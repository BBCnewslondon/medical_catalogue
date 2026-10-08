"""Strongly typed domain events for the Clinical Completion Engine (CCE).

All domain events represent immutable facts emitted by clinicians, external diagnostic
systems, or scheduled timers, and strictly adhere to Pydantic V2 specifications.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BaseDomainEvent(BaseModel):
    """Abstract base model for all CCE domain events.

    Guarantees immutable event payload with UUID identification, timezone-aware
    timestamping, identifiable actor provenance, and target obligation binding.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique event identifier")
    timestamp: datetime = Field(
        default_factory=_utc_now,
        description="Timezone-aware timestamp of event occurrence",
    )
    actor_id: str = Field(..., min_length=1, description="Clinician or system identifier")
    obligation_id: uuid.UUID = Field(..., description="Target obligation identifier")

    @field_validator("timestamp", mode="after")
    @classmethod
    def _enforce_timezone_aware_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Event timestamp must be timezone-aware (tzinfo cannot be None)")
        return v


class HumanConfirmEvent(BaseDomainEvent):
    """Confirms a DRAFT obligation, transitioning it to ACTIVE."""

    event_type: Literal["HumanConfirmEvent"] = "HumanConfirmEvent"
    rationale_text: str | None = Field(
        default=None,
        description="Optional clinical confirmation notes or comments",
    )


class ClockTickEvent(BaseDomainEvent):
    """Evaluates current simulated time against due_window_start and due_window_end."""

    event_type: Literal["ClockTickEvent"] = "ClockTickEvent"
    actor_id: str = Field(
        default="SYSTEM_CLOCK",
        min_length=1,
        description="Timer or scheduler identifier",
    )
    current_simulated_time: datetime = Field(
        ...,
        description="Timezone-aware simulated evaluation timestamp",
    )

    @field_validator("current_simulated_time", mode="after")
    @classmethod
    def _enforce_timezone_aware_simulated_time(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "current_simulated_time must be timezone-aware (tzinfo cannot be None)"
            )
        return v


class DiagnosticReportReceivedEvent(BaseDomainEvent):
    """A lab test or imaging report has landed (e.g., blood test processed).

    Must contain report_id and action_code match.
    """

    event_type: Literal["DiagnosticReportReceivedEvent"] = "DiagnosticReportReceivedEvent"
    report_id: str = Field(
        ..., min_length=1, description="Unique external lab or imaging report ID"
    )
    action_code: str = Field(
        ...,
        min_length=1,
        description="Standardized clinical action/procedure code (e.g. LOINC/SNOMED)",
    )
    report_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic report findings, values, and metadata",
    )


class ClinicalReviewDocumentedEvent(BaseDomainEvent):
    """A clinician has documented their review of the diagnostic report.

    Must contain review_note_id and attribution.
    """

    event_type: Literal["ClinicalReviewDocumentedEvent"] = "ClinicalReviewDocumentedEvent"
    review_note_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of clinical review note or EHR consultation entry",
    )
    attribution: str = Field(
        default="",
        description="Attribution of reviewing clinician (defaults to actor_id if omitted)",
    )
    reviewer_id: str | None = Field(
        default=None,
        description="Optional reviewer user ID if different from actor_id",
    )
    review_notes: str | None = Field(
        default=None,
        description="Clinician's synthesis and review rationale",
    )

    @model_validator(mode="after")
    def _populate_attribution(self) -> "ClinicalReviewDocumentedEvent":
        if not self.attribution:
            # Pydantic models are frozen; using object.__setattr__ to default attribution to actor_id
            object.__setattr__(self, "attribution", self.actor_id)
        return self


