"""Pure, deterministic state machine transition engine for Clinical Completion Engine (CCE).

Enforces safety-critical transition guards preventing healthcare drop-offs:
- False closure: requires verified diagnostic review or mandatory explicit manual override.
- Unreviewed diagnostic results: diagnostic report landing leaves obligation ACTIVE.
- Silent dismissals: requires structured reason codes and mandatory clinical rationale.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple

from cce.audit import InvalidStateTransitionError
from cce.enums import (
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
    DomainEvent,
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)
from cce.models import Obligation

TERMINAL_LIFECYCLE_STATUSES: frozenset[LifecycleStatus] = frozenset(
    {
        LifecycleStatus.COMPLETE,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.SUPERSEDED,
        LifecycleStatus.INVALID,
    }
)


class ObligationStateTuple(NamedTuple):
    """Immutable 4-dimensional status tuple representing an obligation's exact state."""

    lifecycle_status: LifecycleStatus
    timeliness_status: TimelinessStatus
    evidence_review_status: EvidenceReviewStatus
    ownership_status: OwnershipStatus

    @classmethod
    def create(
        cls,
        lifecycle_status: LifecycleStatus | str,
        timeliness_status: TimelinessStatus | str,
        evidence_review_status: EvidenceReviewStatus | str,
        ownership_status: OwnershipStatus | str,
    ) -> "ObligationStateTuple":
        """Convenience constructor accepting either enum instances or string names."""
        return cls(
            lifecycle_status=LifecycleStatus(lifecycle_status),
            timeliness_status=TimelinessStatus(timeliness_status),
            evidence_review_status=EvidenceReviewStatus(evidence_review_status),
            ownership_status=OwnershipStatus(ownership_status),
        )

    @classmethod
    def from_obligation(cls, obligation: Obligation) -> "ObligationStateTuple":
        """Construct an ObligationStateTuple from a SQLAlchemy Obligation instance."""
        return cls(
            lifecycle_status=obligation.lifecycle_status,
            timeliness_status=obligation.timeliness_status,
            evidence_review_status=obligation.evidence_review_status,
            ownership_status=obligation.ownership_status,
        )

    def to_dict(self) -> dict[str, str]:
        """Convert state tuple to a string-keyed dictionary matching audit snapshot format."""
        return {
            "lifecycle_status": self.lifecycle_status.value,
            "timeliness_status": self.timeliness_status.value,
            "evidence_review_status": self.evidence_review_status.value,
            "ownership_status": self.ownership_status.value,
        }


@dataclass(frozen=True)
class TransitionContext:
    """Immutable domain context supplied to pure transition evaluations."""

    obligation_id: uuid.UUID
    required_action_code: str
    due_window_end: datetime
    due_window_start: datetime | None = None
    patient_id: str | None = None
    assigned_team: str | None = None
    assigned_user_id: str | None = None
    audit_seq: int = 1
    superseded_by_id: uuid.UUID | None = None
    migration_flag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_obligation(cls, obligation: Obligation) -> "TransitionContext":
        """Extract a TransitionContext snapshot from an active Obligation entity."""
        return cls(
            obligation_id=obligation.id,
            required_action_code=obligation.required_action_code,
            due_window_start=obligation.due_window_start,
            due_window_end=obligation.due_window_end,
            patient_id=obligation.patient_id,
            assigned_team=obligation.assigned_team,
            assigned_user_id=obligation.assigned_user_id,
            audit_seq=obligation.audit_seq,
            superseded_by_id=obligation.superseded_by_id,
            migration_flag=obligation.migration_flag,
        )


@dataclass(frozen=True)
class TransitionResult:
    """Deterministic result of processing a DomainEvent against an ObligationStateTuple."""

    previous_state: ObligationStateTuple
    new_state: ObligationStateTuple
    audit_event_type: AuditEventType
    reason_code: str
    rationale_text: str | None = None
    evidence_reference: dict[str, Any] | None = None
    updated_fields: dict[str, Any] = field(default_factory=dict)
    ambiguous_review_data: dict[str, Any] | None = None
    state_changed: bool = True

    @property
    def has_state_changed(self) -> bool:
        """Indicate whether state dimensions or updated fields changed."""
        return self.state_changed


