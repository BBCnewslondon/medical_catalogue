import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from cce.enums import (
    AmbiguousItemStatus,
    AuditEventType,
    EvidenceReviewStatus,
    LifecycleStatus,
    OwnershipStatus,
    TimelinessStatus,
)


class Base(DeclarativeBase):
    pass


class Obligation(Base):
    """Primary clinical obligation entity.

    Tracks four independent state dimensions (lifecycle, timeliness, evidence_review, ownership)
    and enforces strict clinical auditability and supersession semantics.
    """

    __tablename__ = "obligations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    patient_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    required_action_code: Mapped[str] = mapped_column(String(128), nullable=False)
    required_action_description: Mapped[str] = mapped_column(Text, nullable=False)
    due_window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 4 Independent State Dimensions
    lifecycle_status: Mapped[LifecycleStatus] = mapped_column(
        Enum(LifecycleStatus, name="lifecycle_status", native_enum=True),
        default=LifecycleStatus.DRAFT,
        nullable=False,
    )
    timeliness_status: Mapped[TimelinessStatus] = mapped_column(
        Enum(TimelinessStatus, name="timeliness_status", native_enum=True),
        default=TimelinessStatus.NOT_DUE,
        nullable=False,
    )
    evidence_review_status: Mapped[EvidenceReviewStatus] = mapped_column(
        Enum(EvidenceReviewStatus, name="evidence_review_status", native_enum=True),
        default=EvidenceReviewStatus.NO_EVIDENCE,
        nullable=False,
    )
    ownership_status: Mapped[OwnershipStatus] = mapped_column(
        Enum(OwnershipStatus, name="ownership_status", native_enum=True),
        default=OwnershipStatus.NO_OWNER,
        nullable=False,
    )

    # Accountable Ownership
    assigned_team: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Supersession Pointer (self-referencing FK) & Rationale
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("obligations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    migration_flag: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit Sequence (strictly incremented on each mutation)
    audit_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )

    # Relationships
    superseded_by: Mapped[Optional["Obligation"]] = relationship(
        "Obligation",
        remote_side=[id],
        foreign_keys=[superseded_by_id],
        backref="superseded_obligations",
    )
    audit_logs: Mapped[list["ObligationAuditLog"]] = relationship(
        "ObligationAuditLog",
        back_populates="obligation",
        order_by="ObligationAuditLog.audit_seq",
    )
    ambiguous_review_items: Mapped[list["AmbiguousReviewItem"]] = relationship(
        "AmbiguousReviewItem",
        back_populates="obligation",
    )

    __table_args__ = (
        CheckConstraint(
            "lifecycle_status != 'SUPERSEDED' OR (superseded_by_id IS NOT NULL OR migration_flag IS NOT NULL)",
            name="chk_obligation_superseded",
        ),
        CheckConstraint(
            "(ownership_status != 'OWNED') OR (assigned_team IS NOT NULL OR assigned_user_id IS NOT NULL)",
            name="chk_obligation_ownership",
        ),
        CheckConstraint(
            "due_window_start IS NULL OR due_window_end >= due_window_start",
            name="chk_obligation_due_window",
        ),
        Index(
            "idx_obligations_dimensions",
            "lifecycle_status",
            "timeliness_status",
            "evidence_review_status",
            "ownership_status",
        ),
        Index(
            "idx_obligations_active_risk",
            "timeliness_status",
            "ownership_status",
            postgresql_where=text("lifecycle_status = 'ACTIVE'"),
        ),
    )

    def get_dimensions_snapshot(self) -> dict[str, str]:
        """Return a snapshot dict of the 4 independent status dimensions."""
        return {
            "lifecycle_status": self.lifecycle_status.value
            if hasattr(self.lifecycle_status, "value")
            else str(self.lifecycle_status),
            "timeliness_status": self.timeliness_status.value
            if hasattr(self.timeliness_status, "value")
            else str(self.timeliness_status),
            "evidence_review_status": self.evidence_review_status.value
            if hasattr(self.evidence_review_status, "value")
            else str(self.evidence_review_status),
            "ownership_status": self.ownership_status.value
            if hasattr(self.ownership_status, "value")
            else str(self.ownership_status),
        }


class ObligationAuditLog(Base):
    """Append-only, immutable clinical audit ledger for obligations."""

    __tablename__ = "obligation_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    obligation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("obligations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    audit_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[AuditEventType] = mapped_column(
        Enum(AuditEventType, name="audit_event_type", native_enum=True),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )

    obligation: Mapped["Obligation"] = relationship(
        "Obligation",
        back_populates="audit_logs",
    )

    __table_args__ = (
        Index("idx_audit_log_obligation_seq", "obligation_id", "audit_seq"),
        Index("idx_audit_log_obligation_created", "obligation_id", "created_at"),
    )


class AmbiguousReviewItem(Base):
    """Review queue entity for ambiguous evidence matching requiring clinical verification."""

    __tablename__ = "ambiguous_review_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    obligation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("obligations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposed_evidence_snippet: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assigned_reviewer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AmbiguousItemStatus] = mapped_column(
        Enum(AmbiguousItemStatus, name="ambiguous_item_status", native_enum=True),
        default=AmbiguousItemStatus.OPEN,
        nullable=False,
    )
    resolution_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )

    obligation: Mapped["Obligation"] = relationship(
        "Obligation",
        back_populates="ambiguous_review_items",
    )

    __table_args__ = (
        Index("idx_ambiguous_items_obligation_id", "obligation_id"),
        Index("idx_ambiguous_items_status", "status"),
    )
