"""Unit tests for strongly typed domain events (Pydantic V2)."""

import uuid
import zoneinfo
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cce.events import (
    AmbiguousEvidenceFlaggedEvent,
    AssignOwnershipEvent,
    CancelObligationEvent,
    ClinicalReviewDocumentedEvent,
    ClockTickEvent,
    DiagnosticReportReceivedEvent,
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)


def test_base_event_mandatory_fields():
    ob_id = uuid.uuid4()
    now = datetime.now(UTC)

    event = HumanConfirmEvent(
        actor_id="dr_smith",
        obligation_id=ob_id,
        timestamp=now,
    )

    assert isinstance(event.event_id, uuid.UUID)
    assert event.actor_id == "dr_smith"
    assert event.obligation_id == ob_id
    assert event.timestamp == now
    assert event.event_type == "HumanConfirmEvent"


def test_event_rejects_naive_timestamp():
    ob_id = uuid.uuid4()
    naive_dt = datetime(2026, 10, 8, 12, 0, 0)  # No tzinfo

    with pytest.raises(ValidationError, match="timezone-aware"):
        HumanConfirmEvent(
            actor_id="dr_smith",
            obligation_id=ob_id,
            timestamp=naive_dt,
        )


def test_event_accepts_different_timezones():
    ob_id = uuid.uuid4()
    bst_tz = zoneinfo.ZoneInfo("Europe/London")
    dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=bst_tz)

    event = HumanConfirmEvent(
        actor_id="dr_smith",
        obligation_id=ob_id,
        timestamp=dt,
    )
    assert event.timestamp.tzinfo is not None


def test_event_immutability_and_extra_fields():
    ob_id = uuid.uuid4()
    event = HumanConfirmEvent(actor_id="dr_smith", obligation_id=ob_id)

    with pytest.raises(ValidationError):
        # Extra field forbidden
        HumanConfirmEvent(actor_id="dr_smith", obligation_id=ob_id, invalid_field=123)  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        # Frozen model mutation forbidden
        event.actor_id = "dr_jones"  # type: ignore[misc]


