const state = {
  data: null,
  activeView: "oversight",
  ledgerFilter: "all",
  govFilter: "ALL",
  searchQuery: "",
  selectedObligationId: null,
  selectedBenchmarkId: "CCE-001",
  queueIndex: 0,
  lastReconciliation: null,
  pendingToasts: [],
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function badgeToneForDimension(dim, val) {
  if (dim === "lifecycle") {
    if (val === "COMPLETE") return "tone-teal";
    if (val === "ACTIVE" || val === "CONFIRMED") return "tone-primary";
    if (val === "CANCELLED" || val === "INVALID" || val === "SUPERSEDED") return "tone-neutral";
    return "tone-warning";
  }
  if (dim === "timeliness") {
    if (val === "OVERDUE") return "tone-danger";
    if (val === "DUE") return "tone-warning";
    if (val === "NOT_APPLICABLE") return "tone-neutral";
    return "tone-teal";
  }
  if (dim === "evidence") {
    if (val === "VERIFIED_COMPLETE") return "tone-teal";
    if (val === "AMBIGUOUS_REVIEW_EVIDENCE" || val === "AWAITING_REVIEW_EVIDENCE") return "tone-warning";
    if (val === "ACTION_EVIDENCE_RECEIVED") return "tone-primary";
    return "tone-neutral";
  }
  if (dim === "ownership") {
    return val === "NO_OWNER" ? "tone-danger" : "tone-teal";
  }
  return "tone-neutral";
}

/* ============================================================================
   Accessible Persistent Toast Notifications (popover="manual")
   ============================================================================ */
function flushPendingToasts() {
  if (document.querySelector("dialog:modal")) return;
  while (state.pendingToasts.length > 0) {
    const next = state.pendingToasts.shift();
    displayToast(next.title, next.message, next.variant);
  }
}

function showToast(title, message, variant = "info") {
  if (document.querySelector("dialog:modal")) {
    state.pendingToasts.push({ title, message, variant });
    return;
  }
  displayToast(title, message, variant);
}

function displayToast(title, message, variant = "info") {
  const region = document.getElementById("toast-region");
  const live = document.getElementById("toast-live");
  if (!region) return;

  if (live) {
    live.textContent = `${title}: ${message}`;
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${variant}`;
  toast.setAttribute("popover", "manual");

  toast.innerHTML = `
    <div class="toast-row">
      <div>
        <div class="toast-title">${escapeHtml(title)}</div>
        <div class="toast-body">${escapeHtml(message)}</div>
      </div>
      <button type="button" class="toast-close" aria-label="Close notification">✕</button>
    </div>
  `;

  region.appendChild(toast);

  const dismiss = () => {
    if (toast.isConnected) {
      if (typeof toast.hidePopover === "function") {
        try {
          toast.hidePopover();
        } catch {
          /* ignore if already hidden */
        }
      }
      toast.remove();
    }
  };

  let timerId = null;
  const scheduleDismiss = () => {
    window.clearTimeout(timerId);
    timerId = window.setTimeout(() => {
      if (toast.matches(":hover") || toast.contains(document.activeElement)) {
        scheduleDismiss();
        return;
      }
      dismiss();
    }, 5000);
  };

  const closeBtn = toast.querySelector(".toast-close");
  closeBtn?.addEventListener("click", dismiss);
  toast.addEventListener("mouseenter", () => window.clearTimeout(timerId));
  toast.addEventListener("mouseleave", scheduleDismiss);
  toast.addEventListener("focusin", () => window.clearTimeout(timerId));
  toast.addEventListener("focusout", scheduleDismiss);

  if (typeof toast.showPopover === "function") {
    toast.showPopover();
  }
  scheduleDismiss();
}

/* ============================================================================
   Native <dialog> Setup (Strict modern-web-guidance)
   ============================================================================ */
function setupDialogs() {
  const supportsClosedBy = "closedBy" in HTMLDialogElement.prototype;
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("close", () => {
      dialog.returnValue = "";
      if (!document.querySelector("dialog:modal")) {
        flushPendingToasts();
      }
    });

    if (!supportsClosedBy) {
      dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const inside =
          event.clientX >= rect.left &&
          event.clientX <= rect.right &&
          event.clientY >= rect.top &&
          event.clientY <= rect.bottom;
        if (!inside) {
          dialog.close("backdrop");
        }
      });
    }
  });
}

/* ============================================================================
   API Helpers
   ============================================================================ */
async function apiRequest(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await res.json();
  if (!res.ok) {
    if (payload.state) {
      state.data = payload.state;
      renderAll();
    }
    const err = new Error(payload.error || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  state.data = payload;
  return payload;
}

async function loadState(caseId = null) {
  const qs = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
  await apiRequest(`/api/state${qs}`);
  ensureValidSelections();
  renderAll();
}

function ensureValidSelections() {
  const obls = state.data?.obligations || [];
  if (obls.length > 0 && !obls.some((o) => o.id === state.selectedObligationId)) {
    state.selectedObligationId = obls[0].id;
  }
  const pending = state.data?.review_queue?.pending || [];
  if (state.queueIndex >= pending.length) {
    state.queueIndex = Math.max(0, pending.length - 1);
  }
  const scenarios = state.data?.scenarios || [];
  if (scenarios.length > 0 && !scenarios.some((s) => s.case_id === state.selectedBenchmarkId)) {
    state.selectedBenchmarkId = scenarios[0].case_id;
  }
}

/* ============================================================================
   Navigation & Header Telemetry
   ============================================================================ */
function switchView(viewName) {
  state.activeView = viewName;
  const views = ["oversight", "queue", "governance", "audit"];
  views.forEach((v) => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.hidden = v !== viewName;
  });
  document.querySelectorAll(".nav-link").forEach((btn) => {
    const active = btn.dataset.view === viewName;
    btn.classList.toggle("is-active", active);
    if (active) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
  });
}

function renderTelemetryHeader() {
  if (!state.data) return;
  const { telemetry, metrics } = state.data;

  const backendBadge = document.getElementById("backend-badge");
  if (backendBadge) {
    const engineLabel = telemetry.backend === "postgresql" ? "PostgreSQL" : "SQLite Fallback";
    backendBadge.textContent = `Mercy General — Acute Care Division • ${engineLabel}`;
  }

  const syncPill = document.getElementById("sync-status-pill");
  if (syncPill) {
    syncPill.textContent = `${telemetry.benchmarks_passed}/${telemetry.benchmarks_total} Benchmarks Synced`;
  }

  const queueBadge = document.getElementById("nav-queue-badge");
  if (queueBadge) {
    queueBadge.textContent = `${metrics.pending_review_queue} Pending`;
    queueBadge.className =
      metrics.pending_review_queue === 0
        ? "nav-count-badge nav-count-pass"
        : "nav-count-badge";
  }

  const auditBadge = document.getElementById("nav-audit-badge");
  if (auditBadge) {
    auditBadge.textContent = `${telemetry.benchmarks_passed}/${telemetry.benchmarks_total}`;
  }

  const scenarioSelect = document.getElementById("scenario-select");
  if (scenarioSelect && telemetry.selected_case_id) {
    scenarioSelect.value = telemetry.selected_case_id;
  }
}

/* ============================================================================
   VIEW 1: OVERSIGHT DASHBOARD
   ============================================================================ */
function getFilteredObligations() {
  const obls = state.data?.obligations || [];
  const q = state.searchQuery.trim().toLowerCase();
  const selCase = state.data?.telemetry?.selected_case_id;

  return obls.filter((o) => {
    if (selCase && selCase !== "ALL" && o.case_id !== selCase) return false;
    if (q) {
      const hay =
        `${o.patient_name} ${o.mrn} ${o.case_id} ${o.required_action_code} ${o.required_action_description} ${o.assigned_user_id || ""} ${o.assigned_team || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }

    if (state.ledgerFilter === "active") return !o.is_terminal;
    if (state.ledgerFilter === "overdue") return o.timeliness_status === "OVERDUE";
    if (state.ledgerFilter === "unreviewed") {
      return ["ACTION_EVIDENCE_RECEIVED", "AWAITING_REVIEW_EVIDENCE", "AMBIGUOUS_REVIEW_EVIDENCE"].includes(
        o.evidence_review_status
      );
    }
    if (state.ledgerFilter === "no_owner") return o.ownership_status === "NO_OWNER" && !o.is_terminal;
    if (state.ledgerFilter === "terminal") return o.is_terminal;
    return true;
  });
}

