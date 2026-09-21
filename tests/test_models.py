from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cce.enums import (
    AmbiguousItemStatus,
    AuditEventType,
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.models import AmbiguousReviewItem, Obligation, ObligationAuditLog
from cce.service import ObligationService


def test_insert_complete_obligation_with_four_dimensions(db_session):
    """Validate inserting a complete obligation with all 4 independent dimensions."""
    due_start = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    due_end = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)

    obligation = ObligationService.create_obligation(
        session=db_session,
        patient_id="NHS-9876543210",
        source_evidence={
            "document_id": "DOC-DISCH-001",
            "document_type": "Discharge Summary",
            "snippet": "Repeat U&E in 7 days to assess renal recovery post-AKI.",
            "extracted_at": "2026-10-01T08:30:00Z",
        },
        required_action_code="U_AND_E",
        required_action_description="Check repeat urea and electrolytes",
        due_window_start=due_start,
        due_window_end=due_end,
        actor_id="DR_SMITH_GMC12345",
        assigned_team="Renal Surveillance Team",
        assigned_user_id="USER-7788",
        lifecycle_status=LifecycleStatus.ACTIVE,
        timeliness_status=TimelinessStatus.NOT_DUE,
        evidence_review_status=EvidenceReviewStatus.NO_EVIDENCE,
    )

    db_session.flush()

    # Query back
    stmt = select(Obligation).where(Obligation.id == obligation.id)
    saved = db_session.scalar(stmt)

    assert saved is not None
    assert saved.patient_id == "NHS-9876543210"
    assert saved.required_action_code == "U_AND_E"
    assert saved.lifecycle_status == LifecycleStatus.ACTIVE
    assert saved.timeliness_status == TimelinessStatus.NOT_DUE
    assert saved.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE
    assert saved.ownership_status == OwnershipStatus.OWNED
    assert saved.assigned_team == "Renal Surveillance Team"
    assert saved.assigned_user_id == "USER-7788"
    assert saved.audit_seq == 1

    # Check that creation audit log was correctly paired
    assert len(saved.audit_logs) == 1
    creation_audit = saved.audit_logs[0]
    assert creation_audit.event_type == AuditEventType.CREATION
    assert creation_audit.actor_id == "DR_SMITH_GMC12345"
    assert creation_audit.audit_seq == 1
    assert creation_audit.previous_state is None
    assert creation_audit.new_state["lifecycle_status"] == "ACTIVE"
    assert creation_audit.new_state["ownership_status"] == "OWNED"


def test_relaxed_ownership_constraint_in_models(db_session):
    """Validate NHS clinical reality: NO_OWNER can retain assigned_team context (e.g. Ward 4B)."""
    due_end = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)

    # Allowed: NO_OWNER with assigned_team (unallocated within ward)
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="NHS-11223344",
        source_evidence={"doc": "Discharge Note"},
        required_action_code="LFT",
        required_action_description="Liver function check",
        due_window_end=due_end,
        assigned_team="Acute Medical Unit",
        assigned_user_id=None,
    )
    # Manually assert unallocated ownership status
    ob.ownership_status = OwnershipStatus.NO_OWNER
    # Keep audit log in sync with snapshot
    ob.audit_logs[0].new_state = ob.get_dimensions_snapshot()

    db_session.flush()
    assert ob.ownership_status == OwnershipStatus.NO_OWNER
    assert ob.assigned_team == "Acute Medical Unit"


def test_invalid_ownership_raises_integrity_error(db_session):
    """Validate that OWNED without assigned_team or assigned_user_id violates chk_obligation_ownership."""
    due_end = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    ob_id = uuid.uuid4()

    invalid_ob = Obligation(
        id=ob_id,
        patient_id="NHS-11223344",
        source_evidence={"doc": "Clinic Letter"},
        required_action_code="CXR",
        required_action_description="Chest X-Ray follow-up",
        due_window_end=due_end,
        lifecycle_status=LifecycleStatus.ACTIVE,
        timeliness_status=TimelinessStatus.NOT_DUE,
        evidence_review_status=EvidenceReviewStatus.NO_EVIDENCE,
        ownership_status=OwnershipStatus.OWNED,  # OWNED but both team & user are None!
        assigned_team=None,
        assigned_user_id=None,
        audit_seq=1,
    )
    audit = ObligationAuditLog(
        obligation_id=ob_id,
        audit_seq=1,
        event_type=AuditEventType.CREATION,
        actor_id="SYSTEM",
        new_state=invalid_ob.get_dimensions_snapshot(),
        reason_code="INITIAL_EXTRACTION",
    )
    db_session.add(invalid_ob)
    db_session.add(audit)

    with pytest.raises(IntegrityError) as excinfo:
        db_session.flush()

    assert "chk_obligation_ownership" in str(excinfo.value)


def test_ambiguous_review_items_association(db_session):
    """Validate creating ambiguous review items linked to an obligation."""
    due_end = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    obligation = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-AMBIGUOUS-01",
        source_evidence={"doc": "Referral Letter"},
        required_action_code="CT_CHEST",
        required_action_description="Follow-up CT chest in 3 months",
        due_window_end=due_end,
    )
    db_session.flush()

    # Add ambiguous review item
    review_item = AmbiguousReviewItem(
        obligation_id=obligation.id,
        proposed_evidence_snippet={
            "report_id": "RAD-2026-999",
            "modality": "CT Thorax / Abdomen",
            "snippet": "CT chest, abdomen and pelvis performed for staging...",
            "match_confidence": 0.65,
        },
        assigned_reviewer_id="RAD_REVIEWER_01",
        due_at=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc),
        status=AmbiguousItemStatus.OPEN,
    )
    db_session.add(review_item)
    db_session.flush()

    # Query
    assert len(obligation.ambiguous_review_items) == 1
    assert obligation.ambiguous_review_items[0].status == AmbiguousItemStatus.OPEN
    assert obligation.ambiguous_review_items[0].assigned_reviewer_id == "RAD_REVIEWER_01"

