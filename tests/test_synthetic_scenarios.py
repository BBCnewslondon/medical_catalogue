"""End-to-End Test Suite for CCE Synthetic Benchmarks & Time Machine Simulator.

Validates that all 10 clinical synthetic scenarios from 'SYNTHETIC CASES V1.csv'
execute deterministically against a real PostgreSQL test database, strictly enforcing
4-dimensional state transitions, audit ledger invariants, review items, and anti-gaming guards.
"""

from pathlib import Path

import pytest
from sqlalchemy import select

from cce.enums import (
    AmbiguousItemStatus,
    AuditEventType,
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.models import Obligation, ObligationAuditLog
from cce.simulator.parser import ScenarioParser
from cce.simulator.runner import ScenarioRunner

CSV_PATH = Path(__file__).resolve().parent.parent / "SYNTHETIC CASES V1.csv"

ALL_CASE_IDS = [
    "CCE-001",
    "CCE-002",
    "CCE-003",
    "CCE-004",
    "CCE-005",
    "CCE-006",
    "CCE-007",
    "CCE-008",
    "CCE-009",
    "CCE-010",
]


def test_parser_csv_structure():
    """Verify that ScenarioParser parses all 10 cases without errors and extracts valid ground truth."""
    scenarios = ScenarioParser.parse_file(CSV_PATH)
    assert len(scenarios) == 10

    case_ids = [s.case_id for s in scenarios]
    assert case_ids == ALL_CASE_IDS

    for sc in scenarios:
        assert sc.title
        assert sc.benchmark_role
        assert sc.age > 0
        assert sc.sex in ("M", "F")
        assert sc.setting
        assert sc.source_note
        assert sc.action
        assert sc.action_code
        assert sc.due_day >= sc.created_day
        assert len(sc.timeline_events) > 0
        assert isinstance(sc.expected_lifecycle_status, LifecycleStatus)
        assert isinstance(sc.expected_timeliness_status, TimelinessStatus)
        assert isinstance(sc.expected_evidence_review_status, EvidenceReviewStatus)
        assert isinstance(sc.expected_ownership_status, OwnershipStatus)


@pytest.mark.parametrize("case_id", ALL_CASE_IDS)
def test_synthetic_scenario_end_to_end(db_session, case_id: str):
    """Execute scenario end-to-end and assert all 4 dimensions, headline, audit logs, and review items."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    result = runner.run_case(case_id)

    # 1. Verification assertions
    assert result.success is True, f"Validation errors for {case_id}: {result.validation_errors}"
    scenario = result.scenario
    obligation = result.obligation

    # 2. Assert 4-Dimension State
    assert obligation.lifecycle_status == scenario.expected_lifecycle_status
    assert obligation.timeliness_status == scenario.expected_timeliness_status
    assert obligation.evidence_review_status == scenario.expected_evidence_review_status
    assert obligation.ownership_status == scenario.expected_ownership_status

    # 3. Assert Headline and Safety Risk Flag
    assert result.final_headline == scenario.expected_headline
    assert result.should_flag == scenario.should_flag

    # 4. Assert Review Item Generation when specified
    if scenario.expected_review_item:
        assert len(result.review_items) == 1
        item = result.review_items[0]
        assert item.status.value == scenario.expected_review_item["status"]
        assert item.assigned_reviewer_id == scenario.expected_review_item["owner"]
    else:
        assert len(result.review_items) == 0

    # 5. Assert Append-Only Audit Ledger Invariants
    assert len(result.audit_logs) == obligation.audit_seq
    assert result.audit_logs[0].event_type == AuditEventType.CREATION
    assert result.audit_logs[0].audit_seq == 1

    # Verify strictly monotonic audit sequences
    expected_seqs = list(range(1, obligation.audit_seq + 1))
    actual_seqs = [log.audit_seq for log in result.audit_logs]
    assert actual_seqs == expected_seqs


def test_scenario_step_to_day_incremental(db_session):
    """Verify that step_to_day allows incremental day-by-day stepping and inspects intermediate states."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    ob = runner.load_scenario("CCE-001")

    # Initial state on Day 0 before events: DRAFT
    assert ob.lifecycle_status == LifecycleStatus.DRAFT
    assert ob.audit_seq == 1

    # Step to Day 0: OBLIGATION_CONFIRMED occurs
    steps_day0 = runner.step_to_day(0)
    assert len(steps_day0) == 1
    assert ob.lifecycle_status == LifecycleStatus.ACTIVE
    assert ob.audit_seq == 2

    # Step to Day 5: Mid-window, no events, clock ticks keep it NOT_DUE
    steps_day5 = runner.step_to_day(5)
    assert len(steps_day5) == 5  # Days 1, 2, 3, 4, 5
    assert ob.lifecycle_status == LifecycleStatus.ACTIVE
    assert ob.timeliness_status == TimelinessStatus.NOT_DUE
    assert ob.audit_seq == 2  # No audit seq bump when state is unchanged

    # Step to Day 9: TEST_PERFORMED and RESULT_AVAILABLE
    steps_day9 = runner.step_to_day(9)
    assert len(steps_day9) == 4  # Days 6, 7, 8, 9
    assert ob.evidence_review_status == EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED
    assert ob.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    # Seq 3: DiagnosticReportReceivedEvent, Seq 4: ClockTick evaluated timeliness to NOT_APPLICABLE
    assert ob.audit_seq == 4

    # Step to Day 10: REVIEW_NOTE verified
    steps_day10 = runner.step_to_day(10)
    assert len(steps_day10) == 1
    assert ob.lifecycle_status == LifecycleStatus.COMPLETE
    assert ob.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE
    assert ob.audit_seq == 5


def test_cce_010_anti_gaming_rejected(db_session):
    """Verify CCE-010: user attempt to force COMPLETE without rationale is rejected and state preserved."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    result = runner.run_case("CCE-010")

    assert result.success is True
    # Rejection was caught and logged
    assert len(result.rejections) == 1
    rej = result.rejections[0]
    assert rej["day"] == 8
    assert rej["event_token"] == "MANUAL_COMPLETE_ATTEMPT"
    assert "Manual override requires mandatory" in rej["error"]

    # Obligation remained protected in ACTIVE, OVERDUE, NO_EVIDENCE
    assert result.obligation.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.obligation.timeliness_status == TimelinessStatus.OVERDUE
    assert result.obligation.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE

    # Ensure no manual override audit log exists in DB
    override_logs = (
        db_session.execute(
            select(ObligationAuditLog).where(
                ObligationAuditLog.obligation_id == result.obligation.id,
                ObligationAuditLog.event_type == AuditEventType.MANUAL_OVERRIDE,
            )
        )
        .scalars()
        .all()
    )
    assert len(override_logs) == 0


def test_cce_009_supersession_linking(db_session):
    """Verify CCE-009: original obligation is SUPERSEDED and linked to successor obligation."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    result = runner.run_case("CCE-009")

    assert result.success is True
    ob = result.obligation
    assert ob.lifecycle_status == LifecycleStatus.SUPERSEDED
    assert ob.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    assert ob.superseded_by_id is not None

    # Verify replacement obligation exists in DB
    replacement = db_session.get(Obligation, ob.superseded_by_id)
    assert replacement is not None
    assert replacement.lifecycle_status == LifecycleStatus.ACTIVE
    assert replacement.patient_id == ob.patient_id


def test_cce_005_ownership_alert_independent_of_timeliness(db_session):
    """Verify CCE-005: NO_OWNER surfaces an immediate safety alert even when deadline is NOT_DUE."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    result = runner.run_case("CCE-005")

    assert result.success is True
    assert result.obligation.ownership_status == OwnershipStatus.NO_OWNER
    assert result.obligation.timeliness_status == TimelinessStatus.NOT_DUE
    assert result.final_headline == "NO_OWNER"
    assert result.should_flag is True


def test_cce_003_and_004_review_queue_distinction(db_session):
    """Verify review queue distinction: CCE-003 creates OVERDUE review item; CCE-004 creates OPEN review item."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)

    # 1. CCE-003: Missing review evidence past deadline -> OVERDUE
    res_003 = runner.run_case("CCE-003")
    assert res_003.success is True
    items_003 = res_003.review_items
    assert len(items_003) == 1
    assert items_003[0].status == AmbiguousItemStatus.OVERDUE
    assert items_003[0].assigned_reviewer_id == "Rheumatology team"

    # Clean session for CCE-004
    db_session.rollback()
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)

    # 2. CCE-004: Ambiguous free-text note -> OPEN confirmation item
    res_004 = runner.run_case("CCE-004")
    assert res_004.success is True
    items_004 = res_004.review_items
    assert len(items_004) == 1
    assert items_004[0].status == AmbiguousItemStatus.OPEN
    assert items_004[0].assigned_reviewer_id == "Rheumatology team"


def test_cce_006_appointment_cancellation_does_not_close_obligation(db_session):
    """Verify CCE-006: Cancelled booking does not close underlying clinical obligation."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    result = runner.run_case("CCE-006")

    assert result.success is True
    assert result.obligation.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.obligation.timeliness_status == TimelinessStatus.OVERDUE
    assert result.obligation.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE


def test_cce_007_radiology_report_read_receipt_does_not_close_obligation(db_session):
    """Verify CCE-007: Read receipt on radiology report does not count as follow-up action completion."""
    runner = ScenarioRunner(session=db_session, csv_path=CSV_PATH)
    result = runner.run_case("CCE-007")

    assert result.success is True
    assert result.obligation.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.obligation.timeliness_status == TimelinessStatus.OVERDUE
    assert result.obligation.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE
