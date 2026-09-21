from enum import StrEnum


class LifecycleStatus(StrEnum):
    """Lifecycle progression dimension for a clinical obligation."""

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    INVALID = "INVALID"


class TimelinessStatus(StrEnum):
    """Timeliness dimension relative to clinical deadline window."""

    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceReviewStatus(StrEnum):
    """Evidence reconciliation and clinical review dimension."""

    NO_EVIDENCE = "NO_EVIDENCE"
    ACTION_EVIDENCE_RECEIVED = "ACTION_EVIDENCE_RECEIVED"
    AWAITING_REVIEW_EVIDENCE = "AWAITING_REVIEW_EVIDENCE"
    AMBIGUOUS_REVIEW_EVIDENCE = "AMBIGUOUS_REVIEW_EVIDENCE"
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"


class OwnershipStatus(StrEnum):
    """Clinical responsibility and accountability dimension."""

    OWNED = "OWNED"
    NO_OWNER = "NO_OWNER"


class AuditEventType(StrEnum):
    """Class of audit event logged in immutable obligation audit ledger."""

    CREATION = "CREATION"
    STATE_CHANGE = "STATE_CHANGE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    CANCELLATION = "CANCELLATION"
    SUPERSEDED = "SUPERSEDED"
    OWNERSHIP_ASSIGNED = "OWNERSHIP_ASSIGNED"
    CONFIRMATION = "CONFIRMATION"


class AmbiguousItemStatus(StrEnum):
    """Status of an ambiguous evidence review queue item."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    OVERDUE = "OVERDUE"
