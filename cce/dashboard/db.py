"""Database layer, SQLite fallback adapters, and domain orchestration for the CCE Dashboard."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, desc, event, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.ddl import CreateColumn

from cce.audit import (
    AuditViolationError,
    InvalidStateTransitionError,
    register_audit_listeners,
)
from cce.engine.state_machine import TERMINAL_LIFECYCLE_STATUSES
from cce.enums import (
    AmbiguousItemStatus,
    AuditEventType,
    EvidenceReviewStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.events import (
    AmbiguousEvidenceFlaggedEvent,
    AssignOwnershipEvent,
    CancelObligationEvent,
    ClinicalReviewDocumentedEvent,
    ClockTickEvent,
    DiagnosticReportReceivedEvent,
    DomainEvent,
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)
from cce.models import AmbiguousReviewItem, Base, Obligation, ObligationAuditLog
from cce.service import ObligationService
from cce.simulator.parser import (
    DEFAULT_BASE_DATE,
    ScenarioParser,
    SyntheticScenario,
    calculate_headline,
    calculate_should_flag,
)
from cce.simulator.runner import ScenarioRunner, ScenarioRunResult

# ==============================================================================
# SQLite DDL Compatibility Adapters (preserve PostgreSQL JSONB/UUID DDL unchanged)
# ==============================================================================


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(element: PG_UUID[Any], compiler: Any, **kw: Any) -> str:
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element: JSONB, compiler: Any, **kw: Any) -> str:
    return "JSON"


@compiles(CreateColumn, "sqlite")
def _compile_create_column_sqlite(element: CreateColumn, compiler: Any, **kw: Any) -> str:
    column = element.element
    original_default = column.server_default
    if original_default is not None:
        default_sql = str(getattr(original_default, "arg", original_default)).lower()
        if "gen_random_uuid" in default_sql or "clock_timestamp" in default_sql:
            column.server_default = None
            try:
                return str(compiler.visit_create_column(element, **kw))
            finally:
                column.server_default = original_default
    return str(compiler.visit_create_column(element, **kw))


_AUDIT_LISTENER_LOCK = threading.Lock()
_AUDIT_LISTENERS_REGISTERED = False

_DT_ATTRS_BY_MODEL: tuple[tuple[type[Any], tuple[str, ...]], ...] = (
    (Obligation, ("due_window_start", "due_window_end", "created_at", "updated_at")),
    (ObligationAuditLog, ("created_at",)),
    (AmbiguousReviewItem, ("due_at", "created_at", "updated_at")),
)


def _normalize_sqlite_datetimes(target: Any, _context: Any, attrs: tuple[str, ...]) -> None:
    for attr in attrs:
        val = getattr(target, attr, None)
        if isinstance(val, datetime) and val.tzinfo is None:
            set_committed_value(target, attr, val.replace(tzinfo=UTC))


def _ensure_audit_listeners() -> None:
    global _AUDIT_LISTENERS_REGISTERED
    with _AUDIT_LISTENER_LOCK:
        if not _AUDIT_LISTENERS_REGISTERED:
            register_audit_listeners()
            for model_cls, dt_attrs in _DT_ATTRS_BY_MODEL:

                def _make_loader(
                    field_names: tuple[str, ...],
                ) -> Any:
                    def _on_load(target: Any, context: Any) -> None:
                        _normalize_sqlite_datetimes(target, context, field_names)

                    return _on_load

                event.listen(model_cls, "load", _make_loader(dt_attrs))
            _AUDIT_LISTENERS_REGISTERED = True


DEFAULT_CSV_PATH = Path(__file__).resolve().parents[2] / "SYNTHETIC CASES V1.csv"


_PATIENT_DIRECTORY: dict[str, dict[str, Any]] = {
    "CCE-001": {
        "patient_name": "Elena Rostova",
        "mrn": "MRN-49201-R",
        "demographics": "58F • Primary Care Clinic",
        "clinician": "Dr. Aris Thorne, MD",
        "team": "Primary Care Team A",
        "origin": "Outpatient EHR Order Entry",
        "order_ref": "#OBL-2026-0101",
    },
    "CCE-002": {
        "patient_name": "Marcus Vance",
        "mrn": "MRN-94821-T",
        "demographics": "64M • Cardiology Telemetry",
        "clinician": "Dr. Julian Vance, MD",
        "team": "Cardiology Service",
        "origin": "Inpatient Cardiology Ward 4B",
        "order_ref": "#OBL-2026-0102",
    },
    "CCE-003": {
        "patient_name": "Arthur Pendelton",
        "mrn": "MRN-11294-P",
        "demographics": "69M • Chest Pain Unit",
        "clinician": "Dr. S. Lin, MD",
        "team": "Acute Medicine Team",
        "origin": "HL7v2 ORU^R01 Lab Feed",
        "order_ref": "#OBL-2026-0103",
        "confidence": 0.72,
        "raw_hl7": (
            "MSH|^~\\&|LABSYS|MERCY_HOSP|CCE_CORE|ACUTE|202604051415||ORU^R01|MSG00391|P|2.5.1\n"
            "PID|1||MRN-11294-P^^^MERCY||Pendelton^Arthur||19570214|M\n"
            "OBR|1|ORD-88912|LAB-99301|30522-7^hs-CRP / Cardiac Risk^LN|||202604051355\n"
            "OBX|1|NM|30522-7^Cardiac Panel^LN||0.09|ng/mL|<0.04|HH|||F|||202604051412\n"
            "NTE|1||Result posted to portal without signed clinician attenuation note."
        ),
        "discrepancy": (
            "Diagnostic report landed in external lab interface 48h ago, but NO signed clinical "
            "review note or EHR acknowledgement has been attested by the ordering clinician."
        ),
        "alignment": [
            {
                "field": "Patient Identity & DOB",
                "status": "EXACT",
                "detail": "MRN-11294-P (100% Match)",
            },
            {
                "field": "Required Action Code",
                "status": "MATCH",
                "detail": "Matched LAB_RESULT_FOLLOWUP",
            },
            {
                "field": "Clinician Review Attestation",
                "status": "MISSING",
                "detail": "No signed Progress Note found",
            },
            {
                "field": "SLA Review Window",
                "status": "OVERDUE",
                "detail": "+24h past review verification target",
            },
        ],
    },
    "CCE-004": {
        "patient_name": "Clara Oswald",
        "mrn": "MRN-77312-O",
        "demographics": "47F • Pulmonology Consult",
        "clinician": "Dr. Elena Park, MD",
        "team": "Thoracic Oncology & Pulm",
        "origin": "External Imaging DICOM / HL7 MDM",
        "order_ref": "#OBL-2026-0104",
        "confidence": 0.61,
        "raw_hl7": (
            "MSH|^~\\&|RAD_EXT|ST_JUDE_IMG|CCE_CORE|PULM|202604041030||ORU^R01|MSG00418|P|2.5.1\n"
            "PID|1||MRN-77312-O^^^MERCY||Oswald^Clara||19790822|F\n"
            "OBR|1|EXT-4410|IMG-7721|24627-2^CT Chest w/o Contrast^LN|||202604040945\n"
            "OBX|1|TX|24627-2^Impression^LN||4mm subpleural nodule RLL; external read preliminary; correlate with prior 2024 scan not attached.||||||P\n"
            "NTE|1||Ambiguous accession cross-reference: order code differs from outpatient PET-CT request."
        ),
        "discrepancy": (
            "Free-text external radiology addendum references unattached 2024 baseline films and "
            "carries preliminary (P) status with partial accession match (61% heuristic confidence)."
        ),
        "alignment": [
            {
                "field": "Patient Identity & DOB",
                "status": "EXACT",
                "detail": "MRN-77312-O Verified",
            },
            {
                "field": "Procedure LOINC Mapping",
                "status": "PARTIAL",
                "detail": "CT Chest vs PET-CT order code ambiguity",
            },
            {
                "field": "Report Finalization",
                "status": "WARNING",
                "detail": "HL7 OBX-11 Status = 'P' (Preliminary)",
            },
            {
                "field": "Temporal Sequence",
                "status": "MATCH",
                "detail": "Within 48h expected completion window",
            },
        ],
    },
    "CCE-005": {
        "patient_name": "David Chen",
        "mrn": "MRN-61045-C",
        "demographics": "76M • Transitional Care",
        "clinician": "Unassigned Discharge Pool",
        "team": None,
        "origin": "Discharge Summary NLP Extractor",
        "order_ref": "#OBL-2026-0105",
    },
    "CCE-006": {
        "patient_name": "Sofia Patel",
        "mrn": "MRN-38492-S",
        "demographics": "52F • Gastroenterology",
        "clinician": "Dr. Maya Nair, MD",
        "team": "GI Endoscopy Unit",
        "origin": "Plan Supersession Link",
        "order_ref": "#OBL-2026-0106",
    },
    "CCE-007": {
        "patient_name": "Robert Miller",
        "mrn": "MRN-52910-M",
        "demographics": "61M • Orthopedics",
        "clinician": "Dr. Kevin Grant, MD",
        "team": "Orthopedic Surgery",
        "origin": "Outpatient Cancel Order",
        "order_ref": "#OBL-2026-0107",
    },
    "CCE-008": {
        "patient_name": "Hannah Kim",
        "mrn": "MRN-20841-K",
        "demographics": "39F • Neurology",
        "clinician": "Dr. Omar Farah, MD",
        "team": "Neurovascular Team",
        "origin": "EHR Scheduling & Discharge Feed",
        "order_ref": "#OBL-2026-0108",
    },
    "CCE-009": {
        "patient_name": "Thomas Wright",
        "mrn": "MRN-73190-W",
        "demographics": "81M • Geriatric Medicine",
        "clinician": "Dr. Priya Kapoor, MD",
        "team": "Acute Geriatrics",
        "origin": "HL7 Action Code Mismatch Monitor",
        "order_ref": "#OBL-2026-0109",
    },
    "CCE-010": {
        "patient_name": "Beatrice Alvarez",
        "mrn": "MRN-66512-A",
        "demographics": "67F • Surgical ICU",
        "clinician": "Dr. S. Lin, MD",
        "team": "Critical Care Oversight",
        "origin": "Anti-Gaming Policy Sentinel",
        "order_ref": "#OBL-2026-0110",
    },
    "CCE-LAB-842": {
        "patient_name": "Eleanor Vance",
        "mrn": "MRN-88412-V",
        "demographics": "72F • Cardiology Ward 4B",
        "clinician": "Dr. Julian Vance, MD",
        "team": "Acute Cardiology Service",
        "origin": "HL7v2 ORU^R01 Cardiology Interface",
        "order_ref": "#OBL-2026-0842",
        "confidence": 0.84,
        "raw_hl7": (
            "MSH|^~\\&|CARD_LAB|MERCY_ACUTE|CCE_ENGINE|CARD_4B|202604050842||ORU^R01|MSG00842|P|2.5.1\n"
            "PID|1||MRN-88412-V^^^MERCY||Vance^Eleanor||19540319|F\n"
            "OBR|1|ORD-2026-0842|LAB-88412|10839-9^Troponin I.cardiac^LN|||202604050824\n"
            "OBX|1|NM|10839-9^Troponin I.cardiac^LN||0.42|ng/mL|<0.04|HH|||P|||202604050840\n"
            "NTE|1||Specimen drawn 18 min past Q4H window; mild hemolysis noted — repeat recommended if clinically discordant."
        ),
        "discrepancy": (
            "Serial Troponin-I elevation (0.42 ng/mL, critical high) arrived 18 minutes outside "
            "scheduled Q4H collection window with lab comment noting mild specimen hemolysis."
        ),
        "alignment": [
            {
                "field": "Patient Identity & DOB",
                "status": "EXACT",
                "detail": "Vance, Eleanor • MRN-88412-V (100% Match)",
            },
            {
                "field": "Order Reference",
                "status": "EXACT",
                "detail": "#OBL-2026-0842 matched external OBR-2",
            },
            {
                "field": "Analyte & Clinical Intent",
                "status": "MATCH",
                "detail": "LOINC 10839-9 -> LAB_RESULT_FOLLOWUP",
            },
            {
                "field": "Specimen Timing / Hemolysis",
                "status": "WARNING",
                "detail": "+18 min Q4H variance & lab NTE addendum",
            },
        ],
    },
}


class DashboardDatabase:
    """Thread-safe persistence and CCE orchestration controller for the oversight dashboard."""

    def __init__(
        self,
        database_url: str | None = None,
        csv_path: str | Path | None = None,
        auto_seed: bool = True,
    ) -> None:
        _ensure_audit_listeners()
        self.csv_path = Path(csv_path) if csv_path else DEFAULT_CSV_PATH
        self.lock = threading.RLock()
        self.backend_name = "sqlite"
        self.fallback_reason: str | None = None
        self.database_url = self._resolve_engine_url(database_url)
        self.engine = self._create_configured_engine(self.database_url)
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False)

        self.obligation_meta: dict[str, dict[str, Any]] = {}
        self.review_meta: dict[str, dict[str, Any]] = {}
        self.anti_gaming_rejections: list[dict[str, Any]] = []
        self.adjudication_history: list[dict[str, Any]] = []
        self.benchmark_results: dict[str, dict[str, Any]] = {}
        self.selected_case_id: str = "ALL"

        if auto_seed:
            self.reset_and_seed()

    def _resolve_engine_url(self, explicit_url: str | None) -> str:
        candidate = (
            explicit_url
            or os.environ.get("CCE_DASHBOARD_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
        )
        if candidate and candidate.startswith("postgresql"):
            probe = create_engine(candidate, pool_pre_ping=True)
            try:
                with probe.connect() as conn:
                    conn.execute(text("SELECT 1"))
                self.backend_name = "postgresql"
                return candidate
            except Exception as exc:  # noqa: BLE001
                self.fallback_reason = (
                    f"PostgreSQL unavailable ({exc}); using SQLite in-memory engine"
                )
                probe.dispose()
                return "sqlite+pysqlite:///:memory:"
            finally:
                probe.dispose()

        if candidate:
            if candidate.startswith("sqlite"):
                self.backend_name = "sqlite"
                return candidate
            return candidate

        return "sqlite+pysqlite:///:memory:"

    def _create_configured_engine(self, url: str) -> Engine:
        if url.startswith("sqlite"):
            kwargs: dict[str, Any] = {
                "connect_args": {"check_same_thread": False},
                "future": True,
            }
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
            return create_engine(url, **kwargs)
        return create_engine(url, pool_pre_ping=True, future=True)

    def close(self) -> None:
        """Dispose underlying SQLAlchemy connection pool cleanly."""
        self.engine.dispose()

    def reset_and_seed(self) -> None:
        """Reset schema and seed authentic obligations, benchmark runs, and queue items."""
        with self.lock:
            Base.metadata.drop_all(self.engine)
            Base.metadata.create_all(self.engine)

            self.selected_case_id = "ALL"
            self.obligation_meta.clear()
            self.review_meta.clear()
            self.anti_gaming_rejections.clear()
            self.adjudication_history.clear()
            self.benchmark_results = self._compute_benchmark_snapshots()

            with self.SessionFactory() as session:
                self._seed_live_workspace(session)
                session.commit()

    def _compute_benchmark_snapshots(self) -> dict[str, dict[str, Any]]:
        """Execute all CSV synthetic cases cleanly in an isolated SQLite DB for audit playback."""
        bench_engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bench_engine)
        snapshots: dict[str, dict[str, Any]] = {}
        try:
            BenchSession = sessionmaker(bind=bench_engine, expire_on_commit=False)
            with BenchSession() as session:
                if not self.csv_path.exists():
                    return snapshots
                runner = ScenarioRunner(
                    session, csv_path=self.csv_path, base_date=DEFAULT_BASE_DATE
                )
                results = runner.run_all()
                for case_id, res in sorted(results.items()):
                    snapshots[case_id] = self._serialize_benchmark_result(res)
        finally:
            bench_engine.dispose()
        return snapshots

    def _serialize_benchmark_result(self, res: ScenarioRunResult) -> dict[str, Any]:
        profile = _PATIENT_DIRECTORY.get(res.case_id, {})
        steps_out: list[dict[str, Any]] = []
        for step in res.step_results:
            state = step.state_after_step
            steps_out.append(
                {
                    "day": step.day,
                    "simulated_time": step.simulated_time.isoformat(),
                    "ingested_events": step.ingested_events,
                    "audit_logs_created": step.audit_logs_created,
                    "rejections": step.rejections,
                    "state": {
                        "lifecycle": state.lifecycle_status.value if state else None,
                        "timeliness": state.timeliness_status.value if state else None,
                        "evidence_review": state.evidence_review_status.value if state else None,
                        "ownership": state.ownership_status.value if state else None,
                    },
                    "headline": step.headline_after_step,
                    "should_flag": step.should_flag_after_step,
                    "review_items_count": step.review_items_count,
                }
            )
        return {
            "case_id": res.case_id,
            "title": res.scenario.title,
            "benchmark_role": res.scenario.benchmark_role,
            "patient_name": profile.get("patient_name", res.case_id),
            "mrn": profile.get("mrn", f"MRN-{res.case_id}"),
            "action": res.scenario.action,
            "action_code": res.scenario.action_code,
            "setting": res.scenario.setting,
            "owner": res.scenario.owner or "Unassigned",
            "expected": {
                "lifecycle": res.scenario.expected_lifecycle_status.value,
                "timeliness": res.scenario.expected_timeliness_status.value,
                "evidence_review": res.scenario.expected_evidence_review_status.value,
                "ownership": res.scenario.expected_ownership_status.value,
                "headline": res.scenario.expected_headline,
                "should_flag": res.scenario.should_flag,
            },
            "actual": {
                "lifecycle": res.final_state.lifecycle_status.value,
                "timeliness": res.final_state.timeliness_status.value,
                "evidence_review": res.final_state.evidence_review_status.value,
                "ownership": res.final_state.ownership_status.value,
                "headline": res.final_headline,
                "should_flag": res.should_flag,
            },
            "audit_count": len(res.audit_logs),
            "review_items_count": len(res.review_items),
            "rejections": list(res.rejections),
            "validation_errors": list(res.validation_errors),
            "passed": res.success,
            "engine_test_focus": res.scenario.engine_test_focus,
            "expected_system_behaviour": res.scenario.expected_system_behaviour,
            "steps": steps_out,
        }

    def _seed_live_workspace(self, session: Session) -> None:
        scenarios: list[SyntheticScenario] = []
        if self.csv_path.exists():
            scenarios = ScenarioParser.parse_file(self.csv_path, base_date=DEFAULT_BASE_DATE)

        # Replay each synthetic case into the live workspace database via ScenarioRunner
        for scenario in scenarios:
            runner = ScenarioRunner(session, csv_path=self.csv_path, base_date=DEFAULT_BASE_DATE)
            res = runner.run_case(scenario.case_id)
            profile = _PATIENT_DIRECTORY.get(scenario.case_id, {})
            obl_id_str = str(res.obligation.id)
            self.obligation_meta[obl_id_str] = {
                "case_id": scenario.case_id,
                "title": scenario.title,
                **profile,
                "setting": scenario.setting,
                "source_note": scenario.source_note,
            }
            for rej in res.rejections:
                self.anti_gaming_rejections.append(
                    {
                        "id": str(uuid.uuid4()),
                        "case_id": scenario.case_id,
                        "obligation_id": obl_id_str,
                        "patient_name": profile.get("patient_name", scenario.case_id),
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": str(rej.get("event", "MANUAL_OVERRIDE")),
                        "actor_id": "dashboard_user",
                        "reason": str(rej.get("error", "Rejected by CCE invariant")),
                    }
                )
            for item in res.review_items:
                item_id_str = str(item.id)
                snippet = item.proposed_evidence_snippet or {}
                snippet_conf = snippet.get("confidence_score")
                self.review_meta[item_id_str] = {
                    "case_id": scenario.case_id,
                    "confidence": float(
                        profile.get(
                            "confidence", snippet_conf if snippet_conf is not None else 0.65
                        )
                    ),
                    "raw_hl7": profile.get("raw_hl7") or json.dumps(snippet, indent=2),
                    "discrepancy": profile.get("discrepancy")
                    or str(
                        snippet.get("ambiguity_rationale")
                        or snippet.get("reason")
                        or "Requires human clinical attestation."
                    ),
                    "alignment": profile.get("alignment")
                    or [
                        {
                            "field": "Patient Identity",
                            "status": "EXACT",
                            "detail": profile.get("mrn", res.obligation.patient_id),
                        },
                        {
                            "field": "Required Action Code",
                            "status": "PARTIAL",
                            "detail": res.obligation.required_action_code,
                        },
                    ],
                }

        # Seed Stitch's featured Acute Cardiology staging case (Eleanor Vance)
        self._seed_featured_cardiology_case(session)

    def _seed_featured_cardiology_case(self, session: Session) -> None:
        now = datetime.now(UTC)
        profile = _PATIENT_DIRECTORY["CCE-LAB-842"]
        obl = ObligationService.create_obligation(
            session=session,
            patient_id="MRN-88412-V",
            source_evidence={
                "case_id": "CCE-LAB-842",
                "source_note": "ED Cardiology Consult — Serial cardiac biomarker monitoring q4h.",
                "encounter_id": "ENC-2026-88412",
                "origin": profile["origin"],
            },
            required_action_code="LAB_RESULT_FOLLOWUP",
            required_action_description="STAT Troponin-I Serial Protocol (Q4H) — Chest Pain Workup",
            due_window_start=now - timedelta(hours=4),
            due_window_end=now + timedelta(hours=2),
            actor_id="dr_julian_vance",
            assigned_team=profile["team"],
            assigned_user_id="dr_julian_vance",
            reason_code="INITIAL_EXTRACTION",
            rationale_text="Extracted serial cardiac troponin order from Cardiology admission note.",
        )
        obl, _ = ObligationService.process_event(
            session,
            obl,
            HumanConfirmEvent(
                event_id=uuid.uuid4(),
                actor_id="sarah_jensen_rn",
                obligation_id=obl.id,
                timestamp=now - timedelta(hours=3),
                rationale_text="Confirmed Q4H Troponin-I obligation on Telemetry Floor 4B.",
            ),
        )
        obl, _ = ObligationService.process_event(
            session,
            obl,
            AmbiguousEvidenceFlaggedEvent(
                event_id=uuid.uuid4(),
                actor_id="HL7_ORU_INGEST",
                obligation_id=obl.id,
                timestamp=now - timedelta(minutes=18),
                evidence_snippet={
                    "hl7_message_id": "MSG00842",
                    "loinc": "10839-9",
                    "value": "0.42 ng/mL",
                    "abnormal_flag": "HH",
                    "comment": "Specimen drawn 18 min past Q4H window; mild hemolysis noted",
                },
                confidence_score=0.84,
                reason_code="AMBIGUOUS_EVIDENCE_MATCH",
                ambiguity_rationale=profile["discrepancy"],
                due_at=now + timedelta(hours=4),
                assigned_reviewer_id="sarah_jensen_rn",
            ),
        )
        session.flush()
        self.obligation_meta[str(obl.id)] = {
            "case_id": "CCE-LAB-842",
            "title": "STAT Troponin-I Serial Protocol (Q4H)",
            **profile,
            "setting": "Cardiology Ward 4B",
            "source_note": "ED Cardiology Consult — Serial cardiac biomarker monitoring q4h.",
        }
        items = (
            session.execute(
                select(AmbiguousReviewItem).where(AmbiguousReviewItem.obligation_id == obl.id)
            )
            .scalars()
            .all()
        )
        for item in items:
            self.review_meta[str(item.id)] = {
                "case_id": "CCE-LAB-842",
                "confidence": 0.84,
                "raw_hl7": profile["raw_hl7"],
                "discrepancy": profile["discrepancy"],
                "alignment": profile["alignment"],
            }

    def run_scenario(self, case_id: str) -> dict[str, Any]:
        """Run a specific scenario ('CCE-001'..'CCE-010') or reset/run all."""
        with self.lock:
            normalized = case_id.strip().upper()
            if normalized in ("ALL", "RESET"):
                self.selected_case_id = "ALL"
                self.reset_and_seed()
                return self.get_state()

            if normalized not in self.benchmark_results:
                raise ValueError(f"Unknown synthetic case ID: {case_id}")

            self.selected_case_id = normalized
            # Re-run that case in benchmark snapshot and ensure a fresh instance exists in live DB
            bench = self._compute_benchmark_snapshots()
            if normalized in bench:
                self.benchmark_results[normalized] = bench[normalized]
            return self.get_state()

    def obligation_action(
        self,
        obligation_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a strict domain event against an Obligation via ObligationService."""
        with self.lock:
            uid = uuid.UUID(obligation_id)
            actor_id = (
                str(payload.get("actor_id") or "sarah_jensen_rn").strip() or "sarah_jensen_rn"
            )
            now = datetime.now(UTC)

            with self.SessionFactory() as session:
                obl = session.get(Obligation, uid)
                if obl is None:
                    raise KeyError(f"Obligation {obligation_id} not found")

                try:
                    event_obj = self._build_domain_event(obl, action, actor_id, now, payload)
                    obl, audit_log = ObligationService.process_event(session, obl, event_obj)
                    # Resolve open ambiguous review items automatically when clinician confirms review
                    if (
                        action == "document_review"
                        and obl.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE
                    ):
                        open_items = (
                            session.execute(
                                select(AmbiguousReviewItem).where(
                                    AmbiguousReviewItem.obligation_id == obl.id,
                                    AmbiguousReviewItem.status != AmbiguousItemStatus.RESOLVED,
                                )
                            )
                            .scalars()
                            .all()
                        )
                        for item in open_items:
                            item.status = AmbiguousItemStatus.RESOLVED
                            item.assigned_reviewer_id = actor_id
                            item.resolution_rationale = str(
                                payload.get("review_notes") or "Verified via Oversight Ledger."
                            )
                    session.commit()
                except (InvalidStateTransitionError, AuditViolationError, ValidationError) as exc:
                    session.rollback()
                    self._record_rejection(obl, action.upper(), actor_id, str(exc))
                    raise ValueError(str(exc)) from exc

                result_state = self.get_state()
                result_state["last_audit_id"] = str(audit_log.id) if audit_log else None
                result_state["last_action"] = action
                result_state["target_obligation_id"] = str(obl.id)
                return result_state

    def _build_domain_event(
        self,
        obl: Obligation,
        action: str,
        actor_id: str,
        now: datetime,
        payload: dict[str, Any],
    ) -> Any:
        if action == "confirm":
            return HumanConfirmEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                rationale_text=str(
                    payload.get("rationale_text") or "Clinician confirmed obligation."
                ),
            )

        if action == "receive_report":
            return DiagnosticReportReceivedEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                report_id=str(payload.get("report_id") or f"RPT-{uuid.uuid4().hex[:6].upper()}"),
                action_code=str(payload.get("action_code") or obl.required_action_code),
                report_payload={"source": "EHR_INTERFACE", "summary": "Ingested from dashboard"},
            )

        if action == "document_review":
            return ClinicalReviewDocumentedEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                review_note_id=str(
                    payload.get("review_note_id") or f"NOTE-{uuid.uuid4().hex[:6].upper()}"
                ),
                attribution=str(payload.get("attribution") or actor_id),
                reviewer_id=actor_id,
                review_notes=str(
                    payload.get("review_notes") or "Clinician attested diagnostic findings."
                ),
            )

        if action == "claim":
            return AssignOwnershipEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                assigned_user_id=actor_id,
                assigned_team=str(
                    payload.get("assigned_team") or obl.assigned_team or "Oversight Triage Team"
                ),
                reason_code=str(payload.get("reason_code") or "OWNERSHIP_CLAIMED"),
                rationale_text=str(payload.get("rationale_text") or f"Claimed by {actor_id}"),
            )

        if action == "reassign":
            new_user = str(payload.get("assigned_user_id") or "").strip() or None
            new_team = str(payload.get("assigned_team") or "").strip() or None
            if not new_user and not new_team:
                raise ValueError("Attribution reassignment requires a target clinician or team.")
            return AssignOwnershipEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                assigned_user_id=new_user,
                assigned_team=new_team,
                reason_code=str(payload.get("reason_code") or "RC-102"),
                rationale_text=str(
                    payload.get("rationale_text") or "Shift handoff attribution transfer."
                ),
            )

        if action == "override":
            rationale = str(payload.get("rationale_text") or "")
            reason_code = str(payload.get("reason_code") or "RC-101")
            if not rationale.strip():
                # Intentionally route through CCE state machine to test anti-gaming guard
                return ManualOverrideEvent.model_construct(
                    event_id=uuid.uuid4(),
                    actor_id=actor_id,
                    obligation_id=obl.id,
                    timestamp=now,
                    reason_code=reason_code,
                    rationale_text=rationale,
                )
            return ManualOverrideEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                reason_code=reason_code,
                rationale_text=rationale,
            )

        if action == "supersede":
            return SupersedePlanEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                reason_code=str(payload.get("reason_code") or "RC-104"),
                rationale_text=str(
                    payload.get("rationale_text") or "Care plan updated by attending team."
                ),
                migration_flag="CARE_PLAN_REPLACED",
            )

        if action == "cancel":
            return CancelObligationEvent(
                event_id=uuid.uuid4(),
                actor_id=actor_id,
                obligation_id=obl.id,
                timestamp=now,
                reason_code=str(payload.get("reason_code") or "RC-105"),
                rationale_text=str(
                    payload.get("rationale_text") or "Order cancelled per updated clinical status."
                ),
            )

        if action == "clock_tick":
            days = int(payload.get("days", 2))
            sim_time = max(obl.due_window_end + timedelta(days=days), now + timedelta(days=days))
            return ClockTickEvent(
                event_id=uuid.uuid4(),
                actor_id="SYSTEM_CLOCK",
                obligation_id=obl.id,
                timestamp=now,
                current_simulated_time=sim_time,
            )

        raise ValueError(f"Unsupported obligation action: {action}")

    def adjudicate_review_item(
        self,
        item_id: str,
        decision: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Adjudicate an AmbiguousReviewItem via confirm, reject, or clarify."""
        with self.lock:
            uid = uuid.UUID(item_id)
            actor_id = (
                str(payload.get("actor_id") or "sarah_jensen_rn").strip() or "sarah_jensen_rn"
            )
            rationale = str(payload.get("rationale_text") or "").strip()
            now = datetime.now(UTC)

            with self.SessionFactory() as session:
                item = session.get(AmbiguousReviewItem, uid)
                if item is None:
                    raise KeyError(f"Review item {item_id} not found")
                obl = session.get(Obligation, item.obligation_id)
                if obl is None:
                    raise KeyError(f"Obligation {item.obligation_id} not found")

                meta = self.review_meta.get(str(item.id), {})
                obl_meta = self.obligation_meta.get(str(obl.id), {})

                try:
                    event_obj: DomainEvent
                    if decision == "confirm":
                        note_text = (
                            rationale
                            or "Matched external diagnostic result verified against clinical obligation."
                        )
                        event_obj = ClinicalReviewDocumentedEvent(
                            event_id=uuid.uuid4(),
                            actor_id=actor_id,
                            obligation_id=obl.id,
                            timestamp=now,
                            review_note_id=f"ADJ-{item.id.hex[:8].upper()}",
                            attribution=actor_id,
                            reviewer_id=actor_id,
                            review_notes=note_text,
                        )
                        obl, audit_log = ObligationService.process_event(session, obl, event_obj)
                        item.status = AmbiguousItemStatus.RESOLVED
                        item.assigned_reviewer_id = actor_id
                        item.resolution_rationale = note_text
                        outcome_label = "MATCH_CONFIRMED"
                    elif decision == "reject":
                        reason = (
                            rationale
                            or "External HL7 snippet rejected as mismatch; routed to Clinical Triage Pool."
                        )
                        event_obj = AssignOwnershipEvent(
                            event_id=uuid.uuid4(),
                            actor_id=actor_id,
                            obligation_id=obl.id,
                            timestamp=now,
                            assigned_team="Clinical Triage Pool",
                            assigned_user_id=None,
                            reason_code="AMBIGUOUS_MATCH_REJECTED",
                            rationale_text=reason,
                        )
                        obl, audit_log = ObligationService.process_event(session, obl, event_obj)
                        item.status = AmbiguousItemStatus.RESOLVED
                        item.assigned_reviewer_id = actor_id
                        item.resolution_rationale = f"[REJECTED TO TRIAGE] {reason}"
                        outcome_label = "REJECTED_TO_TRIAGE"
                    elif decision == "clarify":
                        note = (
                            rationale
                            or "Manual clarification requested from originating department."
                        )
                        event_obj = AssignOwnershipEvent(
                            event_id=uuid.uuid4(),
                            actor_id=actor_id,
                            obligation_id=obl.id,
                            timestamp=now,
                            assigned_team=obl.assigned_team or "Originating Dept Clarification",
                            assigned_user_id="dr_attending_clarification",
                            reason_code="CLARIFICATION_REQUESTED",
                            rationale_text=note,
                        )
                        obl, audit_log = ObligationService.process_event(session, obl, event_obj)
                        item.assigned_reviewer_id = "dr_attending_clarification"
                        item.resolution_rationale = note
                        outcome_label = "CLARIFICATION_REQUESTED"
                    else:
                        raise ValueError(f"Unsupported adjudication decision: {decision}")

                    session.commit()
                except (InvalidStateTransitionError, AuditViolationError, ValidationError) as exc:
                    session.rollback()
                    self._record_rejection(
                        obl, f"ADJUDICATE_{decision.upper()}", actor_id, str(exc)
                    )
                    raise ValueError(str(exc)) from exc

                audit_hash = hashlib.sha256(
                    f"{audit_log.id}:{audit_log.audit_seq}:{now.isoformat()}".encode()
                    if audit_log
                    else str(item.id).encode()
                ).hexdigest()[:16]

                snippet = item.proposed_evidence_snippet or {}
                fhir_payload = {
                    "resourceType": "Observation",
                    "id": f"obs-{item.id.hex[:8]}",
                    "status": "final" if decision == "confirm" else "preliminary",
                    "code": {
                        "text": obl.required_action_description,
                        "coding": [{"system": "urn:cce:action", "code": obl.required_action_code}],
                    },
                    "subject": {
                        "reference": f"Patient/{obl.patient_id}",
                        "display": obl_meta.get("patient_name", obl.patient_id),
                    },
                    "performer": [{"display": actor_id}],
                    "issued": now.isoformat(),
                    "note": [{"text": rationale or outcome_label}],
                    "meta": {
                        "cceObligationId": str(obl.id),
                        "auditHash": f"sha256:{audit_hash}",
                        "confidenceScore": meta.get(
                            "confidence", snippet.get("confidence_score", 0.75)
                        ),
                    },
                }

                history_entry = {
                    "id": str(item.id),
                    "obligation_id": str(obl.id),
                    "case_id": obl_meta.get("case_id", "CCE-LIVE"),
                    "patient_name": obl_meta.get("patient_name", obl.patient_id),
                    "mrn": obl_meta.get("mrn", obl.patient_id),
                    "action": obl.required_action_description,
                    "decision": outcome_label,
                    "actor_id": actor_id,
                    "resolved_at": now.isoformat(),
                    "audit_hash": audit_hash,
                    "fhir_observation": fhir_payload,
                }
                self.adjudication_history.insert(0, history_entry)

                state = self.get_state()
                state["reconciliation"] = history_entry
                return state

    def simulate_ambiguous_ingestion(self) -> dict[str, Any]:
        """Inject a realistic live HL7 ambiguous ingestion via ObligationService."""
        with self.lock:
            now = datetime.now(UTC)
            with self.SessionFactory() as session:
                obl = ObligationService.create_obligation(
                    session=session,
                    patient_id="MRN-55819-K",
                    source_evidence={
                        "case_id": "CCE-SIM-LIVE",
                        "source_note": "ICU Step-Down Potassium Repletion & BMP Follow-up",
                        "origin": "HL7v2 ORU^R01 Telemetry Feed",
                    },
                    required_action_code="LAB_RESULT_FOLLOWUP",
                    required_action_description="Serum Electrolytes (K+) Post-Repletion Panel",
                    due_window_start=now - timedelta(hours=2),
                    due_window_end=now + timedelta(hours=4),
                    actor_id="sarah_jensen_rn",
                    assigned_team="ICU Step-Down Nursing",
                    assigned_user_id="sarah_jensen_rn",
                    reason_code="LIVE_SIMULATION_INGEST",
                    rationale_text="Simulated order ingested for Ambiguous Review Queue triage.",
                )
                obl, _ = ObligationService.process_event(
                    session,
                    obl,
                    HumanConfirmEvent(
                        event_id=uuid.uuid4(),
                        actor_id="sarah_jensen_rn",
                        obligation_id=obl.id,
                        timestamp=now,
                        rationale_text="Confirmed active bedside lab monitoring obligation.",
                    ),
                )
                obl, _ = ObligationService.process_event(
                    session,
                    obl,
                    AmbiguousEvidenceFlaggedEvent(
                        event_id=uuid.uuid4(),
                        actor_id="HL7_LISTENER_PORT_2575",
                        obligation_id=obl.id,
                        timestamp=now,
                        evidence_snippet={
                            "hl7_message_id": f"MSG{now.strftime('%H%M%S')}",
                            "loinc": "2823-3",
                            "analyte": "Potassium [Moles/volume] in Serum",
                            "value": "3.4 mmol/L",
                            "note": "Point-of-care i-STAT result vs central lab draw variance",
                        },
                        confidence_score=0.79,
                        reason_code="AMBIGUOUS_EVIDENCE_MATCH",
                        ambiguity_rationale=(
                            "POCT i-STAT potassium (3.4 mmol/L) differs from central laboratory specimen "
                            "status; accession prefix 'POC-' requires manual match confirmation."
                        ),
                        due_at=now + timedelta(hours=3),
                        assigned_reviewer_id="sarah_jensen_rn",
                    ),
                )
                session.commit()

                obl_id_str = str(obl.id)
                self.obligation_meta[obl_id_str] = {
                    "case_id": "CCE-SIM-LIVE",
                    "title": "Post-Repletion Potassium Follow-Up",
                    "patient_name": "Nora Delgado",
                    "mrn": "MRN-55819-K",
                    "demographics": "63F • ICU Step-Down",
                    "clinician": "Dr. Aris Thorne, MD",
                    "team": "ICU Step-Down Nursing",
                    "origin": "HL7v2 POCT Interface",
                    "order_ref": f"#OBL-{obl.id.hex[:4].upper()}",
                    "setting": "ICU Step-Down",
                    "source_note": "ICU Step-Down Potassium Repletion & BMP Follow-up",
                }
                items = (
                    session.execute(
                        select(AmbiguousReviewItem).where(
                            AmbiguousReviewItem.obligation_id == obl.id
                        )
                    )
                    .scalars()
                    .all()
                )
                for item in items:
                    self.review_meta[str(item.id)] = {
                        "case_id": "CCE-SIM-LIVE",
                        "confidence": 0.79,
                        "raw_hl7": (
                            f"MSH|^~\\&|ISTAT_POC|MERCY_ICU|CCE_CORE|SDU|{now.strftime('%Y%m%d%H%M')}||ORU^R01|{now.strftime('%H%M%S')}|P|2.5.1\n"
                            "PID|1||MRN-55819-K^^^MERCY||Delgado^Nora||19630412|F\n"
                            "OBR|1|POC-9918|LAB-2823|2823-3^Potassium [Serum/Plasma]^LN\n"
                            "OBX|1|NM|2823-3^Potassium^LN||3.4|mmol/L|3.5-5.1|L|||F\n"
                            "NTE|1||Point-of-care cartridge run during central lab draw transit."
                        ),
                        "discrepancy": (
                            "POCT i-STAT potassium (3.4 mmol/L, borderline low) arrived with POC accession "
                            "identifier instead of central lab order number."
                        ),
                        "alignment": [
                            {
                                "field": "Patient Identity",
                                "status": "EXACT",
                                "detail": "Delgado, Nora • MRN-55819-K",
                            },
                            {
                                "field": "Order Cross-Reference",
                                "status": "PARTIAL",
                                "detail": "POC-9918 vs #OBL-2026",
                            },
                            {
                                "field": "Clinical Analyte",
                                "status": "MATCH",
                                "detail": "Serum K+ / LAB_RESULT_FOLLOWUP",
                            },
                            {
                                "field": "Collection Timing",
                                "status": "WARNING",
                                "detail": "POCT draw 11m before central sample",
                            },
                        ],
                    }

            return self.get_state()

    def _record_rejection(
        self, obl: Obligation, event_name: str, actor_id: str, reason: str
    ) -> None:
        meta = self.obligation_meta.get(str(obl.id), {})
        self.anti_gaming_rejections.insert(
            0,
            {
                "id": str(uuid.uuid4()),
                "case_id": meta.get("case_id", "LIVE"),
                "obligation_id": str(obl.id),
                "patient_name": meta.get("patient_name", obl.patient_id),
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event_name,
                "actor_id": actor_id,
                "reason": reason,
            },
        )

    def get_state(self, active_case_id: str | None = None) -> dict[str, Any]:
        """Serialize complete real-time state of obligations, queue, audit ledger, and scenarios."""
        with self.lock:
            if active_case_id:
                self.selected_case_id = active_case_id.strip().upper()

            with self.SessionFactory() as session:
                obligations = (
                    session.execute(
                        select(Obligation).order_by(
                            desc(Obligation.updated_at), desc(Obligation.created_at)
                        )
                    )
                    .scalars()
                    .all()
                )
                audit_logs = (
                    session.execute(
                        select(ObligationAuditLog).order_by(
                            desc(ObligationAuditLog.created_at), desc(ObligationAuditLog.audit_seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                review_items = (
                    session.execute(
                        select(AmbiguousReviewItem).order_by(desc(AmbiguousReviewItem.created_at))
                    )
                    .scalars()
                    .all()
                )

            logs_by_obl: dict[str, list[dict[str, Any]]] = {}
            obl_by_id = {str(o.id): o for o in obligations}

            governance_logs: list[dict[str, Any]] = []
            for log in audit_logs:
                obl_id_str = str(log.obligation_id)
                meta = self.obligation_meta.get(obl_id_str, {})
                target_obl = obl_by_id.get(obl_id_str)
                entry = {
                    "id": str(log.id),
                    "obligation_id": obl_id_str,
                    "case_id": meta.get("case_id", "CCE-LIVE"),
                    "patient_name": meta.get(
                        "patient_name", target_obl.patient_id if target_obl else obl_id_str[:8]
                    ),
                    "mrn": meta.get("mrn", target_obl.patient_id if target_obl else ""),
                    "action_description": (
                        target_obl.required_action_description if target_obl else ""
                    ),
                    "audit_seq": log.audit_seq,
                    "event_type": log.event_type.value,
                    "actor_id": log.actor_id,
                    "reason_code": log.reason_code,
                    "rationale_text": log.rationale_text,
                    "previous_state": log.previous_state,
                    "new_state": log.new_state,
                    "created_at": log.created_at.isoformat(),
                }
                logs_by_obl.setdefault(obl_id_str, []).append(entry)
                if log.event_type in (
                    AuditEventType.MANUAL_OVERRIDE,
                    AuditEventType.OWNERSHIP_ASSIGNED,
                    AuditEventType.SUPERSEDED,
                    AuditEventType.CANCELLATION,
                    AuditEventType.CONFIRMATION,
                ):
                    governance_logs.append(entry)

            serialized_obligations: list[dict[str, Any]] = []
            active_count = 0
            overdue_count = 0
            unreviewed_count = 0
            no_owner_count = 0

            for obl in obligations:
                obl_id_str = str(obl.id)
                meta = self.obligation_meta.get(obl_id_str, {})
                case_id = str(
                    meta.get("case_id") or (obl.source_evidence or {}).get("case_id") or "CCE-LIVE"
                )
                headline = calculate_headline(obl)
                should_flag = calculate_should_flag(obl)
                obl_logs = logs_by_obl.get(obl_id_str, [])

                if obl.lifecycle_status not in TERMINAL_LIFECYCLE_STATUSES:
                    active_count += 1
                if obl.timeliness_status == TimelinessStatus.OVERDUE:
                    overdue_count += 1
                if obl.evidence_review_status in (
                    EvidenceReviewStatus.AWAITING_REVIEW_EVIDENCE,
                    EvidenceReviewStatus.AMBIGUOUS_REVIEW_EVIDENCE,
                    EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED,
                ):
                    unreviewed_count += 1
                if (
                    obl.ownership_status == OwnershipStatus.NO_OWNER
                    and obl.lifecycle_status not in TERMINAL_LIFECYCLE_STATUSES
                ):
                    no_owner_count += 1

                serialized_obligations.append(
                    {
                        "id": obl_id_str,
                        "case_id": case_id,
                        "order_ref": meta.get("order_ref", f"#OBL-{obl.id.hex[:4].upper()}"),
                        "patient_id": obl.patient_id,
                        "patient_name": meta.get("patient_name", obl.patient_id),
                        "mrn": meta.get("mrn", obl.patient_id),
                        "demographics": meta.get("demographics", meta.get("setting", "Acute Care")),
                        "origin": meta.get(
                            "origin",
                            (obl.source_evidence or {}).get("origin", "EHR Clinical Stream"),
                        ),
                        "source_note": meta.get(
                            "source_note",
                            (obl.source_evidence or {}).get("source_note", ""),
                        ),
                        "required_action_code": obl.required_action_code,
                        "required_action_description": obl.required_action_description,
                        "assigned_team": obl.assigned_team,
                        "assigned_user_id": obl.assigned_user_id,
                        "due_window_start": (
                            obl.due_window_start.isoformat() if obl.due_window_start else None
                        ),
                        "due_window_end": obl.due_window_end.isoformat(),
                        "lifecycle_status": obl.lifecycle_status.value,
                        "timeliness_status": obl.timeliness_status.value,
                        "evidence_review_status": obl.evidence_review_status.value,
                        "ownership_status": obl.ownership_status.value,
                        "is_terminal": obl.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES,
                        "headline": headline,
                        "should_flag": should_flag,
                        "audit_count": len(obl_logs),
                        "audit_logs": list(reversed(obl_logs)),
                        "updated_at": obl.updated_at.isoformat(),
                    }
                )

            pending_queue: list[dict[str, Any]] = []
            resolved_queue: list[dict[str, Any]] = []
            for item in review_items:
                item_id_str = str(item.id)
                obl_id_str = str(item.obligation_id)
                target_obl = obl_by_id.get(obl_id_str)
                if target_obl is None:
                    continue
                obl_meta = self.obligation_meta.get(obl_id_str, {})
                rmeta = self.review_meta.get(item_id_str, {})
                snippet = item.proposed_evidence_snippet or {}
                serialized_item = {
                    "id": item_id_str,
                    "obligation_id": obl_id_str,
                    "case_id": rmeta.get("case_id", obl_meta.get("case_id", "CCE-LIVE")),
                    "order_ref": obl_meta.get("order_ref", f"#OBL-{target_obl.id.hex[:4].upper()}"),
                    "patient_name": obl_meta.get("patient_name", target_obl.patient_id),
                    "mrn": obl_meta.get("mrn", target_obl.patient_id),
                    "demographics": obl_meta.get("demographics", "Acute Care"),
                    "clinician": obl_meta.get(
                        "clinician", target_obl.assigned_user_id or "Attending Physician"
                    ),
                    "required_action_code": target_obl.required_action_code,
                    "required_action_description": target_obl.required_action_description,
                    "source_note": obl_meta.get("source_note", ""),
                    "status": item.status.value,
                    "confidence_score": float(
                        rmeta.get("confidence", snippet.get("confidence_score") or 0.75)
                    ),
                    "reason_code": str(snippet.get("reason_code") or "AMBIGUOUS_EVIDENCE_MATCH"),
                    "discrepancy": rmeta.get(
                        "discrepancy",
                        str(
                            snippet.get("ambiguity_rationale")
                            or snippet.get("reason")
                            or "Discrepant diagnostic evidence requires verification."
                        ),
                    ),
                    "raw_hl7": rmeta.get("raw_hl7", json.dumps(snippet, indent=2)),
                    "alignment": rmeta.get("alignment", []),
                    "due_at": item.due_at.isoformat() if item.due_at else None,
                    "assigned_reviewer_id": item.assigned_reviewer_id,
                    "resolved_by": (
                        item.assigned_reviewer_id
                        if item.status == AmbiguousItemStatus.RESOLVED
                        else None
                    ),
                    "resolved_at": (
                        item.updated_at.isoformat()
                        if item.status == AmbiguousItemStatus.RESOLVED
                        else None
                    ),
                    "resolution_notes": item.resolution_rationale,
                    "lifecycle_status": target_obl.lifecycle_status.value,
                    "evidence_review_status": target_obl.evidence_review_status.value,
                }
                if item.status == AmbiguousItemStatus.RESOLVED:
                    resolved_queue.append(serialized_item)
                else:
                    pending_queue.append(serialized_item)

            passed_benchmarks = sum(
                1 for b in self.benchmark_results.values() if b.get("passed", False)
            )
            total_benchmarks = len(self.benchmark_results)

            return {
                "telemetry": {
                    "backend": self.backend_name,
                    "fallback_reason": self.fallback_reason,
                    "selected_case_id": self.selected_case_id,
                    "benchmarks_passed": passed_benchmarks,
                    "benchmarks_total": total_benchmarks,
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                "metrics": {
                    "active_obligations": active_count,
                    "overdue_actions": overdue_count,
                    "unreviewed_results": unreviewed_count,
                    "unassigned_owners": no_owner_count,
                    "pending_review_queue": len(pending_queue),
                    "resolved_today": len(self.adjudication_history) + len(resolved_queue),
                    "override_volume_24h": sum(
                        1
                        for g in governance_logs
                        if g["event_type"] == AuditEventType.MANUAL_OVERRIDE.value
                    ),
                    "blocked_anti_gaming": len(self.anti_gaming_rejections),
                },
                "obligations": serialized_obligations,
                "review_queue": {
                    "pending": pending_queue,
                    "resolved": resolved_queue,
                    "recently_adjudicated": self.adjudication_history,
                },
                "governance_logs": governance_logs,
                "anti_gaming_rejections": self.anti_gaming_rejections,
                "scenarios": list(self.benchmark_results.values()),
            }
