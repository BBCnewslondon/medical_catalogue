from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from cce.enums import AuditEventType
from cce.models import Obligation, ObligationAuditLog


class AuditViolationError(Exception):
    """Base exception for audit and governance violations."""

    pass


class AuditMissingError(AuditViolationError):
    """Raised when an obligation mutation lacks a corresponding audit log entry."""

    pass


class ImmutabilityViolationError(AuditViolationError):
    """Raised when an operation attempts to mutate or delete immutable clinical entities."""

    pass


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state machine transition is attempted."""

    pass


def build_audit_log(
    obligation: Obligation,
    event_type: AuditEventType,
    actor_id: str,
    reason_code: str,
    rationale_text: str | None = None,
    evidence_reference: dict[str, Any] | None = None,
    previous_state: dict[str, Any] | None = None,
    target_audit_seq: int | None = None,
) -> ObligationAuditLog:
    """Build an ObligationAuditLog entry paired to an obligation's current or target mutation.

    Args:
        obligation: The target Obligation entity.
        event_type: The category of clinical/system event.
        actor_id: Named clinician or system process making the change.
        reason_code: Structured reason (e.g. CLINICAL_PLAN_CHANGED, PATIENT_DECEASED).
        rationale_text: Free-text explanation.
        evidence_reference: Reference payload to justifying clinical report/note.
        previous_state: Snapshot of dimensions prior to change (default: computed from obligation history).
        target_audit_seq: Explicit audit sequence number (default: obligation.audit_seq).
    """
    if target_audit_seq is None:
        target_audit_seq = obligation.audit_seq

    new_state = obligation.get_dimensions_snapshot()

    return ObligationAuditLog(
        obligation_id=obligation.id,
        audit_seq=target_audit_seq,
        event_type=event_type,
        actor_id=actor_id,
        previous_state=previous_state,
        new_state=new_state,
        reason_code=reason_code,
        rationale_text=rationale_text,
        evidence_reference=evidence_reference,
    )


def register_audit_listeners() -> None:
    """Register SQLAlchemy Session-level event listeners to enforce defensive audit invariants."""

    @event.listens_for(Session, "before_flush")
    def _enforce_audit_invariants_before_flush(
        session: Session, flush_context: Any, instances: Any
    ) -> None:
        # 1. Check for prohibited deletions
        for deleted_obj in session.deleted:
            if isinstance(deleted_obj, Obligation):
                raise ImmutabilityViolationError(
                    f"Direct deletion of obligation {deleted_obj.id} is strictly prohibited for clinical safety. "
                    "Use lifecycle cancellation or supersession instead."
                )
            if isinstance(deleted_obj, ObligationAuditLog):
                raise ImmutabilityViolationError(
                    f"Deletions from obligation_audit_log (id: {deleted_obj.id}) are prohibited. "
                    "The audit ledger is immutable and append-only."
                )

        # 2. Check for prohibited updates on immutable audit log
        for dirty_obj in session.dirty:
            if isinstance(dirty_obj, ObligationAuditLog):
                state = inspect(dirty_obj)
                # If persistent attributes modified
                if state.modified:
                    raise ImmutabilityViolationError(
                        f"Updates to obligation_audit_log (id: {dirty_obj.id}) are prohibited. "
                        "The audit ledger is immutable and append-only."
                    )

        # 3. Check for new Obligations (must have matching CREATION audit log with audit_seq = 1)
        for new_obj in session.new:
            if isinstance(new_obj, Obligation):
                # Ensure an audit log is staged in session.new for this obligation
                staged_audits = [
                    obj
                    for obj in session.new
                    if isinstance(obj, ObligationAuditLog)
                    and (obj.obligation_id == new_obj.id or obj.obligation is new_obj)
                    and obj.audit_seq == 1
                ]
                if not staged_audits:
                    raise AuditMissingError(
                        f"Obligation {new_obj.id} insertion lacks required creation audit log "
                        f"with event_type=CREATION and audit_seq=1."
                    )

        # 4. Check for dirty Obligations (must have matching audit log with audit_seq = old_seq + 1)
        for dirty_obj in session.dirty:
            if isinstance(dirty_obj, Obligation):
                state = inspect(dirty_obj)
                # Check if meaningful columns changed
                attrs_changed = [attr.key for attr in state.attrs if attr.history.has_changes()]
                # If only updated_at or audit_seq touched, might be DB trigger sync, otherwise real update:
                meaningful_changes = [
                    k for k in attrs_changed if k not in ("updated_at", "audit_seq")
                ]
                if meaningful_changes:
                    audit_seq_history = state.attrs["audit_seq"].history
                    if audit_seq_history.has_changes() and audit_seq_history.deleted:
                        prev_seq = audit_seq_history.deleted[0]
                    else:
                        prev_seq = dirty_obj.audit_seq
                    expected_seq = prev_seq + 1

                    staged_audits = [
                        obj
                        for obj in session.new
                        if isinstance(obj, ObligationAuditLog)
                        and (obj.obligation_id == dirty_obj.id or obj.obligation is dirty_obj)
                        and obj.audit_seq == expected_seq
                    ]
                    if not staged_audits:
                        raise AuditMissingError(
                            f"Obligation {dirty_obj.id} updated without required audit log. "
                            f"Changed fields: {meaningful_changes}. "
                            f"Expected an ObligationAuditLog with audit_seq={expected_seq}."
                        )