def test_clock_tick_event_validation():
    ob_id = uuid.uuid4()
    sim_time = datetime.now(UTC)

    event = ClockTickEvent(
        obligation_id=ob_id,
        current_simulated_time=sim_time,
    )
    assert event.actor_id == "SYSTEM_CLOCK"
    assert event.current_simulated_time == sim_time

    # Reject naive simulated time
    naive_sim = datetime(2026, 10, 8, 14, 0, 0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        ClockTickEvent(
            obligation_id=ob_id,
            current_simulated_time=naive_sim,
        )


def test_diagnostic_report_received_event():
    ob_id = uuid.uuid4()
    event = DiagnosticReportReceivedEvent(
        actor_id="LAB_SYS",
        obligation_id=ob_id,
        report_id="REP-9982",
        action_code="UREA_CREATININE_SERUM",
        report_payload={"creatinine_umol_l": 115, "egfr": 58},
    )
    assert event.report_id == "REP-9982"
    assert event.action_code == "UREA_CREATININE_SERUM"
    assert event.report_payload["creatinine_umol_l"] == 115

    # Missing report_id or action_code must fail
    with pytest.raises(ValidationError):
        DiagnosticReportReceivedEvent(
            actor_id="LAB_SYS",
            obligation_id=ob_id,
            report_id="",
            action_code="UREA_CREATININE_SERUM",
        )


def test_clinical_review_documented_event_attribution():
    ob_id = uuid.uuid4()

    # When attribution omitted, defaults to actor_id
    event1 = ClinicalReviewDocumentedEvent(
        actor_id="consultant_123",
        obligation_id=ob_id,
        review_note_id="NOTE-4001",
    )
    assert event1.attribution == "consultant_123"

    # When explicit attribution provided
    event2 = ClinicalReviewDocumentedEvent(
        actor_id="registrar_55",
        obligation_id=ob_id,
        review_note_id="NOTE-4002",
        attribution="Dr. A. Jones (Consultant Nephrologist)",
        reviewer_id="consultant_99",
    )
    assert event2.attribution == "Dr. A. Jones (Consultant Nephrologist)"
    assert event2.reviewer_id == "consultant_99"


def test_ambiguous_evidence_flagged_event():
    ob_id = uuid.uuid4()
    event = AmbiguousEvidenceFlaggedEvent(
        actor_id="NLP_EXTRACTION_ENGINE",
        obligation_id=ob_id,
        evidence_snippet={"raw_text": "Serum creatinine collected at home", "date": "2026-10-01"},
        confidence_score=0.45,
        ambiguity_rationale="Specimen collection setting outside verified hospital lab pipeline",
    )
    assert event.confidence_score == 0.45
    assert event.reason_code == "AMBIGUOUS_EVIDENCE_MATCH"

    # Confidence score out of [0, 1] range must fail
    with pytest.raises(ValidationError):
        AmbiguousEvidenceFlaggedEvent(
            actor_id="NLP_EXTRACTION_ENGINE",
            obligation_id=ob_id,
            confidence_score=1.5,
        )


def test_supersede_plan_event_validation():
    ob_id = uuid.uuid4()
    replacement_id = uuid.uuid4()

    # Valid with replacement ID
    event1 = SupersedePlanEvent(
        actor_id="dr_cardio",
        obligation_id=ob_id,
        superseded_by_id=replacement_id,
        reason_code="MEDICATION_CLASS_SWITCH",
        rationale_text="Switched from Warfarin monitoring to DOAC regimen",
    )
    assert event1.superseded_by_id == replacement_id

    # Valid with migration flag
    event2 = SupersedePlanEvent(
        actor_id="dr_cardio",
        obligation_id=ob_id,
        migration_flag="PATIENT_TRANSFERRED_TERTIARY_CENTER",
        reason_code="EXTERNAL_TRANSFER",
        rationale_text="Care pathway transferred to Royal Brompton",
    )
    assert event2.migration_flag == "PATIENT_TRANSFERRED_TERTIARY_CENTER"

    # Fails if neither replacement ID nor migration flag provided
    with pytest.raises(ValidationError, match="either superseded_by_id or migration_flag"):
        SupersedePlanEvent(
            actor_id="dr_cardio",
            obligation_id=ob_id,
            reason_code="EXTERNAL_TRANSFER",
            rationale_text="Missing successor rationale",
        )


def test_cancel_obligation_event_validation():
    ob_id = uuid.uuid4()

    event = CancelObligationEvent(
        actor_id="admin_user",
        obligation_id=ob_id,
        reason_code="DUPLICATE_ORDER",
        rationale_text="Erroneously duplicated during morning ward round entry",
    )
    assert event.reason_code == "DUPLICATE_ORDER"

    # Empty reason or rationale must fail
    with pytest.raises(ValidationError):
        CancelObligationEvent(
            actor_id="admin_user",
            obligation_id=ob_id,
            reason_code="",
            rationale_text="Some text",
        )


def test_manual_override_event_validation():
    ob_id = uuid.uuid4()

    event = ManualOverrideEvent(
        actor_id="dr_senior_consultant",
        obligation_id=ob_id,
        reason_code="VERIFIED_EXTERNAL_EHR",
        rationale_text="Personally inspected renal profile completed in private facility",
    )
    assert event.actor_id == "dr_senior_consultant"
    assert event.reason_code == "VERIFIED_EXTERNAL_EHR"

    # Missing mandatory actor or rationale must fail
    with pytest.raises(ValidationError):
        ManualOverrideEvent(
            actor_id="",
            obligation_id=ob_id,
            reason_code="VERIFIED_EXTERNAL_EHR",
            rationale_text="Rationale",
        )


def test_assign_ownership_event():
    ob_id = uuid.uuid4()

    event = AssignOwnershipEvent(
        actor_id="ward_clerk",
        obligation_id=ob_id,
        assigned_team="Ward 3 Renal Team",
        assigned_user_id="consultant_77",
    )
    assert event.assigned_team == "Ward 3 Renal Team"
    assert event.assigned_user_id == "consultant_77"
