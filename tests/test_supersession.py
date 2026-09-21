from datetime import UTC, datetime

from sqlalchemy import select

from cce.enums import AuditEventType, LifecycleStatus
from cce.models import Obligation
from cce.service import ObligationService


def test_supersede_with_replacement_obligation(db_session):
    """Verify superseding an obligation by linking to a replacement obligation."""
    due_end_1 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    due_end_2 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

    # 1. Original obligation: daily INR monitoring for Warfarin
    original_ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-WARFARIN-01",
        source_evidence={"doc": "Clinic Review", "snippet": "Monitor INR weekly on Warfarin"},
        required_action_code="INR_MONITOR",
        required_action_description="Weekly INR test for Warfarin dosing",
        due_window_end=due_end_1,
        assigned_team="Anticoagulation Clinic",
    )
    db_session.flush()

    # 2. Patient switched to DOAC (Apixaban), so INR is no longer needed; instead annual renal review is required
    replacement_ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-WARFARIN-01",
        source_evidence={
            "doc": "Hematology Letter",
            "snippet": "Switched from Warfarin to Apixaban",
        },
        required_action_code="DOAC_RENAL_REVIEW",
        required_action_description="Annual renal function check for DOAC monitoring",
        due_window_end=due_end_2,
        assigned_team="Anticoagulation Clinic",
    )
    db_session.flush()

    # 3. Supersede original obligation with replacement
    audit = ObligationService.supersede_obligation(
        session=db_session,
        original_obligation=original_ob,
        actor_id="DR_HAEMATOLOGY_99",
        reason_code="CLINICAL_PLAN_CHANGED",
        rationale_text="Switched from Warfarin to DOAC; INR monitoring no longer required; DOAC protocol initiated.",
        replacement_obligation=replacement_ob,
    )
    db_session.flush()

    # Query back
    stmt = select(Obligation).where(Obligation.id == original_ob.id)
    queried = db_session.scalar(stmt)

    assert queried.lifecycle_status == LifecycleStatus.SUPERSEDED
    assert queried.superseded_by_id == replacement_ob.id
    assert queried.superseded_by.id == replacement_ob.id

    # Check audit log
    assert audit.event_type == AuditEventType.SUPERSEDED
    assert audit.reason_code == "CLINICAL_PLAN_CHANGED"
    assert audit.new_state["lifecycle_status"] == "SUPERSEDED"


def test_supersede_with_migration_flag(db_session):
    """Verify superseding an obligation using a structured migration flag (e.g. overarching service transfer)."""
    due_end = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

    original_ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-TRANSFER-01",
        source_evidence={"doc": "Discharge"},
        required_action_code="PHYSIO_REHAB",
        required_action_description="Community physiotherapy review",
        due_window_end=due_end,
    )
    db_session.flush()

    # Superseded due to out-of-area relocation/transfer
    audit = ObligationService.supersede_obligation(
        session=db_session,
        original_obligation=original_ob,
        actor_id="CARE_COORDINATOR_55",
        reason_code="EXTERNAL_CARE_TRANSFER",
        rationale_text="Patient relocated to Scotland NHS Trust; local obligations superseded by cross-border transfer.",
        migration_flag="SCOTLAND_NHS_TRANSFER_REF_8819",
    )
    db_session.flush()

    stmt = select(Obligation).where(Obligation.id == original_ob.id)
    queried = db_session.scalar(stmt)

    assert queried.lifecycle_status == LifecycleStatus.SUPERSEDED
    assert queried.superseded_by_id is None
    assert queried.migration_flag == "SCOTLAND_NHS_TRANSFER_REF_8819"
    assert audit.event_type == AuditEventType.SUPERSEDED


def test_administrative_cancellation_vs_supersession(db_session):
    """Verify administrative cancellation is kept distinct from clinical supersession."""
    due_end = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

    # Ingested obligation that was an erroneous extraction
    ob = ObligationService.create_obligation(
        session=db_session,
        patient_id="PAT-CANCEL-01",
        source_evidence={"doc": "Draft Note"},
        required_action_code="COLONOSCOPY",
        required_action_description="Surveillance colonoscopy",
        due_window_end=due_end,
    )
    db_session.flush()

    # Administrative cancellation
    audit = ObligationService.cancel_obligation(
        session=db_session,
        obligation=ob,
        actor_id="LEAD_CLINICIAN_01",
        reason_code="FALSE_EXTRACTION",
        rationale_text="Obligation extracted from past medical history rather than a forward-looking recommendation.",
    )
    db_session.flush()

    assert ob.lifecycle_status == LifecycleStatus.CANCELLED
    assert ob.superseded_by_id is None
    assert ob.migration_flag is None
    assert audit.event_type == AuditEventType.CANCELLATION
    assert audit.reason_code == "FALSE_EXTRACTION"
