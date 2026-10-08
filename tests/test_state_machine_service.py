"""Integration tests for state machine execution coordinated via ObligationService and PostgreSQL audit triggers."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from cce.audit import InvalidStateTransitionError
from cce.enums import (
    AmbiguousItemStatus,
    AuditEventType,
    EvidenceReviewStatus,
    LifecycleStatus,
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
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)
from cce.models import AmbiguousReviewItem, ObligationAuditLog
from cce.service import ObligationService


def test_full_clinical_obligation_lifecycle(db_session):
    """Test full sequential lifecycle: DRAFT -> ACTIVE -> DUE -> ACTION_EVIDENCE -> VERIFIED_COMPLETE."""
    now = datetime.now(UTC)
    w_start = now + timedelta(days=7)
    w_end = now + timedelta(days=14)

    # 1. Ingestion: DRAFT (audit_seq = 1)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-STAGE-1",
        source_evidence={"discharge_summary_id": "DISCH-902"},
        required_action_code="REPEAT_CREATININE",
        required_action_description="Repeat serum creatinine within 7-14 days post-discharge",
        due_window_start=w_start,
        due_window_end=w_end,
        actor_id="INGESTION_AGENT",
        lifecycle_status=LifecycleStatus.DRAFT,
        timeliness_status=TimelinessStatus.NOT_DUE,
    )
    db_session.flush()
    assert ob.audit_seq == 1
    assert ob.lifecycle_status == LifecycleStatus.DRAFT

    # 2. Human Confirmation: DRAFT -> ACTIVE (audit_seq = 2)
    confirm_event = HumanConfirmEvent(
        actor_id="dr_nephro",
        obligation_id=ob.id,
        rationale_text="Confirmed repeat renal panel required post acute tubular necrosis",
    )
    ob, audit2 = ObligationService.process_event(db_session, ob, confirm_event)
    db_session.flush()

    assert ob.audit_seq == 2
    assert ob.lifecycle_status == LifecycleStatus.ACTIVE
    assert audit2 is not None
    assert audit2.event_type == AuditEventType.CONFIRMATION
    assert audit2.actor_id == "dr_nephro"
    assert audit2.new_state["lifecycle_status"] == "ACTIVE"

    # 3. Clock Tick: NOT_DUE -> DUE (audit_seq = 3)
    tick_due = ClockTickEvent(
        obligation_id=ob.id,
        current_simulated_time=now + timedelta(days=8),
    )
    ob, audit3 = ObligationService.process_event(db_session, ob, tick_due)
    db_session.flush()

    assert ob.audit_seq == 3
    assert ob.timeliness_status == TimelinessStatus.DUE
    assert audit3 is not None
    assert audit3.event_type == AuditEventType.STATE_CHANGE

    # 3b. Clock Tick without state change (no audit entry, no sequence bump)
    tick_same = ClockTickEvent(
        obligation_id=ob.id,
        current_simulated_time=now + timedelta(days=9),
    )
    ob, audit_none = ObligationService.process_event(db_session, ob, tick_same)
    db_session.flush()
    assert audit_none is None
    assert ob.audit_seq == 3

    # 4. Diagnostic Report Lands: ACTIVE, ACTION_EVIDENCE_RECEIVED (audit_seq = 4)
    report_event = DiagnosticReportReceivedEvent(
        actor_id="PATHOLOGY_SYSTEM",
        obligation_id=ob.id,
        report_id="LAB-RESULT-5541",
        action_code="REPEAT_CREATININE",
        report_payload={"creatinine_value": 98, "units": "umol/L"},
    )
    ob, audit4 = ObligationService.process_event(db_session, ob, report_event)
    db_session.flush()

    assert ob.audit_seq == 4
    # False closure prevention: remains ACTIVE
    assert ob.lifecycle_status == LifecycleStatus.ACTIVE
    assert ob.evidence_review_status == EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED
    assert audit4 is not None
    assert audit4.reason_code == "DIAGNOSTIC_REPORT_RECEIVED"

    # 5. Clinician Documents Review: ACTIVE -> COMPLETE (audit_seq = 5)
    review_event = ClinicalReviewDocumentedEvent(
        actor_id="dr_registrar",
        obligation_id=ob.id,
        review_note_id="EHR-CONSULT-8889",
        attribution="Dr. S. Miller (Registrar)",
        review_notes="Creatinine returned to baseline. No further surveillance needed.",
    )
    ob, audit5 = ObligationService.process_event(db_session, ob, review_event)
    db_session.flush()

    assert ob.audit_seq == 5
    assert ob.lifecycle_status == LifecycleStatus.COMPLETE
    assert ob.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE
    assert ob.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    assert audit5 is not None
    assert audit5.reason_code == "CLINICAL_REVIEW_VERIFIED"

    # Verify all 5 audit logs exist and are ordered
    logs = (
        db_session.execute(
            select(ObligationAuditLog)
            .where(ObligationAuditLog.obligation_id == ob.id)
            .order_by(ObligationAuditLog.audit_seq)
        )
        .scalars()
        .all()
    )

    assert len(logs) == 5
    assert [log.audit_seq for log in logs] == [1, 2, 3, 4, 5]


def test_ambiguous_evidence_creates_review_item_in_db(db_session):
    """Test that AmbiguousEvidenceFlaggedEvent creates an AmbiguousReviewItem in DB."""
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-AMBIG-1",
        source_evidence={"order": "renal"},
        required_action_code="URINE_ACR",
        required_action_description="Urine ACR 3-month follow-up",
        due_window_end=datetime.now(UTC) + timedelta(days=30),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    db_session.flush()

    ambig_event = AmbiguousEvidenceFlaggedEvent(
        actor_id="NLP_MATCHER",
        obligation_id=ob.id,
        evidence_snippet={"raw": "ACR tested at GP clinic 2 weeks ago"},
        confidence_score=0.52,
        assigned_reviewer_id="gp_liaison_nurse",
        due_at=datetime.now(UTC) + timedelta(days=2),
    )

    ob, audit = ObligationService.process_event(db_session, ob, ambig_event)
    db_session.flush()

    assert ob.audit_seq == 2
    assert ob.evidence_review_status == EvidenceReviewStatus.AMBIGUOUS_REVIEW_EVIDENCE

    # Query AmbiguousReviewItem table
    items = (
        db_session.execute(
            select(AmbiguousReviewItem).where(AmbiguousReviewItem.obligation_id == ob.id)
        )
        .scalars()
        .all()
    )

    assert len(items) == 1
    item = items[0]
    assert item.status == AmbiguousItemStatus.OPEN
    assert item.assigned_reviewer_id == "gp_liaison_nurse"
    assert item.proposed_evidence_snippet["raw"] == "ACR tested at GP clinic 2 weeks ago"


def test_manual_override_service_integration(db_session):
    """Test that ManualOverrideEvent transitions obligation to COMPLETE despite missing evidence."""
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-OVERRIDE-1",
        source_evidence={"cardiology_letter": "EKG_REPEAT"},
        required_action_code="REPEAT_ECG",
        required_action_description="Repeat 12-lead ECG",
        due_window_end=datetime.now(UTC) + timedelta(days=10),
        lifecycle_status=LifecycleStatus.ACTIVE,
        timeliness_status=TimelinessStatus.DUE,
    )
    db_session.flush()

    override_event = ManualOverrideEvent(
        actor_id="dr_chief",
        obligation_id=ob.id,
        reason_code="MANUAL_CLINIC_VERIFICATION",
        rationale_text="ECG performed during bedside review; normal sinus rhythm confirmed",
    )

    ob, audit = ObligationService.process_event(db_session, ob, override_event)
    db_session.flush()

    assert ob.audit_seq == 2
    assert ob.lifecycle_status == LifecycleStatus.COMPLETE
    assert ob.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    # Preserves evidence status as NO_EVIDENCE for safety auditability
    assert ob.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE
    assert audit is not None
    assert audit.event_type == AuditEventType.MANUAL_OVERRIDE


def test_supersede_and_cancel_service_integration(db_session):
    """Test SupersedePlanEvent and CancelObligationEvent via ObligationService."""
    now = datetime.now(UTC)

    # 1. Supersede
    ob1 = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-SUPERSEDE-1",
        source_evidence={"note": "DOAC"},
        required_action_code="INR_MONITORING",
        required_action_description="Weekly INR test",
        due_window_end=now + timedelta(days=7),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    db_session.flush()

    successor = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-SUPERSEDE-1",
        source_evidence={"note": "DOAC"},
        required_action_code="DOAC_RENAL_MONITORING",
        required_action_description="6-month renal profile for DOAC",
        due_window_end=now + timedelta(days=180),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    db_session.flush()

    supersede_event = SupersedePlanEvent(
        actor_id="dr_cardio",
        obligation_id=ob1.id,
        superseded_by_id=successor.id,
        reason_code="ANTICOAGULANT_SWITCH",
        rationale_text="Switched from Warfarin to Apixaban",
    )

    ob1, audit_sup = ObligationService.process_event(db_session, ob1, supersede_event)
    db_session.flush()

    assert ob1.lifecycle_status == LifecycleStatus.SUPERSEDED
    assert ob1.superseded_by_id == successor.id
    assert audit_sup is not None
    assert audit_sup.event_type == AuditEventType.SUPERSEDED

    # 2. Cancel
    ob2 = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-CANCEL-1",
        source_evidence={"note": "Error"},
        required_action_code="REPEAT_XRAY",
        required_action_description="Repeat Chest X-ray",
        due_window_end=now + timedelta(days=14),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    db_session.flush()

    cancel_event = CancelObligationEvent(
        actor_id="dr_radiology",
        obligation_id=ob2.id,
        reason_code="DUPLICATE_ORDER",
        rationale_text="CT Thorax already ordered which supersedes plain radiography",
    )

    ob2, audit_can = ObligationService.process_event(db_session, ob2, cancel_event)
    db_session.flush()

    assert ob2.lifecycle_status == LifecycleStatus.CANCELLED
    assert audit_can is not None
    assert audit_can.event_type == AuditEventType.CANCELLATION


def test_assign_ownership_service_integration(db_session):
    """Test AssignOwnershipEvent via ObligationService."""
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-OWN-1",
        source_evidence={"ward": "unallocated"},
        required_action_code="ECHO_SURVEILLANCE",
        required_action_description="Transthoracic echocardiogram in 6 weeks",
        due_window_end=datetime.now(UTC) + timedelta(days=42),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    db_session.flush()

    assign_event = AssignOwnershipEvent(
        actor_id="ward_manager",
        obligation_id=ob.id,
        assigned_team="Cardiology Team B",
        assigned_user_id="consultant_heart",
    )

    ob, audit = ObligationService.process_event(db_session, ob, assign_event)
    db_session.flush()

    assert ob.ownership_status == OwnershipStatus.OWNED
    assert ob.assigned_team == "Cardiology Team B"
    assert ob.assigned_user_id == "consultant_heart"
    assert audit is not None
    assert audit.event_type == AuditEventType.OWNERSHIP_ASSIGNED


def test_action_code_mismatch_raises_error_and_preserves_state(db_session):
    """Test that a guard failure in process_event leaves obligation state untouched."""
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-MISMATCH-1",
        source_evidence={"note": "blood test"},
        required_action_code="LIPID_PANEL",
        required_action_description="Fasting lipid profile",
        due_window_end=datetime.now(UTC) + timedelta(days=14),
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    db_session.flush()

    mismatch_event = DiagnosticReportReceivedEvent(
        actor_id="LAB_ROBOT",
        obligation_id=ob.id,
        report_id="LAB-9999",
        action_code="GLUCOSE_TOLERANCE",
    )

    with pytest.raises(InvalidStateTransitionError, match="Action code mismatch"):
        ObligationService.process_event(db_session, ob, mismatch_event)

    # Ensure state in session was not modified by the failed transition
    assert ob.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE
    assert ob.audit_seq == 1
