from datetime import datetime, timezone

from cce.audit import build_audit_log
from cce.enums import (
    AuditEventType,
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.models import Obligation
from cce.service import ObligationService


def test_update_dimensions_service(db_session):
    """Verify ObligationService.update_dimensions updates fields and logs an audit record."""
    due_end = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-SERVICE-01",
        source_evidence={"doc": "Discharge"},
        required_action_code="LIPID_PANEL",
        required_action_description="Fast lipid profile",
        due_window_end=due_end,
    )
    db_session.flush()

    audit = ObligationService.update_dimensions(
        session=db_session,
        obligation=ob,
        actor_id="DR_BIOCHEM_01",
        reason_code="RESULTS_RECEIVED",
        timeliness_status=TimelinessStatus.DUE,
        evidence_review_status=EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED,
        rationale_text="Lab report flagged as received in LIMS",
    )
    db_session.flush()

    assert ob.timeliness_status == TimelinessStatus.DUE
    assert ob.evidence_review_status == EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED
    assert ob.audit_seq == 2
    assert audit.audit_seq == 2
    assert audit.event_type == AuditEventType.STATE_CHANGE
    assert audit.previous_state["evidence_review_status"] == "NO_EVIDENCE"
    assert audit.new_state["evidence_review_status"] == "ACTION_EVIDENCE_RECEIVED"


def test_assign_owner_service(db_session):
    """Verify ObligationService.assign_owner allocates clinician ownership and creates audit."""
    due_end = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-SERVICE-02",
        source_evidence={"doc": "Discharge"},
        required_action_code="ECHOCARDIOGRAM",
        required_action_description="Follow-up echo",
        due_window_end=due_end,
    )
    db_session.flush()

    audit = ObligationService.assign_owner(
        session=db_session,
        obligation=ob,
        actor_id="WARD_MANAGER_10",
        assigned_team="Cardiology SpR On-Call",
        assigned_user_id="GMC-654321",
        rationale_text="Allocated to duty cardiology registrar",
    )
    db_session.flush()

    assert ob.ownership_status == OwnershipStatus.OWNED
    assert ob.assigned_team == "Cardiology SpR On-Call"
    assert ob.assigned_user_id == "GMC-654321"
    assert audit.event_type == AuditEventType.OWNERSHIP_ASSIGNED
    assert audit.reason_code == "OWNERSHIP_ALLOCATION"


def test_build_audit_log_helper(db_session):
    """Verify build_audit_log helper produces a valid ObligationAuditLog instance."""
    due_end = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-SERVICE-03",
        source_evidence={"doc": "Note"},
        required_action_code="LFT",
        required_action_description="Liver panel",
        due_window_end=due_end,
    )
    db_session.flush()

    log_entry = build_audit_log(
        obligation=ob,
        event_type=AuditEventType.CONFIRMATION,
        actor_id="SENIOR_CONSULTANT",
        reason_code="PLAN_REVIEWED",
        rationale_text="Consultant ward round review confirmed plan",
    )
    assert log_entry.obligation_id == ob.id
    assert log_entry.audit_seq == ob.audit_seq
    assert log_entry.event_type == AuditEventType.CONFIRMATION
    assert log_entry.new_state["lifecycle_status"] == "DRAFT"