class AmbiguousEvidenceFlaggedEvent(BaseDomainEvent):
    """Ingested evidence cannot be deterministically matched with high confidence."""

    event_type: Literal["AmbiguousEvidenceFlaggedEvent"] = "AmbiguousEvidenceFlaggedEvent"
    evidence_snippet: dict[str, Any] = Field(
        default_factory=dict,
        description="Snippet or metadata of candidate evidence",
    )
    confidence_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    reason_code: str = Field(
        default="AMBIGUOUS_EVIDENCE_MATCH",
        min_length=1,
        description="Categorical reason for ambiguity",
    )
    ambiguity_rationale: str | None = Field(
        default=None,
        description="Detailed explanation of ambiguity",
    )
    due_at: datetime | None = Field(
        default=None,
        description="Deadline for human clinician review of ambiguous item",
    )
    assigned_reviewer_id: str | None = Field(
        default=None,
        description="Clinician allocated to resolve ambiguity",
    )


class SupersedePlanEvent(BaseDomainEvent):
    """Clinical plan changed legitimately; replaces obligation with superseded_by_id or migration_flag."""

    event_type: Literal["SupersedePlanEvent"] = "SupersedePlanEvent"
    superseded_by_id: uuid.UUID | None = Field(
        default=None,
        description="Successor obligation UUID",
    )
    migration_flag: str | None = Field(
        default=None,
        description="Structured rationale flag (e.g. PATIENT_TRANSFERRED, CARE_PATHWAY_DISCONTINUED)",
    )
    reason_code: str = Field(
        ...,
        min_length=1,
        description="Structured clinical reason code",
    )
    rationale_text: str = Field(
        ...,
        min_length=1,
        description="Mandatory clinical explanation for replacing the obligation",
    )

    @model_validator(mode="after")
    def _validate_superseded_target(self) -> "SupersedePlanEvent":
        if self.superseded_by_id is None and not self.migration_flag:
            raise ValueError(
                "SupersedePlanEvent requires either superseded_by_id or migration_flag"
            )
        return self


class CancelObligationEvent(BaseDomainEvent):
    """Administrative or clinical cancellation; requires structured reason_code and rationale_text."""

    event_type: Literal["CancelObligationEvent"] = "CancelObligationEvent"
    reason_code: str = Field(
        ...,
        min_length=1,
        description="Structured reason code (e.g. ERRONEUS_EXTRACTION, DUPLICATE)",
    )
    rationale_text: str = Field(
        ...,
        min_length=1,
        description="Mandatory clinical or administrative rationale",
    )


class ManualOverrideEvent(BaseDomainEvent):
    """Clinician forces COMPLETE despite missing verification.

    Requires mandatory actor_id, reason_code, and rationale_text.
    """

    event_type: Literal["ManualOverrideEvent"] = "ManualOverrideEvent"
    reason_code: str = Field(
        ...,
        min_length=1,
        description="Structured override reason code (e.g. VERIFIED_EXTERNAL_PROVIDER)",
    )
    rationale_text: str = Field(
        ...,
        min_length=1,
        description="Mandatory clinical explanation for manual force-completion",
    )


class AssignOwnershipEvent(BaseDomainEvent):
    """Assigns assigned_team and/or assigned_user_id."""

    event_type: Literal["AssignOwnershipEvent"] = "AssignOwnershipEvent"
    assigned_team: str | None = Field(
        default=None,
        description="Accountable clinical team or ward (e.g. Ward 4B Renal)",
    )
    assigned_user_id: str | None = Field(
        default=None,
        description="Accountable clinician identifier",
    )
    reason_code: str = Field(
        default="OWNERSHIP_ALLOCATION",
        min_length=1,
        description="Reason code for ownership assignment",
    )
    rationale_text: str | None = Field(
        default=None,
        description="Optional ownership assignment notes",
    )

    @model_validator(mode="after")
    def _validate_at_least_one_owner_if_assigned(self) -> "AssignOwnershipEvent":
        # Note: If both are None, this indicates explicit unassignment
        return self


DomainEvent = Annotated[
    HumanConfirmEvent
    | ClockTickEvent
    | DiagnosticReportReceivedEvent
    | ClinicalReviewDocumentedEvent
    | AmbiguousEvidenceFlaggedEvent
    | SupersedePlanEvent
    | CancelObligationEvent
    | ManualOverrideEvent
    | AssignOwnershipEvent,
    Field(discriminator="event_type"),
]
