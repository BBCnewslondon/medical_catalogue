"""Simulation Engine / Time Machine & Scenario Runner for CCE Synthetic Benchmarks.

Coordinates day-by-day simulated timeline progression, event dispatching via ObligationService,
automated ClockTickEvent boundary evaluation, and ground-truth verification against synthetic cases.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cce.audit import InvalidStateTransitionError
from cce.engine.state_machine import TERMINAL_LIFECYCLE_STATUSES, ObligationStateTuple
from cce.enums import (
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.events import ClockTickEvent
from cce.models import AmbiguousReviewItem, Obligation, ObligationAuditLog
from cce.service import ObligationService
from cce.simulator.parser import (
    DEFAULT_BASE_DATE,
    ScenarioParser,
    SyntheticScenario,
    TimelineEvent,
    calculate_headline,
    calculate_should_flag,
)


@dataclass
class SimulationStepResult:
    """Captures detailed diagnostic state for an individual simulated day step."""

    day: int
    simulated_time: datetime
    ingested_events: list[dict[str, Any]] = field(default_factory=list)
    audit_logs_created: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    state_after_step: ObligationStateTuple | None = None
    headline_after_step: str = ""
    should_flag_after_step: bool = False
    review_items_count: int = 0


@dataclass
class ScenarioRunResult:
    """Comprehensive execution report for a synthetic benchmark scenario run."""

    case_id: str
    scenario: SyntheticScenario
    obligation: Obligation
    final_state: ObligationStateTuple
    final_headline: str
    should_flag: bool
    audit_logs: Sequence[ObligationAuditLog]
    review_items: Sequence[AmbiguousReviewItem]
    step_results: list[SimulationStepResult]
    rejections: list[dict[str, Any]]
    success: bool
    validation_errors: list[str] = field(default_factory=list)


class ScenarioRunner:
    """Simulation runner and time machine for CCE synthetic clinical obligations."""

    def __init__(
        self,
        session: Session,
        csv_path: str | Path | None = None,
        base_date: datetime = DEFAULT_BASE_DATE,
    ) -> None:
        self.session = session
        self.base_date = base_date
        self.csv_path = Path(csv_path) if csv_path else Path("SYNTHETIC CASES V1.csv")

        self.scenarios: dict[str, SyntheticScenario] = {}
        if self.csv_path.exists():
            parsed = ScenarioParser.parse_file(self.csv_path, base_date=self.base_date)
            self.scenarios = {s.case_id: s for s in parsed}

        self.current_scenario: SyntheticScenario | None = None
        self.current_obligation: Obligation | None = None
        self.current_day: int = 0
        self.step_history: list[SimulationStepResult] = []
        self.rejections: list[dict[str, Any]] = []
        self.replacement_obligations: dict[str, Obligation] = {}

    def load_scenario(self, scenario_or_id: SyntheticScenario | str) -> Obligation:
        """Initialize and persist the initial Obligation for a scenario in DRAFT or ACTIVE."""
        if isinstance(scenario_or_id, str):
            if scenario_or_id not in self.scenarios:
                raise KeyError(f"Scenario '{scenario_or_id}' not found in loaded CSV cases")
            scenario = self.scenarios[scenario_or_id]
        else:
            scenario = scenario_or_id
            self.scenarios[scenario.case_id] = scenario

        self.current_scenario = scenario
        self.current_day = scenario.created_day
        self.step_history = []
        self.rejections = []
        self.replacement_obligations = {}

        due_dt = scenario.get_reference_datetime(scenario.due_day, self.base_date)

        # Initial lifecycle: DRAFT if case models explicit confirmation, else directly ACTIVE
        initial_lifecycle = (
            LifecycleStatus.DRAFT if scenario.has_confirmation_event else LifecycleStatus.ACTIVE
        )

        ownership_status = OwnershipStatus.OWNED if scenario.owner else OwnershipStatus.NO_OWNER

        source_payload = {
            "case_id": scenario.case_id,
            "setting": scenario.setting,
            "age": scenario.age,
            "sex": scenario.sex,
            "source_note": scenario.source_note,
            "benchmark_role": scenario.benchmark_role,
        }

        obligation = ObligationService.create_obligation(
            session=self.session,
            patient_id=f"PAT-{scenario.case_id}",
            source_evidence=source_payload,
            required_action_code=scenario.action_code,
            required_action_description=scenario.action,
            due_window_start=None,
            due_window_end=due_dt,
            actor_id="SIMULATOR_INGESTION",
            assigned_team=scenario.owner,
            assigned_user_id=None,
            ownership_status=ownership_status,
            lifecycle_status=initial_lifecycle,
            timeliness_status=TimelinessStatus.NOT_DUE,
            evidence_review_status=EvidenceReviewStatus.NO_EVIDENCE,
            reason_code="SYNTHETIC_SCENARIO_INGESTION",
            rationale_text=f"Initial ingestion for scenario {scenario.case_id}: {scenario.title}",
        )
        self.session.flush()

        self.current_obligation = obligation
        return obligation

    def step_to_day(self, target_day: int) -> list[SimulationStepResult]:
        """Advance simulated time incrementally day-by-day up to target_day (inclusive)."""
        if self.current_obligation is None or self.current_scenario is None:
            raise RuntimeError("No scenario loaded. Call load_scenario() before step_to_day().")

        new_steps: list[SimulationStepResult] = []

        while self.current_day <= target_day:
            day = self.current_day
            simulated_time = self.current_scenario.get_reference_datetime(day, self.base_date)

            step_result = SimulationStepResult(
                day=day,
                simulated_time=simulated_time,
            )

            # 1. Locate scheduled timeline events for this day
            day_events: list[TimelineEvent] = [
                e for e in self.current_scenario.timeline_events if e.day == day
            ]

            for ev in day_events:
                rep_id: uuid.UUID | None = None

                # Handle replacement obligation creation for supersession
                if (
                    ev.event_token in ("PLAN_CHANGED", "SUPERSESSION_LINK")
                    and ev.replacement_case_id
                ):
                    if ev.replacement_case_id not in self.replacement_obligations:
                        rep_ob = ObligationService.create_obligation(
                            session=self.session,
                            patient_id=self.current_obligation.patient_id,
                            source_evidence={"superseded_from": self.current_scenario.case_id},
                            required_action_code=f"{self.current_scenario.action_code}_REVISED",
                            required_action_description=f"Replacement care plan for {self.current_scenario.case_id}",
                            due_window_end=simulated_time + timedelta(days=14),
                            lifecycle_status=LifecycleStatus.ACTIVE,
                            assigned_team=self.current_obligation.assigned_team,
                            reason_code="SUPERSESSION_REPLACEMENT",
                            rationale_text=f"Created replacement obligation {ev.replacement_case_id}",
                        )
                        self.session.flush()
                        self.replacement_obligations[ev.replacement_case_id] = rep_ob
                    rep_id = self.replacement_obligations[ev.replacement_case_id].id

                domain_ev = ev.build_domain_event(
                    obligation_id=self.current_obligation.id,
                    simulated_time=simulated_time,
                    action_code=self.current_scenario.action_code,
                    replacement_obligation_id=rep_id,
                )

                if domain_ev is not None:
                    try:
                        self.current_obligation, audit_entry = ObligationService.process_event(
                            self.session, self.current_obligation, domain_ev
                        )
                        self.session.flush()

                        step_result.ingested_events.append(
                            {
                                "token": ev.event_token,
                                "description": ev.description,
                                "domain_event": type(domain_ev).__name__,
                                "dispatched": True,
                                "state_changed": audit_entry is not None,
                            }
                        )
                        if audit_entry is not None:
                            step_result.audit_logs_created.append(
                                {
                                    "audit_seq": audit_entry.audit_seq,
                                    "event_type": audit_entry.event_type.value,
                                    "reason_code": audit_entry.reason_code,
                                    "rationale": audit_entry.rationale_text,
                                }
                            )
                    except (InvalidStateTransitionError, Exception) as exc:
                        # Intentional exception handling (e.g. CCE-010 anti-gaming manual closure rejection)
                        rej_record = {
                            "day": day,
                            "event_token": ev.event_token,
                            "description": ev.description,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        }
                        self.rejections.append(rej_record)
                        step_result.rejections.append(rej_record)
                        step_result.ingested_events.append(
                            {
                                "token": ev.event_token,
                                "description": ev.description,
                                "domain_event": type(domain_ev).__name__,
                                "dispatched": False,
                                "rejected": True,
                                "rejection_reason": str(exc),
                            }
                        )
                else:
                    # Inert external observation (e.g. appointment cancelled, report opened, no action)
                    step_result.ingested_events.append(
                        {
                            "token": ev.event_token,
                            "description": ev.description,
                            "domain_event": None,
                            "dispatched": False,
                            "observation_only": True,
                        }
                    )

            # 2. Automated ClockTickEvent evaluation (advance simulated clock and check deadlines)
            if self.current_obligation.lifecycle_status not in TERMINAL_LIFECYCLE_STATUSES:
                clock_event = ClockTickEvent(
                    event_id=uuid.uuid4(),
                    actor_id="SYSTEM_CLOCK",
                    obligation_id=self.current_obligation.id,
                    timestamp=simulated_time,
                    current_simulated_time=simulated_time,
                )
                self.current_obligation, clock_audit = ObligationService.process_event(
                    self.session, self.current_obligation, clock_event
                )
                self.session.flush()

                if clock_audit is not None:
                    step_result.audit_logs_created.append(
                        {
                            "audit_seq": clock_audit.audit_seq,
                            "event_type": clock_audit.event_type.value,
                            "reason_code": clock_audit.reason_code,
                            "rationale": clock_audit.rationale_text,
                        }
                    )

            # 3. Snapshot state at end of day
            state_tuple = ObligationStateTuple.from_obligation(self.current_obligation)
            step_result.state_after_step = state_tuple
            step_result.headline_after_step = calculate_headline(self.current_obligation)
            step_result.should_flag_after_step = calculate_should_flag(self.current_obligation)

            review_items_count = len(
                self.session.execute(
                    select(AmbiguousReviewItem).where(
                        AmbiguousReviewItem.obligation_id == self.current_obligation.id
                    )
                )
                .scalars()
                .all()
            )
            step_result.review_items_count = review_items_count

            new_steps.append(step_result)
            self.step_history.append(step_result)
            self.current_day += 1

        return new_steps

    def run_case(self, case_id: str, max_day: int | None = None) -> ScenarioRunResult:
        """Execute a full scenario simulation from start to completion and verify results."""
        if case_id not in self.scenarios:
            raise KeyError(f"Case ID '{case_id}' not found in loaded synthetic scenarios.")

        scenario = self.scenarios[case_id]
        obligation = self.load_scenario(scenario)

        timeline_max = max((e.day for e in scenario.timeline_events), default=scenario.due_day)
        target_day = max_day if max_day is not None else timeline_max

        self.step_to_day(target_day)

        # Query all audit logs and review items
        audit_logs = (
            self.session.execute(
                select(ObligationAuditLog)
                .where(ObligationAuditLog.obligation_id == obligation.id)
                .order_by(ObligationAuditLog.audit_seq)
            )
            .scalars()
            .all()
        )

        review_items = (
            self.session.execute(
                select(AmbiguousReviewItem)
                .where(AmbiguousReviewItem.obligation_id == obligation.id)
                .order_by(AmbiguousReviewItem.created_at)
            )
            .scalars()
            .all()
        )

        final_state = ObligationStateTuple.from_obligation(obligation)
        final_headline = calculate_headline(obligation)
        should_flag = calculate_should_flag(obligation)

        # Validation against CSV ground truth
        validation_errors: list[str] = []

        if obligation.lifecycle_status != scenario.expected_lifecycle_status:
            validation_errors.append(
                f"lifecycle_status mismatch: expected {scenario.expected_lifecycle_status.value}, "
                f"got {obligation.lifecycle_status.value}"
            )
        if obligation.timeliness_status != scenario.expected_timeliness_status:
            validation_errors.append(
                f"timeliness_status mismatch: expected {scenario.expected_timeliness_status.value}, "
                f"got {obligation.timeliness_status.value}"
            )
        if obligation.evidence_review_status != scenario.expected_evidence_review_status:
            validation_errors.append(
                f"evidence_review_status mismatch: expected {scenario.expected_evidence_review_status.value}, "
                f"got {obligation.evidence_review_status.value}"
            )
        if obligation.ownership_status != scenario.expected_ownership_status:
            validation_errors.append(
                f"ownership_status mismatch: expected {scenario.expected_ownership_status.value}, "
                f"got {obligation.ownership_status.value}"
            )
        if final_headline != scenario.expected_headline:
            validation_errors.append(
                f"expected_headline mismatch: expected '{scenario.expected_headline}', "
                f"got '{final_headline}'"
            )
        if should_flag != scenario.should_flag:
            validation_errors.append(
                f"should_flag mismatch: expected {scenario.should_flag}, got {should_flag}"
            )

        # Review item expectation check
        if scenario.expected_review_item:
            if not review_items:
                validation_errors.append(
                    "Expected AmbiguousReviewItem to be created, but none found."
                )
            else:
                item = review_items[0]
                expected_status = scenario.expected_review_item.get("status")
                expected_owner = scenario.expected_review_item.get("owner")
                if expected_status and item.status.value != expected_status:
                    validation_errors.append(
                        f"AmbiguousReviewItem status mismatch: expected {expected_status}, got {item.status.value}"
                    )
                if expected_owner and item.assigned_reviewer_id != expected_owner:
                    validation_errors.append(
                        f"AmbiguousReviewItem owner mismatch: expected {expected_owner}, got {item.assigned_reviewer_id}"
                    )
        else:
            if review_items:
                validation_errors.append(f"Expected 0 review items, but found {len(review_items)}")

        # Verify audit ledger invariants
        if obligation.audit_seq != len(audit_logs):
            validation_errors.append(
                f"Audit sequence mismatch: obligation audit_seq={obligation.audit_seq} "
                f"but found {len(audit_logs)} audit records"
            )

        success = len(validation_errors) == 0

        return ScenarioRunResult(
            case_id=case_id,
            scenario=scenario,
            obligation=obligation,
            final_state=final_state,
            final_headline=final_headline,
            should_flag=should_flag,
            audit_logs=audit_logs,
            review_items=review_items,
            step_results=self.step_history,
            rejections=self.rejections,
            success=success,
            validation_errors=validation_errors,
        )

    def run_all(self) -> dict[str, ScenarioRunResult]:
        """Execute all loaded scenarios and return a mapping of case_id -> ScenarioRunResult."""
        results: dict[str, ScenarioRunResult] = {}
        for case_id in sorted(self.scenarios.keys()):
            results[case_id] = self.run_case(case_id)
        return results
