"""End-to-end integration tests for the CCE Clinical Obligation Oversight Dashboard."""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from wsgiref.util import setup_testing_defaults

import pytest

from cce.dashboard.db import DashboardDatabase
from cce.dashboard.server import DashboardApp
from cce.models import Obligation
from cce.service import ObligationService


def _call_wsgi(
    app: DashboardApp,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query_string: str = "",
) -> tuple[str, dict[str, str], bytes]:
    raw_bytes = json.dumps(body).encode("utf-8") if body is not None else b""
    environ: dict[str, Any] = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["QUERY_STRING"] = query_string
    environ["CONTENT_LENGTH"] = str(len(raw_bytes))
    environ["CONTENT_TYPE"] = "application/json"
    environ["wsgi.input"] = io.BytesIO(raw_bytes)

    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> Any:
        captured["status"] = status
        captured["headers"] = {k.lower(): v for k, v in headers}
        return lambda _: None

    chunks = list(app(environ, start_response))
    return captured["status"], captured["headers"], b"".join(chunks)


@pytest.fixture()
def dashboard_app(tmp_path: Path) -> Iterator[DashboardApp]:
    db = DashboardDatabase(database_url=f"sqlite+pysqlite:///{tmp_path / 'dashboard.db'}")
    try:
        yield DashboardApp(db=db)
    finally:
        db.close()


def test_dashboard_seeds_all_benchmarks_and_serves_spa(dashboard_app: DashboardApp) -> None:
    status, headers, html_bytes = _call_wsgi(dashboard_app, "GET", "/")
    assert status.startswith("200")
    assert "text/html" in headers["content-type"]
    html = html_bytes.decode("utf-8")
    assert "Clinical Obligation Oversight Dashboard" in html
    assert '<dialog id="safety-gate-dialog"' in html

    css_status, css_headers, css_bytes = _call_wsgi(dashboard_app, "GET", "/static/styles.css")
    assert css_status.startswith("200")
    assert "text/css" in css_headers["content-type"]
    assert "overscroll-behavior: contain" in css_bytes.decode("utf-8")

    js_status, js_headers, _ = _call_wsgi(dashboard_app, "GET", "/static/app.js")
    assert js_status.startswith("200")
    assert "javascript" in js_headers["content-type"]

    trav_status, _, _ = _call_wsgi(dashboard_app, "GET", "/static/../db.py")
    assert trav_status.startswith("404")

    state_status, _, state_bytes = _call_wsgi(dashboard_app, "GET", "/api/state")
    assert state_status.startswith("200")
    state = json.loads(state_bytes.decode("utf-8"))
    assert state["telemetry"]["backend"] == "sqlite"
    assert state["telemetry"]["benchmarks_passed"] == 10
    assert state["telemetry"]["benchmarks_total"] == 10
    assert len(state["obligations"]) == 12
    assert state["metrics"]["pending_review_queue"] == 3


def test_dashboard_obligation_lifecycle_and_anti_gaming_guards(
    dashboard_app: DashboardApp,
) -> None:
    _, _, state_bytes = _call_wsgi(dashboard_app, "GET", "/api/state")
    state = json.loads(state_bytes.decode("utf-8"))

    # Locate unowned obligation (CCE-005) and claim it
    unowned = next(o for o in state["obligations"] if o["case_id"] == "CCE-005")
    assert unowned["ownership_status"] == "NO_OWNER"

    claim_status, _, claim_bytes = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{unowned['id']}/action",
        {"action": "claim", "actor_id": "sarah_jensen_rn"},
    )
    assert claim_status.startswith("200")
    claimed_state = json.loads(claim_bytes.decode("utf-8"))
    updated_005 = next(o for o in claimed_state["obligations"] if o["id"] == unowned["id"])
    assert updated_005["ownership_status"] == "OWNED"
    assert updated_005["assigned_user_id"] == "sarah_jensen_rn"

    # Empty rationale manual override MUST be rejected by CCE invariant guard (HTTP 422)
    guard_status, _, guard_bytes = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{unowned['id']}/action",
        {"action": "override", "reason_code": "RC-101", "rationale_text": "   "},
    )
    assert guard_status.startswith("422")
    guard_payload = json.loads(guard_bytes.decode("utf-8"))
    assert "rationale" in guard_payload["error"].lower()
    assert (
        guard_payload["state"]["metrics"]["blocked_anti_gaming"]
        > state["metrics"]["blocked_anti_gaming"]
    )

    # Action code mismatch on receive_report MUST return HTTP 422
    mismatch_status, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{unowned['id']}/action",
        {"action": "receive_report", "action_code": "INVALID_CODE_999"},
    )
    assert mismatch_status.startswith("422")

    # Valid workflow: receive_report -> document_review completes CCE-005
    rpt_status, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{unowned['id']}/action",
        {"action": "receive_report", "action_code": unowned["required_action_code"]},
    )
    assert rpt_status.startswith("200")

    rev_status, _, rev_bytes = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{unowned['id']}/action",
        {"action": "document_review", "review_notes": "Verified by bedside team."},
    )
    assert rev_status.startswith("200")
    rev_state = json.loads(rev_bytes.decode("utf-8"))
    completed_005 = next(o for o in rev_state["obligations"] if o["id"] == unowned["id"])
    assert completed_005["lifecycle_status"] == "COMPLETE"
    assert completed_005["evidence_review_status"] == "VERIFIED_COMPLETE"