function renderOversightView() {
  if (!state.data) return;
  const { metrics } = state.data;

  document.getElementById("kpi-active").textContent = metrics.active_obligations;
  document.getElementById("kpi-overdue").textContent = metrics.overdue_actions;
  document.getElementById("kpi-unreviewed").textContent = metrics.unreviewed_results;
  document.getElementById("kpi-unassigned").textContent = metrics.unassigned_owners;

  const filtered = getFilteredObligations();
  document.getElementById("ledger-count-label").textContent =
    `Showing ${filtered.length} of ${state.data.obligations.length} obligations`;

  const tbody = document.getElementById("obligations-tbody");
  tbody.innerHTML = "";

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4">No obligations match the current filter criteria.</td></tr>`;
  } else {
    filtered.forEach((o) => {
      const tr = document.createElement("tr");
      if (o.id === state.selectedObligationId) tr.classList.add("is-selected");
      tr.dataset.obligationId = o.id;

      const quickButtons = [];
      if (o.lifecycle_status === "DRAFT") {
        quickButtons.push(`<button type="button" class="btn btn-xs btn-primary" data-obl-action="confirm" data-obl-id="${o.id}">Confirm</button>`);
      }
      if (o.ownership_status === "NO_OWNER" && !o.is_terminal) {
        quickButtons.push(`<button type="button" class="btn btn-xs btn-tonal" data-obl-action="claim" data-obl-id="${o.id}">Claim</button>`);
      }
      if (!o.is_terminal && o.evidence_review_status === "NO_EVIDENCE") {
        quickButtons.push(`<button type="button" class="btn btn-xs btn-secondary" data-obl-action="receive_report" data-obl-id="${o.id}">Receive Lab</button>`);
      }
      if (
        !o.is_terminal &&
        ["ACTION_EVIDENCE_RECEIVED", "AWAITING_REVIEW_EVIDENCE", "AMBIGUOUS_REVIEW_EVIDENCE"].includes(o.evidence_review_status)
      ) {
        quickButtons.push(`<button type="button" class="btn btn-xs btn-teal" data-obl-action="document_review" data-obl-id="${o.id}">Verify Review</button>`);
      }
      quickButtons.push(`<button type="button" class="btn btn-xs btn-secondary" data-open-gate="${o.id}">Safety Gate</button>`);

      tr.innerHTML = `
        <th scope="row">
          <div class="patient-cell-title">${escapeHtml(o.patient_name)} <span class="mono-tag">${escapeHtml(o.case_id)}</span></div>
          <div class="patient-cell-meta">${escapeHtml(o.mrn)} • ${escapeHtml(o.demographics)}</div>
          <div class="action-desc-line">${escapeHtml(o.required_action_description)}</div>
          <div class="patient-cell-meta"><span class="mono-tag">${escapeHtml(o.required_action_code)}</span> • ${escapeHtml(o.headline)}</div>
        </th>
        <td data-label="4-Dimension Verification State">
          <div class="state-cluster">
            <span class="dim-badge ${badgeToneForDimension("lifecycle", o.lifecycle_status)}">L: ${escapeHtml(o.lifecycle_status)}</span>
            <span class="dim-badge ${badgeToneForDimension("timeliness", o.timeliness_status)}">T: ${escapeHtml(o.timeliness_status)}</span>
            <span class="dim-badge ${badgeToneForDimension("evidence", o.evidence_review_status)}">E: ${escapeHtml(o.evidence_review_status)}</span>
            <span class="dim-badge ${badgeToneForDimension("ownership", o.ownership_status)}">O: ${escapeHtml(o.ownership_status)}</span>
          </div>
        </td>
        <td data-label="Ownership & SLA">
          <div><strong>${escapeHtml(o.assigned_user_id || o.assigned_team || "Unassigned Pool")}</strong></div>
          <div class="patient-cell-meta">${escapeHtml(o.assigned_team || "No Team Assigned")}</div>
          <div class="patient-cell-meta tabular-nums">Due: ${formatDateTime(o.due_window_end)}</div>
        </td>
        <td data-label="Oversight Actions">
          <div class="row-actions">${quickButtons.join("")}</div>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  renderInspectorSidebar();
}

function renderInspectorSidebar() {
  const obls = state.data?.obligations || [];
  const selected = obls.find((o) => o.id === state.selectedObligationId);
  const heading = document.getElementById("inspector-heading");
  const tag = document.getElementById("inspector-case-tag");
  const body = document.getElementById("inspector-body");

  if (!selected) {
    heading.textContent = "Select an Obligation";
    tag.textContent = "—";
    body.innerHTML = `<p class="card-sub">Select a ledger row to inspect 4D dimensions and dispatch domain events.</p>`;
    return;
  }

  heading.textContent = selected.patient_name;
  tag.textContent = `${selected.case_id} • ${selected.order_ref}`;

  const auditItemsHtml = (selected.audit_logs || [])
    .slice()
    .reverse()
    .map(
      (log) => `
      <div class="audit-item">
        <div class="audit-item-top">
          <span>#${log.audit_seq} • ${escapeHtml(log.event_type)}</span>
          <span class="mono-tag">${escapeHtml(log.reason_code)}</span>
        </div>
        <div>${escapeHtml(log.rationale_text)}</div>
        <div class="audit-item-meta">${escapeHtml(log.actor_id)} • ${formatDateTime(log.created_at)}</div>
      </div>
    `
    )
    .join("");

  body.innerHTML = `
    <div class="inspector-meta-grid">
      <div><span class="meta-kv-label">Patient / MRN</span><span class="meta-kv-val">${escapeHtml(selected.mrn)}</span></div>
      <div><span class="meta-kv-label">Action Code</span><span class="meta-kv-val">${escapeHtml(selected.required_action_code)}</span></div>
      <div><span class="meta-kv-label">Assigned Owner</span><span class="meta-kv-val">${escapeHtml(selected.assigned_user_id || selected.assigned_team || "NO_OWNER")}</span></div>
      <div><span class="meta-kv-label">Origin Feed</span><span class="meta-kv-val">${escapeHtml(selected.origin)}</span></div>
    </div>

    <div class="headline-callout ${selected.should_flag ? "is-flagged" : ""}">
      <div>Computed Headline: <strong>${escapeHtml(selected.headline)}</strong></div>
      <div class="patient-cell-meta">Attention Flag: ${selected.should_flag ? "FLAGGED FOR OVERSIGHT" : "Nominal"} • Source Note: ${escapeHtml(selected.source_note || "Standard clinical order")}</div>
    </div>

    <div class="state-cluster" style="margin-bottom: 14px;">
      <span class="dim-badge ${badgeToneForDimension("lifecycle", selected.lifecycle_status)}">${escapeHtml(selected.lifecycle_status)}</span>
      <span class="dim-badge ${badgeToneForDimension("timeliness", selected.timeliness_status)}">${escapeHtml(selected.timeliness_status)}</span>
      <span class="dim-badge ${badgeToneForDimension("evidence", selected.evidence_review_status)}">${escapeHtml(selected.evidence_review_status)}</span>
      <span class="dim-badge ${badgeToneForDimension("ownership", selected.ownership_status)}">${escapeHtml(selected.ownership_status)}</span>
    </div>

    <div class="inspector-action-bar">
      ${selected.lifecycle_status === "DRAFT" ? `<button type="button" class="btn btn-sm btn-primary" data-obl-action="confirm" data-obl-id="${selected.id}">Confirm Draft</button>` : ""}
      ${!selected.is_terminal ? `<button type="button" class="btn btn-sm btn-secondary" data-obl-action="receive_report" data-obl-id="${selected.id}">Receive Lab</button>` : ""}
      ${!selected.is_terminal && selected.evidence_review_status !== "NO_EVIDENCE" ? `<button type="button" class="btn btn-sm btn-teal" data-obl-action="document_review" data-obl-id="${selected.id}">Document Review</button>` : ""}
      ${!selected.is_terminal ? `<button type="button" class="btn btn-sm btn-tonal" data-obl-action="clock_tick" data-obl-id="${selected.id}">Advance Clock (+2d)</button>` : ""}
      ${!selected.is_terminal ? `<button type="button" class="btn btn-sm btn-danger-outline" data-obl-action="mismatch_test" data-obl-id="${selected.id}">Test Mismatch Reject</button>` : ""}
      <button type="button" class="btn btn-sm btn-secondary" data-open-gate="${selected.id}">Safety Gate</button>
      <button type="button" class="btn btn-sm btn-secondary" data-open-audit="${selected.id}">Full Audit (${selected.audit_count})</button>
    </div>

    <div>
      <h3 class="field-label" style="margin-bottom: 8px;">Audit Provenance Stream</h3>
      <div class="audit-stream">${auditItemsHtml || '<div class="card-sub">No audit records yet.</div>'}</div>
    </div>
  `;
}

/* ============================================================================
   VIEW 2: AMBIGUOUS REVIEW QUEUE (Screens 2, 3, and 4)
   ============================================================================ */
function renderQueueView() {
  if (!state.data) return;
  const { pending, recently_adjudicated } = state.data.review_queue;
  const { metrics } = state.data;

  const banner = document.getElementById("reconciliation-banner");
  if (state.lastReconciliation) {
    banner.hidden = false;
    document.getElementById("recon-title").textContent =
      `Obligation ${state.lastReconciliation.case_id} (${state.lastReconciliation.patient_name}) Successfully Reconciled`;
    document.getElementById("recon-sub").textContent =
      `Decision: ${state.lastReconciliation.decision} • Audit SHA-256: ${state.lastReconciliation.audit_hash} • Verified by ${state.lastReconciliation.actor_id}`;
  } else {
    banner.hidden = true;
  }

  const posPill = document.getElementById("queue-position-pill");
  const prevBtn = document.getElementById("btn-queue-prev");
  const nextBtn = document.getElementById("btn-queue-next");
  posPill.textContent = pending.length > 0 ? `Queue: ${state.queueIndex + 1} of ${pending.length}` : "Queue: 0 of 0";
  prevBtn.disabled = pending.length <= 1;
  nextBtn.disabled = pending.length <= 1;

  const activeWrap = document.getElementById("queue-active-workspace");
  const emptyWrap = document.getElementById("queue-empty-workspace");

  if (pending.length === 0) {
    activeWrap.hidden = true;
    emptyWrap.hidden = false;
    renderAllCaughtUp(emptyWrap, metrics, recently_adjudicated);
    return;
  }

  emptyWrap.hidden = true;
  activeWrap.hidden = false;
  const item = pending[state.queueIndex] || pending[0];
  const pct = Math.round((item.confidence_score || 0.75) * 100);
  const dashArray = 163.36;
  const dashOffset = dashArray - (dashArray * pct) / 100;

  const alignmentRows = (item.alignment || [])
    .map((row) => {
      const tone =
        row.status === "EXACT" || row.status === "MATCH"
          ? "tone-teal"
          : row.status === "WARNING" || row.status === "PARTIAL"
            ? "tone-warning"
            : "tone-danger";
      return `
        <tr>
          <th scope="row">${escapeHtml(row.field)}</th>
          <td data-label="Match Status"><span class="dim-badge ${tone}">${escapeHtml(row.status)}</span></td>
          <td data-label="Verification Detail">${escapeHtml(row.detail)}</td>
        </tr>
      `;
    })
    .join("");

  activeWrap.innerHTML = `
    <div class="card-surface queue-hero-card">
      <div>
        <div class="state-cluster" style="margin-bottom: 6px;">
          <span class="dim-badge tone-warning">${escapeHtml(item.evidence_review_status)}</span>
          <span class="mono-tag">${escapeHtml(item.case_id)}</span>
          <span class="mono-tag">${escapeHtml(item.order_ref)}</span>
        </div>
        <h2 class="card-title" style="font-size: 20px;">${escapeHtml(item.patient_name)} • ${escapeHtml(item.mrn)}</h2>
        <div class="card-sub">${escapeHtml(item.demographics)} • Ordered by ${escapeHtml(item.clinician)} • SLA Due: ${formatDateTime(item.due_at)}</div>
      </div>

      <div class="confidence-gauge-box">
        <svg class="gauge-svg" viewBox="0 0 64 64" aria-hidden="true">
          <circle class="gauge-track" cx="32" cy="32" r="26"></circle>
          <circle class="gauge-progress" cx="32" cy="32" r="26" stroke-dasharray="${dashArray}" stroke-dashoffset="${dashOffset}"></circle>
        </svg>
        <div>
          <div class="kpi-label">Heuristic Match Index</div>
          <div class="kpi-value tabular-nums" style="font-size: 24px;">${pct}%</div>
          <div class="card-sub">Threshold ≥ 92% for auto-verify</div>
        </div>
      </div>
    </div>

    <div class="comparison-grid">
      <section class="card-surface" aria-labelledby="target-obl-title">
        <span class="eyebrow">Expected Clinical Order</span>
        <h3 id="target-obl-title" class="card-title">Target Clinical Obligation</h3>
        <div class="inspector-meta-grid" style="margin-top: 12px;">
          <div><span class="meta-kv-label">Action Description</span><span class="meta-kv-val">${escapeHtml(item.required_action_description)}</span></div>
          <div><span class="meta-kv-label">Action Code</span><span class="meta-kv-val">${escapeHtml(item.required_action_code)}</span></div>
          <div><span class="meta-kv-label">Order Reference</span><span class="meta-kv-val">${escapeHtml(item.order_ref)}</span></div>
          <div><span class="meta-kv-label">Assigned Reviewer</span><span class="meta-kv-val">${escapeHtml(item.assigned_reviewer_id || "Sarah Jensen, RN")}</span></div>
        </div>
        <p class="card-sub"><strong>Source Clinical Note:</strong> ${escapeHtml(item.source_note || "EHR structured clinical order")}</p>
      </section>

      <section class="card-surface" aria-labelledby="hl7-snippet-label">
        <span class="eyebrow">Ingested External Feed</span>
        <h3 id="hl7-snippet-label" class="card-title">External Lab / HL7v2 ORU^R01 Snippet</h3>
        <div class="discrepancy-callout" style="margin-top: 10px;">
          <strong>Flagged Discrepancy:</strong> ${escapeHtml(item.discrepancy)}
        </div>
        <pre class="code-viewer" role="region" aria-labelledby="hl7-snippet-label" tabindex="0"><code>${escapeHtml(item.raw_hl7)}</code></pre>
      </section>
    </div>

    <div class="card-surface">
      <div class="ledger-toolbar">
        <div>
          <h3 id="alignment-heading" class="card-title">Clinical Entity Alignment Matrix</h3>
          <p class="card-sub">Automated token &amp; patient identity cross-validation</p>
        </div>
      </div>
      <div class="table-wrapper" tabindex="0" role="region" aria-labelledby="alignment-heading">
        <table class="data-table">
          <thead>
            <tr>
              <th scope="col">Clinical Entity</th>
              <th scope="col">Alignment</th>
              <th scope="col">Observed Evidence</th>
            </tr>
          </thead>
          <tbody>${alignmentRows}</tbody>
        </table>
      </div>
    </div>

    <div class="adjudication-bar">
      <div class="adjudication-input-wrap">
        <label for="adjudication-rationale" class="sr-only">Clinical adjudication note</label>
        <input
          type="text"
          id="adjudication-rationale"
          class="text-input"
          placeholder="Optional clinician verification or triage note (audited to obligation_audit_logs)..."
        />
      </div>
      <div class="adjudication-buttons">
        <button type="button" class="btn btn-secondary" data-adjudicate="clarify" data-item-id="${item.id}">
          Request Manual Clarification
        </button>
        <button type="button" class="btn btn-danger-outline" data-adjudicate="reject" data-item-id="${item.id}">
          Reject Match (Route to Triage Pool)
        </button>
        <button type="button" class="btn btn-teal" data-adjudicate="confirm" data-item-id="${item.id}">
          Confirm Match &amp; Close Obligation
        </button>
      </div>
    </div>
  `;
}

function renderAllCaughtUp(container, metrics, history) {
  const rows = history
    .map(
      (h) => `
      <tr>
        <th scope="row">${escapeHtml(h.patient_name)} <span class="mono-tag">${escapeHtml(h.case_id)}</span></th>
        <td data-label="Decision"><span class="dim-badge tone-teal">${escapeHtml(h.decision)}</span></td>
        <td data-label="Actor & Timestamp">${escapeHtml(h.actor_id)} • ${formatDateTime(h.resolved_at)}</td>
        <td data-label="Signed FHIR"><button type="button" class="btn btn-xs btn-secondary" data-view-history-fhir="${escapeHtml(h.id)}">View Signed FHIR</button></td>
      </tr>
    `
    )
    .join("");

  container.innerHTML = `
    <div class="card-surface caught-up-hero">
      <div class="caught-up-emblem" aria-hidden="true">✓</div>
      <h2 class="page-title" style="font-size: 22px;">Review Queue Cleared — No Ambiguous Ingestions Pending</h2>
      <p class="page-desc" style="max-width: 620px; margin: 8px auto 18px;">
        All incoming HL7v2 ORU^R01 and FHIR R4 diagnostic snippets have been reconciled against active obligations with verified audit provenance.
      </p>
      <button type="button" class="btn btn-primary" id="btn-empty-simulate">
        Simulate Incoming Ambiguous Ingestion
      </button>
    </div>

    <div class="kpi-grid" style="margin-bottom: 18px;">
      <div class="kpi-card"><span class="kpi-label">Items Reviewed Today</span><span class="kpi-value tabular-nums">${metrics.resolved_today}</span><span class="kpi-sub">Adjudicated with human sign-off</span></div>
      <div class="kpi-card kpi-warning"><span class="kpi-label">Pending Backlog</span><span class="kpi-value tabular-nums">0</span><span class="kpi-sub">Zero unverified ambiguous matches</span></div>
      <div class="kpi-card kpi-neutral"><span class="kpi-label">HL7 / FHIR Listeners</span><span class="kpi-value">ACTIVE</span><span class="kpi-sub">Port 2575 MLLP &amp; FHIR Subscription</span></div>
      <div class="kpi-card kpi-danger"><span class="kpi-label">Anti-Gaming Blocks</span><span class="kpi-value tabular-nums">${metrics.blocked_anti_gaming}</span><span class="kpi-sub">Invalid closures intercepted</span></div>
    </div>

    <div class="card-surface">
      <div class="ledger-toolbar">
        <div>
          <h3 id="recent-adj-title" class="card-title">Recently Adjudicated Today</h3>
          <p class="card-sub">Signed FHIR R4 Observations committed to clinical record</p>
        </div>
      </div>
      <div class="table-wrapper" tabindex="0" role="region" aria-labelledby="recent-adj-title">
        <table class="data-table">
          <thead>
            <tr>
              <th scope="col">Patient &amp; Case</th>
              <th scope="col">Decision</th>
              <th scope="col">Reviewer &amp; Time</th>
              <th scope="col">FHIR Payload</th>
            </tr>
          </thead>
          <tbody>${rows || '<tr><td colspan="4">Adjudications performed in this session will appear here.</td></tr>'}</tbody>
        </table>
      </div>
    </div>
  `;
}

/* ============================================================================
   VIEW 3: ATTRIBUTION & OVERRIDE LOG (Screen 5)
   ============================================================================ */
function renderGovernanceView() {
  if (!state.data) return;
  const { governance_logs, anti_gaming_rejections, metrics } = state.data;

  document.getElementById("gov-override-count").textContent = metrics.override_volume_24h;
  document.getElementById("gov-blocked-count").textContent = metrics.blocked_anti_gaming;

  const filtered = governance_logs.filter((g) => {
    if (state.govFilter === "ALL") return true;
    if (state.govFilter === "SUPERSEDED_CANCELLED") {
      return g.event_type === "SUPERSEDED" || g.event_type === "CANCELLATION";
    }
    return g.event_type === state.govFilter;
  });

  const tbody = document.getElementById("governance-tbody");
  tbody.innerHTML =
    filtered
      .map(
        (g) => `
      <tr>
        <th scope="row">
          <div>${escapeHtml(g.patient_name)} <span class="mono-tag">${escapeHtml(g.case_id)}</span></div>
          <div class="patient-cell-meta">Audit Seq #${g.audit_seq}</div>
        </th>
        <td data-label="Event & Reason">
          <span class="dim-badge tone-primary">${escapeHtml(g.event_type)}</span>
          <div class="patient-cell-meta"><span class="mono-tag">${escapeHtml(g.reason_code)}</span></div>
        </td>
        <td data-label="Actor"><strong>${escapeHtml(g.actor_id)}</strong></td>
        <td data-label="Transition">
          <span class="mono-tag">${escapeHtml(g.previous_state?.lifecycle_status || "?")}</span>
          →
          <span class="mono-tag">${escapeHtml(g.new_state?.lifecycle_status || "?")}</span>
        </td>
        <td data-label="Rationale & Timestamp">
          <div>${escapeHtml(g.rationale_text)}</div>
          <div class="patient-cell-meta">${formatDateTime(g.created_at)}</div>
        </td>
      </tr>
    `
      )
      .join("") || '<tr><td colspan="5">No governance events match the selected filter.</td></tr>';

  const rejContainer = document.getElementById("anti-gaming-list");
  rejContainer.innerHTML =
    anti_gaming_rejections
      .map(
        (r) => `
      <div class="rejection-item">
        <div><strong>BLOCKED ${escapeHtml(r.event)}</strong> • ${escapeHtml(r.patient_name)} <span class="mono-tag">${escapeHtml(r.case_id)}</span></div>
        <div style="margin-top: 3px;">${escapeHtml(r.reason)}</div>
        <div class="patient-cell-meta">Actor: ${escapeHtml(r.actor_id)} • ${formatDateTime(r.timestamp)}</div>
      </div>
    `
      )
      .join("") || '<p class="card-sub">No blocked attempts recorded yet. Try "Test Empty Rationale Guard (CCE-010)" inside the Clinical Safety Gate.</p>';
}

/* ============================================================================
   VIEW 4: COMPLIANCE AUDIT & TIME MACHINE
   ============================================================================ */
function renderAuditView() {
  if (!state.data) return;
  const scenarios = state.data.scenarios || [];
  const tbody = document.getElementById("benchmarks-tbody");

  tbody.innerHTML = scenarios
    .map(
      (s) => `
      <tr class="${s.case_id === state.selectedBenchmarkId ? "is-selected" : ""}" data-benchmark-id="${escapeHtml(s.case_id)}">
        <th scope="row">
          <div><span class="mono-tag">${escapeHtml(s.case_id)}</span> ${escapeHtml(s.title)}</div>
          <div class="patient-cell-meta">${escapeHtml(s.patient_name)} • ${escapeHtml(s.benchmark_role)}</div>
        </th>
        <td data-label="Expected 4D"><span class="mono-tag">${escapeHtml(s.expected.lifecycle)} / ${escapeHtml(s.expected.timeliness)} / ${escapeHtml(s.expected.evidence_review)} / ${escapeHtml(s.expected.ownership)}</span></td>
        <td data-label="Actual 4D"><span class="mono-tag">${escapeHtml(s.actual.lifecycle)} / ${escapeHtml(s.actual.timeliness)} / ${escapeHtml(s.actual.evidence_review)} / ${escapeHtml(s.actual.ownership)}</span></td>
        <td data-label="Audit / Flag" class="tabular-nums">${s.audit_count} logs • Flag=${s.actual.should_flag ? "YES" : "NO"}</td>
        <td data-label="Status"><span class="dim-badge ${s.passed ? "tone-teal" : "tone-danger"}">${s.passed ? "PASS" : "FAIL"}</span></td>
      </tr>
    `
    )
    .join("");

  const activeBench = scenarios.find((s) => s.case_id === state.selectedBenchmarkId) || scenarios[0];
  if (!activeBench) return;

  document.getElementById("timeline-heading").textContent = activeBench.title;
  document.getElementById("timeline-case-tag").textContent = activeBench.case_id;

  const stepsHtml = (activeBench.steps || [])
    .map(
      (st) => `
      <div class="timeline-step">
        <div class="audit-item-top">
          <strong>Day ${st.day} • ${escapeHtml(st.headline)}</strong>
          <span class="mono-tag">${escapeHtml(st.state?.lifecycle || "")} / ${escapeHtml(st.state?.timeliness || "")}</span>
        </div>
        <div class="patient-cell-meta" style="margin-top: 4px;">
          Evidence: <strong>${escapeHtml(st.state?.evidence_review || "")}</strong> • Ownership: <strong>${escapeHtml(st.state?.ownership || "")}</strong>
        </div>
        ${
          st.ingested_events?.length
            ? `<div class="patient-cell-meta">Events: ${st.ingested_events.map((e) => escapeHtml(e.event_token || e.event_type || "EVENT")).join(", ")}</div>`
            : ""
        }
        ${
          st.rejections?.length
            ? `<div style="color: var(--error); font-weight: 700; margin-top: 3px;">Blocked: ${escapeHtml(st.rejections[0].error || "Invariant Violation")}</div>`
            : ""
        }
      </div>
    `
    )
    .join("");

  document.getElementById("timeline-body").innerHTML = `
    <div class="headline-callout">
      <div><strong>Test Focus:</strong> ${escapeHtml(activeBench.engine_test_focus)}</div>
      <div class="patient-cell-meta" style="margin-top: 4px;">${escapeHtml(activeBench.expected_system_behaviour)}</div>
    </div>
    ${stepsHtml}
  `;
}

function renderAll() {
  renderTelemetryHeader();
  renderOversightView();
  renderQueueView();
  renderGovernanceView();
  renderAuditView();
}

/* ============================================================================
   ACTIONS & MODALS
   ============================================================================ */
async function handleObligationAction(oblId, action) {
  let payload = { action };
  if (action === "mismatch_test") {
    payload = { action: "receive_report", action_code: "WRONG_LOINC_CODE_999", report_id: "RPT-MISMATCH" };
  }
  try {
    await apiRequest(`/api/obligations/${encodeURIComponent(oblId)}/action`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    ensureValidSelections();
    renderAll();
    showToast("CCE Domain Event Committed", `Executed '${action}' cleanly via ObligationService.`, "success");
  } catch (err) {
    showToast("CCE Invariant Guard Triggered", err.message, "error");
  }
}

async function handleAdjudicate(itemId, decision) {
  const input = document.getElementById("adjudication-rationale");
  const rationale_text = input ? input.value.trim() : "";
  try {
    const res = await apiRequest(`/api/review-queue/${encodeURIComponent(itemId)}/adjudicate`, {
      method: "POST",
      body: JSON.stringify({ decision, rationale_text }),
    });
    if (res.reconciliation) {
      state.lastReconciliation = res.reconciliation;
    }
    ensureValidSelections();
    renderAll();
    showToast(
      "Adjudication Recorded",
      `Queue decision '${decision}' verified and sealed in obligation_audit_logs.`,
      "success"
    );
  } catch (err) {
    showToast("Adjudication Blocked", err.message, "error");
  }
}

function openSafetyGateDialog(preferredOblId = null) {
  const dialog = document.getElementById("safety-gate-dialog");
  const select = document.getElementById("sg-obligation-select");
  const obls = state.data?.obligations || [];

  select.innerHTML = obls
    .map(
      (o) =>
        `<option value="${escapeHtml(o.id)}">${escapeHtml(o.case_id)} — ${escapeHtml(o.patient_name)} (${escapeHtml(o.lifecycle_status)} / ${escapeHtml(o.evidence_review_status)})</option>`
    )
    .join("");

  const targetId = preferredOblId || state.selectedObligationId || obls[0]?.id;
  if (targetId) select.value = targetId;

  document.getElementById("sg-error-banner").hidden = true;
  document.getElementById("sg-rationale").value = "";
  document.getElementById("sg-char-count").textContent =
    "0 characters (non-empty required by CCE guard)";
  dialog.showModal();
}

function openFhirDialog(fhirObj) {
  document.getElementById("fhir-json-code").textContent = JSON.stringify(fhirObj || {}, null, 2);
  document.getElementById("fhir-dialog").showModal();
}

function openAuditDialog(oblId) {
  const obl = (state.data?.obligations || []).find((o) => o.id === oblId);
  if (!obl) return;
  document.getElementById("audit-dialog-title").textContent = `Audit Trail • ${obl.patient_name} (${obl.case_id})`;
  document.getElementById("audit-dialog-body").innerHTML = (obl.audit_logs || [])
    .map(
      (log) => `
      <div class="audit-item">
        <div class="audit-item-top">
          <span>#${log.audit_seq} • ${escapeHtml(log.event_type)}</span>
          <span class="mono-tag">${escapeHtml(log.reason_code)}</span>
        </div>
        <div style="margin-top: 3px;">${escapeHtml(log.rationale_text)}</div>
        <div class="audit-item-meta">${escapeHtml(log.actor_id)} • ${formatDateTime(log.created_at)}</div>
      </div>
    `
    )
    .join("");
  document.getElementById("audit-dialog").showModal();
}

function exportLedgerCsv() {
  const rows = getFilteredObligations();
  const headers = [
    "case_id",
    "patient_name",
    "mrn",
    "action_code",
    "action_description",
    "lifecycle_status",
    "timeliness_status",
    "evidence_review_status",
    "ownership_status",
    "headline",
  ];
  const lines = [headers.join(",")];
  rows.forEach((r) => {
    lines.push(
      [
        r.case_id,
        r.patient_name,
        r.mrn,
        r.required_action_code,
        r.required_action_description,
        r.lifecycle_status,
        r.timeliness_status,
        r.evidence_review_status,
        r.ownership_status,
        r.headline,
      ]
        .map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`)
        .join(",")
    );
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "cce-obligations-ledger.csv";
  link.click();
  URL.revokeObjectURL(url);
  showToast("CSV Exported", `Exported ${rows.length} obligation rows.`, "info");
}

