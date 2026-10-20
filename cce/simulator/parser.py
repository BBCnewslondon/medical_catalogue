"""Scenario & Event Parser for CCE Synthetic Benchmarks.

Parses 'SYNTHETIC CASES V1.csv' into strongly-typed SyntheticScenario specifications
and chronological TimelineEvent streams for simulated execution.
"""

import csv
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cce.enums import (
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.events import (
    AmbiguousEvidenceFlaggedEvent,
    ClinicalReviewDocumentedEvent,
    ClockTickEvent,
    DiagnosticReportReceivedEvent,
    DomainEvent,
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)
from cce.models import Obligation

DEFAULT_BASE_DATE: datetime = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)

# Standard clinical procedure/action codes mapped to synthetic cases
DEFAULT_ACTION_CODES: dict[str, str] = {
    "CCE-001": "REPEAT_RENAL_PROFILE",
    "CCE-002": "REPEAT_UES",
    "CCE-003": "METHOTREXATE_MONITORING",
    "CCE-004": "METHOTREXATE_MONITORING",
    "CCE-005": "REPEAT_RENAL_PROFILE",
    "CCE-006": "MRI_BRAIN",
    "CCE-007": "CT_CHEST",
    "CCE-008": "CARDIOLOGY_OUTPATIENT_REVIEW",
    "CCE-009": "SPIRONOLACTONE_MONITORING",
    "CCE-010": "REPEAT_FBC",
}


def calculate_headline(obligation: Obligation) -> str:
    """Calculate the clinical headline summary badge for an obligation.

    Reflects the highest-priority status dimension following NHS clinical risk hierarchy:
    1. Terminal states (COMPLETE, SUPERSEDED, CANCELLED)
    2. Evidence ambiguity or review requirements (AMBIGUOUS_REVIEW_EVIDENCE, AWAITING_REVIEW_EVIDENCE)
    3. Accountable ownership failures (NO_OWNER)
    4. Timeliness breaches (OVERDUE, DUE)
    5. Fallback lifecycle status
    """
    if obligation.lifecycle_status == LifecycleStatus.COMPLETE:
        return "COMPLETE"
    if obligation.lifecycle_status == LifecycleStatus.SUPERSEDED:
        return "SUPERSEDED"
    if obligation.lifecycle_status == LifecycleStatus.CANCELLED:
        return "CANCELLED"

    if obligation.evidence_review_status == EvidenceReviewStatus.AMBIGUOUS_REVIEW_EVIDENCE:
        return "AMBIGUOUS_REVIEW_EVIDENCE"
    if obligation.evidence_review_status == EvidenceReviewStatus.AWAITING_REVIEW_EVIDENCE:
        return "AWAITING_REVIEW_EVIDENCE"

    if obligation.ownership_status == OwnershipStatus.NO_OWNER:
        return "NO_OWNER"

    if obligation.timeliness_status == TimelinessStatus.OVERDUE:
        return "OVERDUE"
    if obligation.timeliness_status == TimelinessStatus.DUE:
        return "DUE"

    return (
        obligation.lifecycle_status.value
        if hasattr(obligation.lifecycle_status, "value")
        else str(obligation.lifecycle_status)
    )


def calculate_should_flag(obligation: Obligation) -> bool:
    """Determine whether the obligation currently represents an active clinical safety risk.

    Flags obligations that are OVERDUE, have NO_OWNER, or are AWAITING_REVIEW_EVIDENCE.
    """
    headline = calculate_headline(obligation)
    return headline in ("OVERDUE", "NO_OWNER", "AWAITING_REVIEW_EVIDENCE")