def test_ambiguous_review_queue_adjudicate_clear_and_simulate(
    dashboard_app: DashboardApp,
) -> None:
    _, _, initial_bytes = _call_wsgi(dashboard_app, "GET", "/api/state")
    initial = json.loads(initial_bytes.decode("utf-8"))
    pending = initial["review_queue"]["pending"]
    assert len(pending) == 3

    # Clarify first item
    clarify_status, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/review-queue/{pending[0]['id']}/adjudicate",
        {"decision": "clarify", "rationale_text": "Verify hemolysis repeat sample."},
    )
    assert clarify_status.startswith("200")

    # Reject second item to triage pool (resolves review item & assigns triage pool)
    reject_status, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/review-queue/{pending[1]['id']}/adjudicate",
        {"decision": "reject", "rationale_text": "Wrong accession cross-ref."},
    )
    assert reject_status.startswith("200")

    # Confirm remaining pending items until All Caught Up
    _, _, mid_bytes = _call_wsgi(dashboard_app, "GET", "/api/state")
    mid_pending = json.loads(mid_bytes.decode("utf-8"))["review_queue"]["pending"]
    for item in mid_pending:
        conf_status, _, conf_bytes = _call_wsgi(
            dashboard_app,
            "POST",
            f"/api/review-queue/{item['id']}/adjudicate",
            {"decision": "confirm", "rationale_text": "Attested against chart."},
        )
        assert conf_status.startswith("200")
        conf_payload = json.loads(conf_bytes.decode("utf-8"))
        assert conf_payload["reconciliation"]["fhir_observation"]["resourceType"] == "Observation"

    _, _, empty_bytes = _call_wsgi(dashboard_app, "GET", "/api/state")
    empty_state = json.loads(empty_bytes.decode("utf-8"))
    assert empty_state["metrics"]["pending_review_queue"] == 0

    # Simulate incoming HL7 ingestion puts a fresh item back in queue
    sim_status, _, sim_bytes = _call_wsgi(dashboard_app, "POST", "/api/review-queue/simulate", {})
    assert sim_status.startswith("200")
    sim_state = json.loads(sim_bytes.decode("utf-8"))
    assert sim_state["metrics"]["pending_review_queue"] == 1


def test_scenario_runner_endpoints_and_reset(dashboard_app: DashboardApp) -> None:
    scen_status, _, scen_bytes = _call_wsgi(dashboard_app, "GET", "/api/scenarios")
    assert scen_status.startswith("200")
    assert len(json.loads(scen_bytes.decode("utf-8"))["scenarios"]) == 10

    run_status, _, run_bytes = _call_wsgi(
        dashboard_app,
        "POST",
        "/api/scenarios/run",
        {"case_id": "CCE-003"},
    )
    assert run_status.startswith("200")
    assert json.loads(run_bytes.decode("utf-8"))["telemetry"]["selected_case_id"] == "CCE-003"

    bad_status, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        "/api/scenarios/run",
        {"case_id": "CCE-999"},
    )
    assert bad_status.startswith("422")

    reset_status, _, reset_bytes = _call_wsgi(dashboard_app, "POST", "/api/reset", {})
    assert reset_status.startswith("200")
    reset_state = json.loads(reset_bytes.decode("utf-8"))
    assert reset_state["telemetry"]["selected_case_id"] == "ALL"
    assert reset_state["metrics"]["pending_review_queue"] == 3