def transition(
    current_state: ObligationStateTuple,
    event: DomainEvent,
    context: TransitionContext,
) -> TransitionResult:
    """Execute a pure, side-effect-free transition on an obligation state.

    Enforces deterministic safety guards and returns a TransitionResult containing the
    new 4D state and audit specifications.

    Raises:
        InvalidStateTransitionError: If a transition guard is violated.
    """
    # 1. Identity binding guard: Event target must match context target
    if event.obligation_id != context.obligation_id:
        raise InvalidStateTransitionError(
            f"Event obligation_id '{event.obligation_id}' does not match "
            f"context obligation_id '{context.obligation_id}'."
        )

    # 2. Terminal state guard: Terminal obligations cannot undergo state transitions
    if current_state.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES:
        raise InvalidStateTransitionError(
            f"Cannot process event '{type(event).__name__}' on obligation in terminal lifecycle "
            f"status '{current_state.lifecycle_status.value}'."
        )

    # 3. Process specific domain events
    if isinstance(event, HumanConfirmEvent):
        if current_state.lifecycle_status != LifecycleStatus.DRAFT:
            raise InvalidStateTransitionError(
                f"Cannot confirm obligation in status '{current_state.lifecycle_status.value}'. "
                "Obligation must be in DRAFT status to confirm."
            )
        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.ACTIVE,
            timeliness_status=current_state.timeliness_status,
            evidence_review_status=current_state.evidence_review_status,
            ownership_status=current_state.ownership_status,
        )
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.CONFIRMATION,
            reason_code="CLINICAL_CONFIRMATION",
            rationale_text=event.rationale_text
            or "Human clinician confirmed draft obligation into ACTIVE",
            state_changed=True,
        )

    elif isinstance(event, ClockTickEvent):
        t = event.current_simulated_time
        if t > context.due_window_end:
            new_timeliness = TimelinessStatus.OVERDUE
        elif context.due_window_start is not None and t >= context.due_window_start:
            new_timeliness = TimelinessStatus.DUE
        else:
            new_timeliness = TimelinessStatus.NOT_DUE

        new_state = ObligationStateTuple(
            lifecycle_status=current_state.lifecycle_status,
            timeliness_status=new_timeliness,
            evidence_review_status=current_state.evidence_review_status,
            ownership_status=current_state.ownership_status,
        )
        changed = new_timeliness != current_state.timeliness_status
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.STATE_CHANGE,
            reason_code=f"TIMELINESS_{new_timeliness.value}",
            rationale_text=f"Clock tick at {t.isoformat()} evaluated timeliness to {new_timeliness.value}",
            state_changed=changed,
        )

    elif isinstance(event, DiagnosticReportReceivedEvent):
        if current_state.lifecycle_status != LifecycleStatus.ACTIVE:
            raise InvalidStateTransitionError(
                f"Cannot receive diagnostic report for obligation in status "
                f"'{current_state.lifecycle_status.value}'. Obligation must be ACTIVE."
            )
        if event.action_code != context.required_action_code:
            raise InvalidStateTransitionError(
                f"Action code mismatch: report action_code '{event.action_code}' does not match "
                f"obligation required_action_code '{context.required_action_code}'."
            )
        if current_state.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE:
            raise InvalidStateTransitionError(
                "Cannot process diagnostic report: obligation evidence is already VERIFIED_COMPLETE."
            )

        # Invariant: Diagnostic report landing sets ACTION_EVIDENCE_RECEIVED while keeping ACTIVE
        # Prevents premature closure without clinical review!
        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.ACTIVE,
            timeliness_status=current_state.timeliness_status,
            evidence_review_status=EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED,
            ownership_status=current_state.ownership_status,
        )
        evidence_ref = {
            "report_id": event.report_id,
            "action_code": event.action_code,
            **event.report_payload,
        }
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.STATE_CHANGE,
            reason_code="DIAGNOSTIC_REPORT_RECEIVED",
            rationale_text=f"Diagnostic report '{event.report_id}' received matching action code '{event.action_code}'",
            evidence_reference=evidence_ref,
            state_changed=True,
        )

    elif isinstance(event, ClinicalReviewDocumentedEvent):
        if current_state.lifecycle_status != LifecycleStatus.ACTIVE:
            raise InvalidStateTransitionError(
                f"Cannot document clinical review for obligation in status "
                f"'{current_state.lifecycle_status.value}'. Obligation must be ACTIVE."
            )
        if current_state.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE:
            raise InvalidStateTransitionError(
                "Cannot document clinical review when no evidence has been received (NO_EVIDENCE). "
                "Action evidence must be received before clinical review can be verified."
            )

        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.COMPLETE,
            timeliness_status=TimelinessStatus.NOT_APPLICABLE,
            evidence_review_status=EvidenceReviewStatus.VERIFIED_COMPLETE,
            ownership_status=current_state.ownership_status,
        )
        attribution = event.attribution or event.actor_id
        evidence_ref = {
            "review_note_id": event.review_note_id,
            "attribution": attribution,
            "reviewer_id": event.reviewer_id,
            "notes": event.review_notes,
        }
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.STATE_CHANGE,
            reason_code="CLINICAL_REVIEW_VERIFIED",
            rationale_text=f"Clinical review documented (note '{event.review_note_id}') by '{attribution}'",
            evidence_reference=evidence_ref,
            state_changed=True,
        )

    elif isinstance(event, AmbiguousEvidenceFlaggedEvent):
        if current_state.lifecycle_status != LifecycleStatus.ACTIVE:
            raise InvalidStateTransitionError(
                f"Cannot flag ambiguous evidence for obligation in status "
                f"'{current_state.lifecycle_status.value}'. Obligation must be ACTIVE."
            )
        if current_state.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE:
            raise InvalidStateTransitionError(
                "Cannot flag ambiguous evidence: obligation is already VERIFIED_COMPLETE."
            )

        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.ACTIVE,
            timeliness_status=current_state.timeliness_status,
            evidence_review_status=EvidenceReviewStatus.AMBIGUOUS_REVIEW_EVIDENCE,
            ownership_status=current_state.ownership_status,
        )
        evidence_ref = {
            "evidence_snippet": event.evidence_snippet,
            "confidence_score": event.confidence_score,
            "ambiguity_rationale": event.ambiguity_rationale,
        }
        ambiguous_data = {
            "proposed_evidence_snippet": event.evidence_snippet,
            "assigned_reviewer_id": event.assigned_reviewer_id,
            "due_at": event.due_at,
        }
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.STATE_CHANGE,
            reason_code=event.reason_code,
            rationale_text=event.ambiguity_rationale
            or "Diagnostic evidence flagged as ambiguous requiring clinician review",
            evidence_reference=evidence_ref,
            ambiguous_review_data=ambiguous_data,
            state_changed=True,
        )

    elif isinstance(event, SupersedePlanEvent):
        if event.superseded_by_id is None and not event.migration_flag:
            raise InvalidStateTransitionError(
                "SupersedePlanEvent requires either superseded_by_id or migration_flag."
            )

        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.SUPERSEDED,
            timeliness_status=TimelinessStatus.NOT_APPLICABLE,
            evidence_review_status=current_state.evidence_review_status,
            ownership_status=current_state.ownership_status,
        )
        evidence_ref = {
            "superseded_by_id": str(event.superseded_by_id) if event.superseded_by_id else None,
            "migration_flag": event.migration_flag,
        }
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.SUPERSEDED,
            reason_code=event.reason_code,
            rationale_text=event.rationale_text,
            evidence_reference=evidence_ref,
            updated_fields={
                "superseded_by_id": event.superseded_by_id,
                "migration_flag": event.migration_flag,
            },
            state_changed=True,
        )

    elif isinstance(event, CancelObligationEvent):
        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.CANCELLED,
            timeliness_status=TimelinessStatus.NOT_APPLICABLE,
            evidence_review_status=current_state.evidence_review_status,
            ownership_status=current_state.ownership_status,
        )
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.CANCELLATION,
            reason_code=event.reason_code,
            rationale_text=event.rationale_text,
            state_changed=True,
        )

    elif isinstance(event, ManualOverrideEvent):
        new_state = ObligationStateTuple(
            lifecycle_status=LifecycleStatus.COMPLETE,
            timeliness_status=TimelinessStatus.NOT_APPLICABLE,
            evidence_review_status=current_state.evidence_review_status,
            ownership_status=current_state.ownership_status,
        )
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.MANUAL_OVERRIDE,
            reason_code=event.reason_code,
            rationale_text=event.rationale_text,
            evidence_reference={
                "override_actor": event.actor_id,
                "reason_code": event.reason_code,
            },
            state_changed=True,
        )

    elif isinstance(event, AssignOwnershipEvent):
        new_ownership = (
            OwnershipStatus.OWNED
            if (event.assigned_team or event.assigned_user_id)
            else OwnershipStatus.NO_OWNER
        )
        new_state = ObligationStateTuple(
            lifecycle_status=current_state.lifecycle_status,
            timeliness_status=current_state.timeliness_status,
            evidence_review_status=current_state.evidence_review_status,
            ownership_status=new_ownership,
        )
        updated_fields: dict[str, Any] = {
            "assigned_team": event.assigned_team,
            "assigned_user_id": event.assigned_user_id,
        }
        evidence_ref = {
            "assigned_team": event.assigned_team,
            "assigned_user_id": event.assigned_user_id,
        }
        changed = (
            new_ownership != current_state.ownership_status
            or event.assigned_team != context.assigned_team
            or event.assigned_user_id != context.assigned_user_id
        )
        return TransitionResult(
            previous_state=current_state,
            new_state=new_state,
            audit_event_type=AuditEventType.OWNERSHIP_ASSIGNED,
            reason_code=event.reason_code,
            rationale_text=event.rationale_text
            or f"Ownership updated: team={event.assigned_team}, user={event.assigned_user_id}",
            evidence_reference=evidence_ref,
            updated_fields=updated_fields,
            state_changed=changed,
        )

    else:
        raise InvalidStateTransitionError(f"Unsupported event type: {type(event).__name__}")