@dataclass
class TimelineEvent:
    """Chronological event extracted from a scenario's events timeline."""

    day: int
    event_token: str
    description: str
    action_code: str = ""
    case_id: str = ""
    replacement_case_id: str | None = None
    is_external_observation_only: bool = False

    def build_domain_event(
        self,
        obligation_id: uuid.UUID,
        simulated_time: datetime,
        action_code: str | None = None,
        replacement_obligation_id: uuid.UUID | None = None,
    ) -> DomainEvent | None:
        """Transform this timeline event into a strongly typed domain event for dispatch.

        Returns None if this event is an inert external observation that does not
        mutate CCE state (e.g. cancelled booking, opened report read receipt).
        """
        code = action_code or self.action_code or "DEFAULT_ACTION"

        if self.event_token == "OBLIGATION_CONFIRMED":
            return HumanConfirmEvent(
                event_id=uuid.uuid4(),
                actor_id="dr_clinician",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                rationale_text=self.description
                or "Human clinician confirmed draft obligation into ACTIVE",
            )

        if self.event_token in ("RESULT_AVAILABLE", "TEST_PERFORMED"):
            # If this is marked as an observation only (e.g. sample collected on same day as result)
            if self.is_external_observation_only:
                return None
            return DiagnosticReportReceivedEvent(
                event_id=uuid.uuid4(),
                actor_id="PATHOLOGY_SYSTEM",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                report_id=f"LAB-{self.case_id or 'REPORT'}-{self.day}",
                action_code=code,
                report_payload={"findings": self.description},
            )

        if self.event_token == "REVIEW_NOTE":
            return ClinicalReviewDocumentedEvent(
                event_id=uuid.uuid4(),
                actor_id="dr_reviewer",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                review_note_id=f"REV-NOTE-{self.case_id or 'NOTE'}-{self.day}",
                attribution="Reviewing Clinician",
                review_notes=self.description,
            )

        if self.event_token == "FREE_TEXT_NOTE":
            return AmbiguousEvidenceFlaggedEvent(
                event_id=uuid.uuid4(),
                actor_id="NLP_MATCHER",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                evidence_snippet={"raw_text": self.description},
                confidence_score=0.60,
                reason_code="FREE_TEXT_REVIEW",
                ambiguity_rationale=self.description,
            )

        if self.event_token == "NO_REVIEW_EVIDENCE":
            return AmbiguousEvidenceFlaggedEvent(
                event_id=uuid.uuid4(),
                actor_id="SYSTEM_MONITOR",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                evidence_snippet={
                    "reason": "Result exists but review evidence has not appeared within benchmark review window."
                },
                confidence_score=0.0,
                reason_code="NO_REVIEW_EVIDENCE",
                ambiguity_rationale=self.description,
            )

        if self.event_token in ("PLAN_CHANGED", "SUPERSESSION_LINK"):
            if self.is_external_observation_only:
                return None
            return SupersedePlanEvent(
                event_id=uuid.uuid4(),
                actor_id="dr_attending",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                superseded_by_id=replacement_obligation_id,
                migration_flag=(
                    "CARE_PLAN_REPLACED" if replacement_obligation_id is None else None
                ),
                reason_code="CLINICAL_PLAN_CHANGED",
                rationale_text=self.description
                or "Clinical plan legitimately changed; replaced by successor",
            )

        if self.event_token == "MANUAL_COMPLETE_ATTEMPT":
            # Testing defensive guard rejection: constructed without mandatory rationale
            return ManualOverrideEvent.model_construct(
                event_id=uuid.uuid4(),
                actor_id="dashboard_user",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                reason_code="MANUAL_CLOSE",
                rationale_text="",  # Intentionally blank to test guard rejection
            )

        if self.event_token == "CLOCK_ADVANCE":
            return ClockTickEvent(
                event_id=uuid.uuid4(),
                actor_id="SYSTEM_CLOCK",
                obligation_id=obligation_id,
                timestamp=simulated_time,
                current_simulated_time=simulated_time,
            )

        # Informational EHR observations: APPOINTMENT_BOOKED, APPOINTMENT_CANCELLED,
        # NO_REBOOKING, REPORT_OPENED, NO_ACTION, DISCHARGED, NO_APPOINTMENT, NO_EVENT
        return None


@dataclass
class SyntheticScenario:
    """Strongly-typed synthetic scenario loaded from SYNTHETIC CASES V1.csv."""

    case_id: str
    title: str
    benchmark_role: str
    age: int
    sex: str
    setting: str
    source_note: str
    action: str
    action_code: str
    owner: str | None
    created_day: int
    due_day: int
    requires_review_evidence: bool
    raw_events: str
    timeline_events: list[TimelineEvent] = field(default_factory=list)

    # Expected Ground Truth
    expected_lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    expected_timeliness_status: TimelinessStatus = TimelinessStatus.NOT_DUE
    expected_evidence_review_status: EvidenceReviewStatus = EvidenceReviewStatus.NO_EVIDENCE
    expected_ownership_status: OwnershipStatus = OwnershipStatus.OWNED
    expected_review_item: dict[str, Any] | None = None
    expected_headline: str = ""
    should_flag: bool = False
    expected_system_behaviour: str = ""
    engine_test_focus: str = ""
    source_urls: list[str] = field(default_factory=list)

    @property
    def has_confirmation_event(self) -> bool:
        """Check whether the scenario explicitly models draft confirmation."""
        return any(e.event_token == "OBLIGATION_CONFIRMED" for e in self.timeline_events)

    def get_reference_datetime(self, day: int, base_date: datetime = DEFAULT_BASE_DATE) -> datetime:
        """Map a relative day offset to an absolute UTC datetime."""
        return base_date + timedelta(days=day)


