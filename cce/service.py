import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from cce.enums import (
    AuditEventType,
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)
from cce.models import Obligation, ObligationAuditLog


class ObligationService:
    """Safe, auditable transactional service operations for Clinical Obligations."""

    @staticmethod
    def create_obligation(
        session: Session,
        patient_id: str,
        source_evidence: dict[str, Any],
        required_action_code: str,
        required_action_description: str,
        due_window_end: datetime,
        due_window_start: datetime | None = None,
        actor_id: str = "SYSTEM",
        assigned_team: str | None = None,
        assigned_user_id: str | None = None,
        reason_code: str = "INITIAL_EXTRACTION",
        rationale_text: str | None = None,
        lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT,
        timeliness_status: TimelinessStatus = TimelinessStatus.NOT_DUE,
        evidence_review_status: EvidenceReviewStatus = EvidenceReviewStatus.NO_EVIDENCE,
        ownership_status: OwnershipStatus | None = None,
    ) -> Obligation:
        """Create and ingest a new clinical obligation with its mandatory CREATION audit log."""
        obligation_id = uuid.uuid4()
        if ownership_status is not None:
            ownership = ownership_status
        else:
            ownership = (
                OwnershipStatus.OWNED
                if (assigned_team or assigned_user_id)
                else OwnershipStatus.NO_OWNER
            )

        obligation = Obligation(
            id=obligation_id,
            patient_id=patient_id,
            source_evidence=source_evidence,
            required_action_code=required_action_code,
            required_action_description=required_action_description,
            due_window_start=due_window_start,
            due_window_end=due_window_end,
            lifecycle_status=lifecycle_status,
            timeliness_status=timeliness_status,
            evidence_review_status=evidence_review_status,
            ownership_status=ownership,
            assigned_team=assigned_team,
            assigned_user_id=assigned_user_id,
            audit_seq=1,
        )

        initial_snapshot = obligation.get_dimensions_snapshot()

        audit_entry = ObligationAuditLog(
            obligation_id=obligation_id,
            audit_seq=1,
            event_type=AuditEventType.CREATION,
            actor_id=actor_id,
            previous_state=None,
            new_state=initial_snapshot,
            reason_code=reason_code,
            rationale_text=rationale_text or "Initial obligation ingestion",
            evidence_reference=source_evidence,
        )

        session.add(obligation)
        session.add(audit_entry)
        return obligation

    @staticmethod
    def update_dimensions(
        session: Session,
        obligation: Obligation,
        actor_id: str,
        reason_code: str,
        lifecycle_status: LifecycleStatus | None = None,
        timeliness_status: TimelinessStatus | None = None,
        evidence_review_status: EvidenceReviewStatus | None = None,
        ownership_status: OwnershipStatus | None = None,
        event_type: AuditEventType = AuditEventType.STATE_CHANGE,
        rationale_text: str | None = None,
        evidence_reference: dict[str, Any] | None = None,
    ) -> ObligationAuditLog:
        """Atomically update state dimensions and record a corresponding audit log."""
        prev_snapshot = obligation.get_dimensions_snapshot()
        next_seq = obligation.audit_seq + 1

        if lifecycle_status is not None:
            obligation.lifecycle_status = lifecycle_status
        if timeliness_status is not None:
            obligation.timeliness_status = timeliness_status
        if evidence_review_status is not None:
            obligation.evidence_review_status = evidence_review_status
        if ownership_status is not None:
            obligation.ownership_status = ownership_status

        # Synchronize ORM audit sequence
        obligation.audit_seq = next_seq
        new_snapshot = obligation.get_dimensions_snapshot()

        audit_entry = ObligationAuditLog(
            obligation_id=obligation.id,
            audit_seq=next_seq,
            event_type=event_type,
            actor_id=actor_id,
            previous_state=prev_snapshot,
            new_state=new_snapshot,
            reason_code=reason_code,
            rationale_text=rationale_text,
            evidence_reference=evidence_reference,
        )

        session.add(audit_entry)
        return audit_entry

    @staticmethod
    def supersede_obligation(
        session: Session,
        original_obligation: Obligation,
        actor_id: str,
        reason_code: str,
        rationale_text: str,
        replacement_obligation: Obligation | None = None,
        migration_flag: str | None = None,
        evidence_reference: dict[str, Any] | None = None,
    ) -> ObligationAuditLog:
        """Transition an obligation to SUPERSEDED and link it to replacement or migration rationale."""
        if replacement_obligation is None and not migration_flag:
            raise ValueError(
                "A superseded obligation must specify either a replacement_obligation "
                "or an explicit migration_flag."
            )

        prev_snapshot = original_obligation.get_dimensions_snapshot()
        next_seq = original_obligation.audit_seq + 1

        original_obligation.lifecycle_status = LifecycleStatus.SUPERSEDED
        if replacement_obligation is not None:
            original_obligation.superseded_by_id = replacement_obligation.id
        if migration_flag is not None:
            original_obligation.migration_flag = migration_flag

        original_obligation.audit_seq = next_seq
        new_snapshot = original_obligation.get_dimensions_snapshot()

        audit_entry = ObligationAuditLog(
            obligation_id=original_obligation.id,
            audit_seq=next_seq,
            event_type=AuditEventType.SUPERSEDED,
            actor_id=actor_id,
            previous_state=prev_snapshot,
            new_state=new_snapshot,
            reason_code=reason_code,
            rationale_text=rationale_text,
            evidence_reference=evidence_reference
            or (
                {"superseded_by_id": str(replacement_obligation.id)}
                if replacement_obligation
                else {"migration_flag": migration_flag}
            ),
        )

        session.add(audit_entry)
        return audit_entry

    @staticmethod
    def cancel_obligation(
        session: Session,
        obligation: Obligation,
        actor_id: str,
        reason_code: str,
        rationale_text: str,
        evidence_reference: dict[str, Any] | None = None,
    ) -> ObligationAuditLog:
        """Administratively cancel an obligation with clinical rationale."""
        prev_snapshot = obligation.get_dimensions_snapshot()
        next_seq = obligation.audit_seq + 1

        obligation.lifecycle_status = LifecycleStatus.CANCELLED
        obligation.audit_seq = next_seq
        new_snapshot = obligation.get_dimensions_snapshot()

        audit_entry = ObligationAuditLog(
            obligation_id=obligation.id,
            audit_seq=next_seq,
            event_type=AuditEventType.CANCELLATION,
            actor_id=actor_id,
            previous_state=prev_snapshot,
            new_state=new_snapshot,
            reason_code=reason_code,
            rationale_text=rationale_text,
            evidence_reference=evidence_reference,
        )

        session.add(audit_entry)
        return audit_entry

    @staticmethod
    def assign_owner(
        session: Session,
        obligation: Obligation,
        actor_id: str,
        assigned_team: str | None = None,
        assigned_user_id: str | None = None,
        ownership_status: OwnershipStatus | None = None,
        rationale_text: str | None = None,
    ) -> ObligationAuditLog:
        """Assign or update accountable clinical owner."""
        prev_snapshot = obligation.get_dimensions_snapshot()
        next_seq = obligation.audit_seq + 1

        obligation.assigned_team = assigned_team
        obligation.assigned_user_id = assigned_user_id

        if ownership_status is not None:
            obligation.ownership_status = ownership_status
        else:
            obligation.ownership_status = (
                OwnershipStatus.OWNED
                if (assigned_team or assigned_user_id)
                else OwnershipStatus.NO_OWNER
            )

        obligation.audit_seq = next_seq
        new_snapshot = obligation.get_dimensions_snapshot()

        audit_entry = ObligationAuditLog(
            obligation_id=obligation.id,
            audit_seq=next_seq,
            event_type=AuditEventType.OWNERSHIP_ASSIGNED,
            actor_id=actor_id,
            previous_state=prev_snapshot,
            new_state=new_snapshot,
            reason_code="OWNERSHIP_ALLOCATION",
            rationale_text=rationale_text
            or f"Assigned to team={assigned_team}, user={assigned_user_id}",
            evidence_reference={
                "assigned_team": assigned_team,
                "assigned_user_id": assigned_user_id,
            },
        )

        session.add(audit_entry)
        return audit_entry