/* ============================================================================
   EVENT WIRING
   ============================================================================ */
function bindEvents() {
  document.querySelectorAll(".nav-link").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  document.getElementById("global-search")?.addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    renderOversightView();
  });

  document.querySelectorAll(".kpi-card[data-kpi-filter]").forEach((card) => {
    card.addEventListener("click", () => {
      state.ledgerFilter = card.dataset.kpiFilter;
      document.querySelectorAll(".filter-pill").forEach((p) => {
        p.classList.toggle("is-active", p.dataset.filter === state.ledgerFilter);
      });
      renderOversightView();
    });
  });

  document.querySelectorAll(".filter-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      state.ledgerFilter = pill.dataset.filter;
      document.querySelectorAll(".filter-pill").forEach((p) => {
        p.classList.toggle("is-active", p === pill);
      });
      renderOversightView();
    });
  });

  document.querySelectorAll(".gov-filter-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      state.govFilter = pill.dataset.govFilter;
      document.querySelectorAll(".gov-filter-pill").forEach((p) => {
        p.classList.toggle("is-active", p === pill);
      });
      renderGovernanceView();
    });
  });

  document.getElementById("btn-run-scenario")?.addEventListener("click", async () => {
    const sel = document.getElementById("scenario-select").value;
    await apiRequest("/api/scenarios/run", {
      method: "POST",
      body: JSON.stringify({ case_id: sel }),
    });
    ensureValidSelections();
    renderAll();
    showToast("Scenario Loaded", `Focused synthetic benchmark view on ${sel}.`, "info");
  });

  const resetAll = async () => {
    state.lastReconciliation = null;
    await apiRequest("/api/reset", { method: "POST", body: JSON.stringify({}) });
    ensureValidSelections();
    renderAll();
    showToast("Simulation Reset", "Re-seeded clean state and re-verified 10/10 benchmarks.", "success");
  };
  document.getElementById("btn-reset-all")?.addEventListener("click", resetAll);
  document.getElementById("btn-rerun-all-benchmarks")?.addEventListener("click", resetAll);

  document.getElementById("btn-export-csv")?.addEventListener("click", exportLedgerCsv);
  document.getElementById("btn-open-safety-gate-top")?.addEventListener("click", () => openSafetyGateDialog());
  document.getElementById("btn-open-safety-gate-gov")?.addEventListener("click", () => openSafetyGateDialog());

  // Delegated clicks inside tables, inspector, queue
  document.body.addEventListener("click", async (event) => {
    const actionBtn = event.target.closest("[data-obl-action]");
    if (actionBtn) {
      event.stopPropagation();
      await handleObligationAction(actionBtn.dataset.oblId, actionBtn.dataset.oblAction);
      return;
    }

    const gateBtn = event.target.closest("[data-open-gate]");
    if (gateBtn) {
      event.stopPropagation();
      openSafetyGateDialog(gateBtn.dataset.openGate);
      return;
    }

    const auditBtn = event.target.closest("[data-open-audit]");
    if (auditBtn) {
      event.stopPropagation();
      openAuditDialog(auditBtn.dataset.openAudit);
      return;
    }

    const adjBtn = event.target.closest("[data-adjudicate]");
    if (adjBtn) {
      await handleAdjudicate(adjBtn.dataset.itemId, adjBtn.dataset.adjudicate);
      return;
    }

    const histFhirBtn = event.target.closest("[data-view-history-fhir]");
    if (histFhirBtn) {
      const id = histFhirBtn.dataset.viewHistoryFhir;
      const entry = (state.data?.review_queue?.recently_adjudicated || []).find((h) => h.id === id);
      if (entry) openFhirDialog(entry.fhir_observation);
      return;
    }

    if (event.target.id === "btn-empty-simulate" || event.target.id === "btn-simulate-ingest") {
      await apiRequest("/api/review-queue/simulate", { method: "POST", body: JSON.stringify({}) });
      state.queueIndex = 0;
      ensureValidSelections();
      renderAll();
      showToast("HL7 Ingestion Simulated", "New ambiguous POCT observation queued for review.", "info");
      return;
    }

    const oblRow = event.target.closest("tr[data-obligation-id]");
    if (oblRow) {
      state.selectedObligationId = oblRow.dataset.obligationId;
      renderOversightView();
      return;
    }

    const benchRow = event.target.closest("tr[data-benchmark-id]");
    if (benchRow) {
      state.selectedBenchmarkId = benchRow.dataset.benchmarkId;
      renderAuditView();
    }
  });

  document.getElementById("btn-queue-prev")?.addEventListener("click", () => {
    const len = state.data?.review_queue?.pending?.length || 0;
    if (len > 0) {
      state.queueIndex = (state.queueIndex - 1 + len) % len;
      renderQueueView();
    }
  });

  document.getElementById("btn-queue-next")?.addEventListener("click", () => {
    const len = state.data?.review_queue?.pending?.length || 0;
    if (len > 0) {
      state.queueIndex = (state.queueIndex + 1) % len;
      renderQueueView();
    }
  });

  document.getElementById("btn-view-signed-fhir")?.addEventListener("click", () => {
    if (state.lastReconciliation?.fhir_observation) {
      openFhirDialog(state.lastReconciliation.fhir_observation);
    }
  });

  document.getElementById("btn-dismiss-recon")?.addEventListener("click", () => {
    state.lastReconciliation = null;
    renderQueueView();
  });

  // Clinical Safety Gate modal wiring
  const sgForm = document.getElementById("safety-gate-form");
  const sgRationale = document.getElementById("sg-rationale");
  sgRationale?.addEventListener("input", () => {
    document.getElementById("sg-char-count").textContent =
      `${sgRationale.value.trim().length} characters (non-empty required by CCE guard)`;
  });

  sgForm?.querySelectorAll('input[name="sg-action"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      document.getElementById("sg-reassign-group").hidden = radio.value !== "reassign";
    });
  });

  document.getElementById("btn-test-empty-guard")?.addEventListener("click", () => {
    const overrideRadio = sgForm.querySelector('input[name="sg-action"][value="override"]');
    if (overrideRadio) overrideRadio.checked = true;
    document.getElementById("sg-reassign-group").hidden = true;
    sgRationale.value = "";
    document.getElementById("sg-char-count").textContent =
      "0 characters — submitting now will test CCE empty-rationale block!";
  });

  sgForm?.addEventListener("submit", async (event) => {
    if (event.submitter?.getAttribute("formmethod") === "dialog") return;
    event.preventDefault();

    const errBanner = document.getElementById("sg-error-banner");
    errBanner.hidden = true;

    const pin = document.getElementById("sg-pin").value.trim();
    const attested = document.getElementById("sg-attest-check").checked;
    if (!pin || !attested) {
      errBanner.textContent = "Clinician PIN and audit attestation checkbox are required.";
      errBanner.hidden = false;
      return;
    }

    const oblId = document.getElementById("sg-obligation-select").value;
    const action = sgForm.querySelector('input[name="sg-action"]:checked')?.value || "override";
    const reason_code = document.getElementById("sg-reason-code").value;
    const rationale_text = sgRationale.value;
    const assigned_user_id = document.getElementById("sg-target-owner").value;

    try {
      await apiRequest(`/api/obligations/${encodeURIComponent(oblId)}/action`, {
        method: "POST",
        body: JSON.stringify({
          action,
          reason_code,
          rationale_text,
          assigned_user_id,
        }),
      });
      document.getElementById("safety-gate-dialog").close("submitted");
      ensureValidSelections();
      renderAll();
      showToast("Governance Action Recorded", `Signed '${action}' appended to immutable audit log.`, "success");
    } catch (err) {
      errBanner.textContent = `Blocked by CCE Invariant: ${err.message}`;
      errBanner.hidden = false;
    }
  });
}

setupDialogs();
bindEvents();
loadState().catch((err) => {
  showToast("Initialization Error", err.message, "error");
});