class ScenarioParser:
    """Parser that converts SYNTHETIC CASES V1.csv into executable simulation scenarios."""

    EVENT_REGEX = re.compile(r"^Day\s+(\d+):\s*([A-Za-z0-9_]+)(?:\s*[\u2014\u2013\-]\s*(.*))?$")

    @classmethod
    def parse_file(
        cls, csv_path: str | Path, base_date: datetime = DEFAULT_BASE_DATE
    ) -> list[SyntheticScenario]:
        """Read and parse all benchmark scenarios from a CSV file."""
        path = Path(csv_path)
        if not path.is_file():
            raise FileNotFoundError(f"Synthetic cases CSV not found at: {path}")

        scenarios: list[SyntheticScenario] = []
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                scenarios.append(cls.parse_row(row, base_date=base_date))

        return scenarios

    @classmethod
    def parse_row(
        cls, row: dict[str, str], base_date: datetime = DEFAULT_BASE_DATE
    ) -> SyntheticScenario:
        """Parse an individual CSV row into a SyntheticScenario."""
        case_id = row["case_id"].strip()
        action = row["action"].strip()
        action_code = DEFAULT_ACTION_CODES.get(
            case_id, re.sub(r"[^A-Z0-9_]", "_", action[:30].upper())
        )

        owner_raw = row.get("owner", "").strip()
        owner = owner_raw if owner_raw else None

        created_day = int(row.get("created_day", 0))
        due_day = int(row.get("due_day", 0))
        requires_review = row.get("requires_review_evidence", "").strip().lower() == "true"

        raw_events = row.get("events", "")
        timeline_events = cls.parse_events(raw_events, case_id=case_id, action_code=action_code)

        # Parse expected ground truth
        expected_lifecycle = LifecycleStatus(row["lifecycle_status"].strip())
        expected_timeliness = TimelinessStatus(row["timeliness_status"].strip())
        expected_evidence = EvidenceReviewStatus(row["evidence_review_status"].strip())
        expected_ownership = OwnershipStatus(row["ownership_status"].strip())

        review_item_raw = row.get("expected_review_item", "").strip()
        expected_review_item = json.loads(review_item_raw) if review_item_raw else None

        expected_headline = row.get("expected_headline", "").strip()
        should_flag = row.get("should_flag", "").strip().lower() == "true"
        expected_behaviour = row.get("expected_system_behaviour", "").strip()
        test_focus = row.get("engine_test_focus", "").strip()

        source_urls_raw = row.get("source_urls", "")
        source_urls = [u.strip() for u in source_urls_raw.split("|") if u.strip()]

        return SyntheticScenario(
            case_id=case_id,
            title=row.get("title", "").strip(),
            benchmark_role=row.get("benchmark_role", "").strip(),
            age=int(row.get("age", 0)),
            sex=row.get("sex", "").strip(),
            setting=row.get("setting", "").strip(),
            source_note=row.get("source_note", "").strip(),
            action=action,
            action_code=action_code,
            owner=owner,
            created_day=created_day,
            due_day=due_day,
            requires_review_evidence=requires_review,
            raw_events=raw_events,
            timeline_events=timeline_events,
            expected_lifecycle_status=expected_lifecycle,
            expected_timeliness_status=expected_timeliness,
            expected_evidence_review_status=expected_evidence,
            expected_ownership_status=expected_ownership,
            expected_review_item=expected_review_item,
            expected_headline=expected_headline,
            should_flag=should_flag,
            expected_system_behaviour=expected_behaviour,
            engine_test_focus=test_focus,
            source_urls=source_urls,
        )

    @classmethod
    def parse_events(cls, events_str: str, case_id: str, action_code: str) -> list[TimelineEvent]:
        """Parse pipe-separated events timeline into a list of TimelineEvents."""
        timeline_events: list[TimelineEvent] = []
        raw_tokens = [t.strip() for t in events_str.split("|") if t.strip()]

        raw_parsed: list[tuple[int, str, str]] = []
        for raw in raw_tokens:
            m = cls.EVENT_REGEX.match(raw)
            if not m:
                continue
            day = int(m.group(1))
            token = m.group(2).strip()
            desc = m.group(3).strip() if m.group(3) else ""
            raw_parsed.append((day, token, desc))

        # Check for co-located events on same day that pair or consolidate
        days_seen: set[int] = {d for d, _, _ in raw_parsed}

        for day in sorted(days_seen):
            day_events = [(t, desc) for d, t, desc in raw_parsed if d == day]
            tokens_on_day = [t for t, _ in day_events]

            # If both TEST_PERFORMED and RESULT_AVAILABLE appear on same day:
            # TEST_PERFORMED is noted as specimen collection; RESULT_AVAILABLE carries diagnostic report
            has_test = "TEST_PERFORMED" in tokens_on_day
            has_result = "RESULT_AVAILABLE" in tokens_on_day

            # If both PLAN_CHANGED and SUPERSESSION_LINK appear on same day:
            # They pair into a single SupersedePlanEvent
            has_plan_changed = "PLAN_CHANGED" in tokens_on_day
            has_supersession = "SUPERSESSION_LINK" in tokens_on_day

            for token, desc in day_events:
                is_obs_only = False
                replacement_case_id = None

                if has_test and has_result and token == "TEST_PERFORMED":
                    is_obs_only = True

                if has_plan_changed and has_supersession:
                    if token == "SUPERSESSION_LINK":
                        is_obs_only = True
                    elif token == "PLAN_CHANGED":
                        # Find link target from description or fellow event
                        link_event = next(
                            (d for t, d in day_events if t == "SUPERSESSION_LINK"),
                            "",
                        )
                        match_r = re.search(r"(CCE-\d+-R\d+)", link_event)
                        if match_r:
                            replacement_case_id = match_r.group(1)

                timeline_events.append(
                    TimelineEvent(
                        day=day,
                        event_token=token,
                        description=desc,
                        action_code=action_code,
                        case_id=case_id,
                        replacement_case_id=replacement_case_id,
                        is_external_observation_only=is_obs_only,
                    )
                )

        return timeline_events