def test_dashboard_additional_governance_actions_and_error_routes(
    dashboard_app: DashboardApp,
) -> None:
    from datetime import UTC, datetime, timedelta

    # Create a clean DRAFT obligation directly via ObligationService to exercise confirm/clock/override/supersede/cancel
    with dashboard_app.db.SessionFactory() as session:
        draft = ObligationService.create_obligation(
            session=session,
            patient_id="MRN-TEST-DRAFT",
            source_evidence={"case_id": "CCE-DRAFT", "source_note": "Outpatient MRI follow-up"},
            required_action_code="IMAGING_FOLLOWUP",
            required_action_description="Brain MRI w/ Contrast",
            due_window_end=datetime.now(UTC) + timedelta(days=3),
            actor_id="dr_test",
        )
        session.commit()
        draft_id = str(draft.id)

    for payload in [
        {"action": "confirm", "rationale_text": "Confirmed in test."},
        {"action": "clock_tick", "days": 4},
        {"action": "reassign", "assigned_user_id": "dr_julian_vance", "reason_code": "RC-102"},
        {"action": "supersede", "reason_code": "RC-104", "rationale_text": "Replaced by MRA."},
    ]:
        st, _, _ = _call_wsgi(
            dashboard_app,
            "POST",
            f"/api/obligations/{draft_id}/action",
            payload,
        )
        assert st.startswith("200")

    # Terminal superseded obligation rejects subsequent manual override cleanly (HTTP 422)
    term_override_status, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{draft_id}/action",
        {"action": "override", "reason_code": "RC-101", "rationale_text": "Equivalency signed."},
    )
    assert term_override_status.startswith("422")

    # Verify cancel and valid manual override on active seeded obligations
    _, _, st_bytes = _call_wsgi(dashboard_app, "GET", "/api/state")
    all_obls = json.loads(st_bytes.decode("utf-8"))["obligations"]
    active_002 = next(o for o in all_obls if o["case_id"] == "CCE-002")
    cancel_status, _, cancel_bytes = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{active_002['id']}/action",
        {"action": "cancel", "reason_code": "RC-105", "rationale_text": "Discontinued by team."},
    )
    assert cancel_status.startswith("200")
    assert any(
        o["id"] == active_002["id"] and o["lifecycle_status"] == "CANCELLED"
        for o in json.loads(cancel_bytes.decode("utf-8"))["obligations"]
    )

    active_003 = next(o for o in all_obls if o["case_id"] == "CCE-003")
    valid_ovr_status, _, valid_ovr_bytes = _call_wsgi(
        dashboard_app,
        "POST",
        f"/api/obligations/{active_003['id']}/action",
        {
            "action": "override",
            "reason_code": "RC-101",
            "rationale_text": "Reviewed externally in clinic.",
        },
    )
    assert valid_ovr_status.startswith("200")
    assert any(
        o["id"] == active_003["id"] and o["lifecycle_status"] == "COMPLETE"
        for o in json.loads(valid_ovr_bytes.decode("utf-8"))["obligations"]
    )

    active_obl = active_002

    # Error handling coverage (404, 400, unknown decision)
    s404, _, _ = _call_wsgi(dashboard_app, "GET", "/api/nonexistent")
    assert s404.startswith("404")
    s400, _, _ = _call_wsgi(
        dashboard_app, "POST", f"/api/obligations/{active_obl['id']}/action", {}
    )
    assert s400.startswith("400")
    smiss, _, _ = _call_wsgi(
        dashboard_app,
        "POST",
        "/api/obligations/00000000-0000-0000-0000-000000000000/action",
        {"action": "confirm"},
    )
    assert smiss.startswith("404")

    # PostgreSQL unreachable URL falls back cleanly to SQLite
    fallback_db = DashboardDatabase(
        database_url="postgresql+psycopg://bad:bad@127.0.0.1:59999/nope"
    )
    try:
        assert fallback_db.backend_name == "sqlite"
        assert fallback_db.fallback_reason is not None
        assert len(fallback_db.benchmark_results) == 10
        with fallback_db.SessionFactory() as s:
            assert s.get(Obligation, uuid.UUID(active_obl["id"])) is None
    finally:
        fallback_db.close()
