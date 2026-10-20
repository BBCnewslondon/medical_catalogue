"""Clinical Completion Engine (CCE) - Safety-Critical Medical State Machine & Audit Core."""

from cce.audit import (
    AuditMissingError,
    AuditViolationError,
    ImmutabilityViolationError,
    InvalidStateTransitionError,
    build_audit_log,
    register_audit_listeners,
)
from cce.engine import (
    ObligationStateTuple,
    TransitionContext,
    TransitionResult,
    transition,
)
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
    BaseDomainEvent,
    CancelObligationEvent,
    ClinicalReviewDocumentedEvent,
    ClockTickEvent,
    DiagnosticReportReceivedEvent,
    DomainEvent,
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)
from cce.models import AmbiguousReviewItem, Base, Obligation, ObligationAuditLog
from cce.service import ObligationService

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "AmbiguousItemStatus",
    "AuditEventType",
    "EvidenceReviewStatus",
    "LifecycleStatus",
    "OwnershipStatus",
    "TimelinessStatus",
    "AmbiguousReviewItem",
    "Base",
    "Obligation",
    "ObligationAuditLog",
    "AuditMissingError",
    "AuditViolationError",
    "ImmutabilityViolationError",
    "InvalidStateTransitionError",
    "build_audit_log",
    "register_audit_listeners",
    "ObligationService",
    "ObligationStateTuple",
    "TransitionContext",
    "TransitionResult",
    "transition",
    "BaseDomainEvent",
    "DomainEvent",
    "HumanConfirmEvent",
    "ClockTickEvent",
    "DiagnosticReportReceivedEvent",
    "ClinicalReviewDocumentedEvent",
    "AmbiguousEvidenceFlaggedEvent",
    "SupersedePlanEvent",
    "CancelObligationEvent",
    "ManualOverrideEvent",
    "AssignOwnershipEvent",
]
