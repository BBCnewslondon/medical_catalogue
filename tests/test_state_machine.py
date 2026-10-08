"""Unit tests for the pure, deterministic state machine transition engine."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from cce.audit import InvalidStateTransitionError
from cce.engine import (
    ObligationStateTuple,
    TransitionContext,
    transition,
)
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
    HumanConfirmEvent,
    ManualOverrideEvent,
    SupersedePlanEvent,
)


def _make_context(
    obligation_id: uuid.UUID | None = None,
    action_code: str = "REPEAT_CREATININE",
    due_start: datetime | None = None,
    due_end: datetime | None = None,
    audit_seq: int = 1,
) -> TransitionContext:
    ob_id = obligation_id or uuid.uuid4()
    now = datetime.now(UTC)
    return TransitionContext(
        obligation_id=ob_id,
        required_action_code=action_code,
        due_window_start=due_start or (now + timedelta(days=7)),
        due_window_end=due_end or (now + timedelta(days=14)),
        audit_seq=audit_seq,
    )


def test_obligation_state_tuple_helpers():
    state = ObligationStateTuple.create(
        lifecycle_status="ACTIVE",
        timeliness_status="NOT_DUE",
        evidence_review_status="NO_EVIDENCE",
        ownership_status="NO_OWNER",
    )
    assert state.lifecycle_status == LifecycleStatus.ACTIVE
    assert state.timeliness_status == TimelinessStatus.NOT_DUE
    assert state.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE
    assert state.ownership_status == OwnershipStatus.NO_OWNER

    d = state.to_dict()
    assert d["lifecycle_status"] == "ACTIVE"
    assert d["timeliness_status"] == "NOT_DUE"
    assert d["evidence_review_status"] == "NO_EVIDENCE"
    assert d["ownership_status"] == "NO_OWNER"


def test_transition_enforces_obligation_id_binding():
    ob_id_1 = uuid.uuid4()
    ob_id_2 = uuid.uuid4()

    ctx = _make_context(obligation_id=ob_id_1)
    event = HumanConfirmEvent(actor_id="dr_who", obligation_id=ob_id_2)
    state = ObligationStateTuple(
        LifecycleStatus.DRAFT,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )

    with pytest.raises(InvalidStateTransitionError, match="does not match context obligation_id"):
        transition(state, event, ctx)


def test_human_confirm_event_happy_path():
    ctx = _make_context()
    event = HumanConfirmEvent(
        actor_id="consultant_1",
        obligation_id=ctx.obligation_id,
        rationale_text="Confirmed repeat renal panel needed post discharge",
    )
    initial_state = ObligationStateTuple(
        LifecycleStatus.DRAFT,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )

    result = transition(initial_state, event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.new_state.timeliness_status == TimelinessStatus.NOT_DUE
    assert result.audit_event_type == AuditEventType.CONFIRMATION
    assert result.reason_code == "CLINICAL_CONFIRMATION"
    assert result.has_state_changed is True


def test_human_confirm_rejects_non_draft_obligations():
    ctx = _make_context()
    event = HumanConfirmEvent(actor_id="consultant_1", obligation_id=ctx.obligation_id)

    # Already active
    active_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )
    with pytest.raises(InvalidStateTransitionError, match="must be in DRAFT status"):
        transition(active_state, event, ctx)

    # Complete (terminal)
    complete_state = ObligationStateTuple(
        LifecycleStatus.COMPLETE,
        TimelinessStatus.NOT_APPLICABLE,
        EvidenceReviewStatus.VERIFIED_COMPLETE,
        OwnershipStatus.OWNED,
    )
    with pytest.raises(InvalidStateTransitionError, match="terminal"):
        transition(complete_state, event, ctx)


def test_clock_tick_evaluates_due_window():
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    w_start = now + timedelta(days=7)
    w_end = now + timedelta(days=14)
    ctx = _make_context(due_start=w_start, due_end=w_end)

    initial_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )

    # 1. Before window start: NOT_DUE
    t_before = now + timedelta(days=2)
    ev_before = ClockTickEvent(obligation_id=ctx.obligation_id, current_simulated_time=t_before)
    res_before = transition(initial_state, ev_before, ctx)
    assert res_before.new_state.timeliness_status == TimelinessStatus.NOT_DUE
    assert res_before.has_state_changed is False

    # 2. Within window [w_start, w_end]: DUE
    t_due = now + timedelta(days=10)
    ev_due = ClockTickEvent(obligation_id=ctx.obligation_id, current_simulated_time=t_due)
    res_due = transition(initial_state, ev_due, ctx)
    assert res_due.new_state.timeliness_status == TimelinessStatus.DUE
    assert res_due.has_state_changed is True
    assert res_due.audit_event_type == AuditEventType.STATE_CHANGE

    # 3. Beyond window end: OVERDUE
    t_overdue = now + timedelta(days=16)
    ev_overdue = ClockTickEvent(obligation_id=ctx.obligation_id, current_simulated_time=t_overdue)
    res_overdue = transition(res_due.new_state, ev_overdue, ctx)
    assert res_overdue.new_state.timeliness_status == TimelinessStatus.OVERDUE
    assert res_overdue.has_state_changed is True


def test_clock_tick_without_window_start():
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
    w_end = now + timedelta(days=5)
    ctx = _make_context(due_start=None, due_end=w_end)

    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )

    # Before end: NOT_DUE
    ev1 = ClockTickEvent(
        obligation_id=ctx.obligation_id, current_simulated_time=now + timedelta(days=2)
    )
    assert transition(state, ev1, ctx).new_state.timeliness_status == TimelinessStatus.NOT_DUE

    # Past end: OVERDUE
    ev2 = ClockTickEvent(
        obligation_id=ctx.obligation_id, current_simulated_time=now + timedelta(days=6)
    )
    assert transition(state, ev2, ctx).new_state.timeliness_status == TimelinessStatus.OVERDUE


def test_clock_tick_rejects_terminal_obligations():
    ctx = _make_context()
    now = datetime.now(UTC)
    ev = ClockTickEvent(obligation_id=ctx.obligation_id, current_simulated_time=now)

    for terminal_status in [
        LifecycleStatus.COMPLETE,
        LifecycleStatus.CANCELLED,
        LifecycleStatus.SUPERSEDED,
    ]:
        state = ObligationStateTuple(
            terminal_status,
            TimelinessStatus.NOT_APPLICABLE,
            EvidenceReviewStatus.NO_EVIDENCE,
            OwnershipStatus.NO_OWNER,
        )
        with pytest.raises(InvalidStateTransitionError, match="terminal"):
            transition(state, ev, ctx)


def test_diagnostic_report_prevents_false_closure():
    """Safety guard: lab report receipt must NOT close obligation; it must remain ACTIVE."""
    ctx = _make_context(action_code="REPEAT_CREATININE")
    event = DiagnosticReportReceivedEvent(
        actor_id="LAB_INTERFACE",
        obligation_id=ctx.obligation_id,
        report_id="LAB-8812",
        action_code="REPEAT_CREATININE",
        report_payload={"creatinine": 110},
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    result = transition(state, event, ctx)

    # Invariant: Must remain ACTIVE to avoid unreviewed diagnostic report drop-off!
    assert result.new_state.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.new_state.evidence_review_status == EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED
    assert result.new_state.timeliness_status == TimelinessStatus.DUE
    assert result.reason_code == "DIAGNOSTIC_REPORT_RECEIVED"


def test_diagnostic_report_guards():
    ctx = _make_context(action_code="REPEAT_CREATININE")

    # Guard 1: Action code mismatch rejected
    mismatch_event = DiagnosticReportReceivedEvent(
        actor_id="LAB_INTERFACE",
        obligation_id=ctx.obligation_id,
        report_id="LAB-8812",
        action_code="LIVER_FUNCTION_TEST",
    )
    active_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )
    with pytest.raises(InvalidStateTransitionError, match="Action code mismatch"):
        transition(active_state, mismatch_event, ctx)

    # Guard 2: Report cannot land on DRAFT obligation
    valid_event = DiagnosticReportReceivedEvent(
        actor_id="LAB_INTERFACE",
        obligation_id=ctx.obligation_id,
        report_id="LAB-8812",
        action_code="REPEAT_CREATININE",
    )
    draft_state = ObligationStateTuple(
        LifecycleStatus.DRAFT,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )
    with pytest.raises(InvalidStateTransitionError, match="must be ACTIVE"):
        transition(draft_state, valid_event, ctx)


def test_clinical_review_transitions_to_complete():
    """Safety guard: verified clinical review allows formal transition to COMPLETE."""
    ctx = _make_context()
    review_event = ClinicalReviewDocumentedEvent(
        actor_id="consultant_7",
        obligation_id=ctx.obligation_id,
        review_note_id="NOTE-888",
        attribution="Dr. P. Vance (Consultant)",
        review_notes="Serum creatinine stable at 90 umol/L. AKI resolved.",
    )
    # State with action evidence received
    evidence_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED,
        OwnershipStatus.OWNED,
    )

    result = transition(evidence_state, review_event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.COMPLETE
    assert result.new_state.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE
    assert result.new_state.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    assert result.reason_code == "CLINICAL_REVIEW_VERIFIED"


def test_clinical_review_prevents_premature_closure_without_evidence():
    """Safety guard: clinician review cannot verify an obligation without diagnostic evidence."""
    ctx = _make_context()
    review_event = ClinicalReviewDocumentedEvent(
        actor_id="consultant_7",
        obligation_id=ctx.obligation_id,
        review_note_id="NOTE-888",
    )
    no_evidence_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    with pytest.raises(InvalidStateTransitionError, match="no evidence has been received"):
        transition(no_evidence_state, review_event, ctx)


def test_ambiguous_evidence_flagged_event():
    ctx = _make_context()
    event = AmbiguousEvidenceFlaggedEvent(
        actor_id="NLP_MATCHER",
        obligation_id=ctx.obligation_id,
        evidence_snippet={"raw_lab": "Creatinine 105 in clinic letter"},
        confidence_score=0.48,
        ambiguity_rationale="Unstructured clinic note mention without formal lab requisition ID",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    result = transition(state, event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.ACTIVE
    assert result.new_state.evidence_review_status == EvidenceReviewStatus.AMBIGUOUS_REVIEW_EVIDENCE
    assert result.ambiguous_review_data is not None


def test_clinical_review_can_resolve_ambiguous_evidence():
    ctx = _make_context()
    review_event = ClinicalReviewDocumentedEvent(
        actor_id="consultant_7",
        obligation_id=ctx.obligation_id,
        review_note_id="NOTE-999",
        attribution="Dr. P. Vance",
    )
    ambiguous_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.AMBIGUOUS_REVIEW_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    result = transition(ambiguous_state, review_event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.COMPLETE
    assert result.new_state.evidence_review_status == EvidenceReviewStatus.VERIFIED_COMPLETE


def test_manual_override_preserves_unverified_evidence_dimension():
    """Safety auditability: manual override completes obligation but keeps evidence dimension unverified."""
    ctx = _make_context()
    override_event = ManualOverrideEvent(
        actor_id="consultant_chief",
        obligation_id=ctx.obligation_id,
        reason_code="VERIFIED_IN_THIRD_PARTY_SYSTEM",
        rationale_text="Personally verified normal renal function on Scottish Care Information portal",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.OVERDUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    result = transition(state, override_event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.COMPLETE
    assert result.new_state.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    # Critical audit invariant: Evidence status stays NO_EVIDENCE, proving override rather than evidence verification!
    assert result.new_state.evidence_review_status == EvidenceReviewStatus.NO_EVIDENCE
    assert result.audit_event_type == AuditEventType.MANUAL_OVERRIDE


def test_supersede_plan_event():
    ctx = _make_context()
    successor_id = uuid.uuid4()
    event = SupersedePlanEvent(
        actor_id="consultant_cardio",
        obligation_id=ctx.obligation_id,
        superseded_by_id=successor_id,
        reason_code="REGIMEN_CHANGE",
        rationale_text="Warfarin monitoring superseded by Apixaban initiation",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    result = transition(state, event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.SUPERSEDED
    assert result.new_state.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    assert result.updated_fields["superseded_by_id"] == successor_id
    assert result.audit_event_type == AuditEventType.SUPERSEDED


def test_cancel_obligation_event():
    ctx = _make_context()
    event = CancelObligationEvent(
        actor_id="ward_clerk",
        obligation_id=ctx.obligation_id,
        reason_code="CLINICAL_DISMISSAL",
        rationale_text="Patient discharged to palliative care, routine AKI surveillance discontinued",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )

    result = transition(state, event, ctx)

    assert result.new_state.lifecycle_status == LifecycleStatus.CANCELLED
    assert result.new_state.timeliness_status == TimelinessStatus.NOT_APPLICABLE
    assert result.audit_event_type == AuditEventType.CANCELLATION


def test_assign_ownership_event():
    ctx = _make_context()
    event = AssignOwnershipEvent(
        actor_id="ward_clerk",
        obligation_id=ctx.obligation_id,
        assigned_team="Ward 4B Nephrology",
        assigned_user_id="consultant_33",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )

    result = transition(state, event, ctx)

    assert result.new_state.ownership_status == OwnershipStatus.OWNED
    assert result.updated_fields["assigned_team"] == "Ward 4B Nephrology"
    assert result.updated_fields["assigned_user_id"] == "consultant_33"
    assert result.audit_event_type == AuditEventType.OWNERSHIP_ASSIGNED


def test_diagnostic_report_rejected_if_already_verified():
    ctx = _make_context(action_code="REPEAT_CREATININE")
    event = DiagnosticReportReceivedEvent(
        actor_id="LAB",
        obligation_id=ctx.obligation_id,
        report_id="LAB-123",
        action_code="REPEAT_CREATININE",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.VERIFIED_COMPLETE,
        OwnershipStatus.OWNED,
    )
    with pytest.raises(InvalidStateTransitionError, match="already VERIFIED_COMPLETE"):
        transition(state, event, ctx)


def test_clinical_review_rejected_on_draft():
    ctx = _make_context()
    event = ClinicalReviewDocumentedEvent(
        actor_id="dr_x",
        obligation_id=ctx.obligation_id,
        review_note_id="REV-1",
    )
    state = ObligationStateTuple(
        LifecycleStatus.DRAFT,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.ACTION_EVIDENCE_RECEIVED,
        OwnershipStatus.NO_OWNER,
    )
    with pytest.raises(InvalidStateTransitionError, match="must be ACTIVE"):
        transition(state, event, ctx)


def test_ambiguous_evidence_guards():
    ctx = _make_context()
    event = AmbiguousEvidenceFlaggedEvent(
        actor_id="NLP",
        obligation_id=ctx.obligation_id,
        evidence_snippet={},
    )
    # Draft rejected
    draft_state = ObligationStateTuple(
        LifecycleStatus.DRAFT,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )
    with pytest.raises(InvalidStateTransitionError, match="must be ACTIVE"):
        transition(draft_state, event, ctx)

    # Verified complete rejected
    verified_state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.VERIFIED_COMPLETE,
        OwnershipStatus.NO_OWNER,
    )
    with pytest.raises(InvalidStateTransitionError, match="already VERIFIED_COMPLETE"):
        transition(verified_state, event, ctx)


def test_unsupported_event_type():
    ctx = _make_context()
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.NO_OWNER,
    )

    class DummyEvent:
        obligation_id = ctx.obligation_id

    with pytest.raises(InvalidStateTransitionError, match="Unsupported event type"):
        transition(state, DummyEvent(), ctx)  # type: ignore[arg-type]


def test_supersede_without_successor_or_flag_raises_error():
    ctx = _make_context()
    event = SupersedePlanEvent.model_construct(
        event_id=uuid.uuid4(),
        timestamp=datetime.now(UTC),
        actor_id="dr_x",
        obligation_id=ctx.obligation_id,
        superseded_by_id=None,
        migration_flag=None,
        reason_code="CODE",
        rationale_text="Rationale",
    )
    state = ObligationStateTuple(
        LifecycleStatus.ACTIVE,
        TimelinessStatus.NOT_DUE,
        EvidenceReviewStatus.NO_EVIDENCE,
        OwnershipStatus.OWNED,
    )
    with pytest.raises(
        InvalidStateTransitionError, match="either superseded_by_id or migration_flag"
    ):
        transition(state, event, ctx)


def test_transition_context_from_obligation():
    from cce.models import Obligation

    now = datetime.now(UTC)
    ob_id = uuid.uuid4()
    ob = Obligation(
        id=ob_id,
        patient_id="PAT-CTX-1",
        source_evidence={"ref": "test"},
        required_action_code="TEST_CODE",
        required_action_description="Test action",
        due_window_start=now,
        due_window_end=now + timedelta(days=7),
        lifecycle_status=LifecycleStatus.ACTIVE,
        timeliness_status=TimelinessStatus.NOT_DUE,
        evidence_review_status=EvidenceReviewStatus.NO_EVIDENCE,
        ownership_status=OwnershipStatus.OWNED,
        assigned_team="Ward 1",
        assigned_user_id="user_1",
        audit_seq=3,
    )
    ctx = TransitionContext.from_obligation(ob)
    assert ctx.obligation_id == ob_id
    assert ctx.required_action_code == "TEST_CODE"
    assert ctx.patient_id == "PAT-CTX-1"
    assert ctx.assigned_team == "Ward 1"
    assert ctx.assigned_user_id == "user_1"
    assert ctx.audit_seq == 3
