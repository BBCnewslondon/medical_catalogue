#!/usr/bin/env python3
# ruff: noqa: E402
"""CLI Demonstration Tool: CCE Synthetic Event Simulator & Time Machine.

Executes synthetic benchmark clinical scenarios day-by-day, displaying clear
chronological playback, 4-dimension state progression, audit records, and verification.

Usage:
    python scripts/run_case_simulation.py --case-id CCE-003
    python scripts/run_case_simulation.py --all
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cce.audit import register_audit_listeners
from cce.simulator.runner import ScenarioRunner, ScenarioRunResult

console = Console()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://cce_user:cce_password@localhost:5432/cce_db",
)


def _format_dimensions(state: Any) -> Text:
    """Format 4-dimension status tuple with rich semantic clinical colors."""
    t = Text()

    # Lifecycle
    lc = state.lifecycle_status.value
    if lc == "COMPLETE":
        t.append(lc, style="bold green")
    elif lc == "ACTIVE":
        t.append(lc, style="bold cyan")
    elif lc == "SUPERSEDED":
        t.append(lc, style="bold magenta")
    elif lc == "CANCELLED":
        t.append(lc, style="bold red")
    else:
        t.append(lc, style="dim")

    t.append(" | ", style="dim")

    # Timeliness
    tm = state.timeliness_status.value
    if tm == "OVERDUE":
        t.append(tm, style="bold red")
    elif tm == "DUE":
        t.append(tm, style="bold yellow")
    elif tm == "NOT_DUE":
        t.append(tm, style="green")
    else:
        t.append(tm, style="dim")

    t.append(" | ", style="dim")

    # Evidence
    ev = state.evidence_review_status.value
    if ev == "VERIFIED_COMPLETE":
        t.append(ev, style="bold green")
    elif ev == "AMBIGUOUS_REVIEW_EVIDENCE":
        t.append(ev, style="bold yellow")
    elif ev == "AWAITING_REVIEW_EVIDENCE":
        t.append(ev, style="bold red")
    elif ev == "ACTION_EVIDENCE_RECEIVED":
        t.append(ev, style="bold blue")
    else:
        t.append(ev, style="dim")

    t.append(" | ", style="dim")

    # Ownership
    ow = state.ownership_status.value
    if ow == "NO_OWNER":
        t.append(ow, style="bold red on white")
    else:
        t.append(ow, style="bold blue")

    return t


def display_scenario_playback(result: ScenarioRunResult) -> None:
    """Render full day-by-day clinical simulation playback and verification table."""
    sc = result.scenario

    meta_text = Text()
    meta_text.append(f"Title: {sc.title}\n", style="bold white")
    meta_text.append(f"Role: {sc.benchmark_role} | Setting: {sc.setting}\n", style="dim")
    meta_text.append(f"Action: {sc.action} [{sc.action_code}]\n", style="cyan")
    meta_text.append(
        f"Owner: {sc.owner or 'UNALLOCATED (NO_OWNER)'} | Deadline: Day {sc.due_day} (requires review: {sc.requires_review_evidence})\n",
        style="dim",
    )
    meta_text.append(f"Focus: {sc.engine_test_focus}", style="italic yellow")

    console.print(
        Panel(
            meta_text,
            title=f"[bold cyan]Synthetic Scenario Playback: {result.case_id}[/bold cyan]",
            subtitle="Clinical Completion Engine (CCE) Time Machine",
            box=box.ROUNDED,
        )
    )

    playback_table = Table(
        title=f"Chronological Timeline Playback — {result.case_id}",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold magenta",
    )
    playback_table.add_column("Day", style="bold yellow", width=8)
    playback_table.add_column("Ingested Event(s)", style="white", min_width=32)
    playback_table.add_column("4-Dimension State Snapshot", style="cyan", min_width=36)
    playback_table.add_column("Headline / Risk", style="bold", min_width=18)
    playback_table.add_column("Audit / Review Queue Mutations", style="dim", min_width=28)

    for step in result.step_results:
        # Event descriptions
        ev_lines: list[str] = []
        if not step.ingested_events:
            ev_lines.append("[dim]-- No external events --[/dim]")
        else:
            for ie in step.ingested_events:
                token = ie["token"]
                desc = ie.get("description", "")
                if ie.get("rejected"):
                    ev_lines.append(f"[bold red]✘ {token}[/bold red]: {desc}")
                elif ie.get("observation_only"):
                    ev_lines.append(f"[dim blue]ℹ {token}[/dim blue]: {desc}")
                else:
                    ev_lines.append(f"[bold green]✔ {token}[/bold green]: {desc}")

        events_str = "\n".join(ev_lines)

        # 4D state snapshot
        state_repr = (
            _format_dimensions(step.state_after_step) if step.state_after_step else Text("N/A")
        )

        # Headline
        headline_style = "bold red" if step.should_flag_after_step else "bold green"
        headline_repr = f"[{headline_style}]{step.headline_after_step}[/{headline_style}]"

        # Audit & review items
        mutations: list[str] = []
        for a in step.audit_logs_created:
            mutations.append(f"Audit #{a['audit_seq']} ({a['event_type']}): {a['reason_code']}")
        for r in step.rejections:
            mutations.append(f"[bold red]GATED[/bold red]: {r['error_type']} - {r['error']}")
        if step.review_items_count > 0:
            mutations.append(f"[yellow]Review Items Queue: {step.review_items_count}[/yellow]")

        mutations_str = "\n".join(mutations) if mutations else "[dim]--[/dim]"

        playback_table.add_row(
            f"Day {step.day}",
            events_str,
            state_repr,
            headline_repr,
            mutations_str,
        )

    console.print(playback_table)

    # Rejection alert panel if anti-gaming occurred
    if result.rejections:
        rej_text = Text()
        for rej in result.rejections:
            rej_text.append(
                f"Day {rej['day']} [{rej['event_token']}]: {rej['error']}\n", style="bold red"
            )
        rej_text.append(
            "Machine-derived audit state successfully protected against unverified override.",
            style="italic green",
        )
        console.print(
            Panel(
                rej_text,
                title="[bold red]Defensive Governance Guard Triggered (Anti-Gaming Protection)[/bold red]",
                box=box.HEAVY,
            )
        )

    # Verification Summary Table
    verif_table = Table(
        title=f"Ground-Truth Verification: {result.case_id}",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    verif_table.add_column("Verification Dimension", style="bold")
    verif_table.add_column("Expected CSV Ground Truth", style="yellow")
    verif_table.add_column("Simulated Engine Result", style="green")
    verif_table.add_column("Status", style="bold")

    checks = [
        (
            "Lifecycle Status",
            sc.expected_lifecycle_status.value,
            result.obligation.lifecycle_status.value,
            result.obligation.lifecycle_status == sc.expected_lifecycle_status,
        ),
        (
            "Timeliness Status",
            sc.expected_timeliness_status.value,
            result.obligation.timeliness_status.value,
            result.obligation.timeliness_status == sc.expected_timeliness_status,
        ),
        (
            "Evidence Review Status",
            sc.expected_evidence_review_status.value,
            result.obligation.evidence_review_status.value,
            result.obligation.evidence_review_status == sc.expected_evidence_review_status,
        ),
        (
            "Ownership Status",
            sc.expected_ownership_status.value,
            result.obligation.ownership_status.value,
            result.obligation.ownership_status == sc.expected_ownership_status,
        ),
        (
            "Expected Headline",
            sc.expected_headline,
            result.final_headline,
            result.final_headline == sc.expected_headline,
        ),
        (
            "Should Flag Risk",
            str(sc.should_flag),
            str(result.should_flag),
            result.should_flag == sc.should_flag,
        ),
        (
            "Review Items Generated",
            f"{sc.expected_review_item['status']} ({sc.expected_review_item['owner']})"
            if sc.expected_review_item
            else "None",
            f"{result.review_items[0].status.value} ({result.review_items[0].assigned_reviewer_id})"
            if result.review_items
            else "None",
            bool(sc.expected_review_item) == bool(result.review_items),
        ),
        (
            "Audit Ledger Invariant",
            f"audit_seq == {len(result.audit_logs)}",
            f"audit_seq = {result.obligation.audit_seq} ({len(result.audit_logs)} records)",
            result.obligation.audit_seq == len(result.audit_logs),
        ),
    ]

    for dim, exp, act, ok in checks:
        st = "[bold green]PASS[/bold green]" if ok else "[bold red]FAIL[/bold red]"
        verif_table.add_row(dim, exp, act, st)

    console.print(verif_table)
    console.print()


def display_all_summary(results: dict[str, ScenarioRunResult]) -> None:
    """Render executive summary of all synthetic scenario executions."""
    summary_table = Table(
        title="Clinical Completion Engine (CCE) — Synthetic Benchmark Summary (10 Cases)",
        box=box.DOUBLE_EDGE,
        header_style="bold magenta",
    )
    summary_table.add_column("Case ID", style="bold yellow")
    summary_table.add_column("Title", style="white")
    summary_table.add_column("Final 4D Dimensions", style="cyan")
    summary_table.add_column("Headline", style="bold")
    summary_table.add_column("Flagged?", style="bold")
    summary_table.add_column("Audits", justify="right")
    summary_table.add_column("Review Queue", justify="center")
    summary_table.add_column("Result", justify="center")

    passed_count = 0
    total_count = len(results)

    for case_id, res in results.items():
        if res.success:
            passed_count += 1
            status_text = "[bold green]PASS[/bold green]"
        else:
            status_text = "[bold red]FAIL[/bold red]"

        flag_text = "[bold red]YES[/bold red]" if res.should_flag else "[green]NO[/green]"
        review_count = len(res.review_items)
        review_str = f"[yellow]{review_count}[/yellow]" if review_count > 0 else "[dim]0[/dim]"

        summary_table.add_row(
            case_id,
            res.scenario.title[:38] + ("..." if len(res.scenario.title) > 38 else ""),
            _format_dimensions(res.final_state),
            res.final_headline,
            flag_text,
            str(len(res.audit_logs)),
            review_str,
            status_text,
        )

    console.print(summary_table)

    accuracy_pct = (passed_count / total_count * 100) if total_count > 0 else 0
    result_panel_style = "bold green" if passed_count == total_count else "bold red"
    console.print(
        Panel(
            f"Benchmark Execution Complete: [bold]{passed_count}/{total_count}[/bold] Scenarios Passed "
            f"([bold]{accuracy_pct:.1f}% Benchmark Accuracy[/bold])",
            title=f"[{result_panel_style}]Simulation Suite Results[/{result_panel_style}]",
            box=box.ROUNDED,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CCE Synthetic Scenario Simulator & Time Machine Runner",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        help="Specific scenario ID to run (e.g. CCE-001, CCE-003, CCE-010)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 10 synthetic benchmark scenarios",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default="SYNTHETIC CASES V1.csv",
        help="Path to synthetic benchmark CSV dataset",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=DATABASE_URL,
        help="PostgreSQL database URL",
    )

    args = parser.parse_args()

    if not args.case_id and not args.all:
        parser.print_help()
        sys.exit(1)

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        console.print(f"[bold red]Error:[/bold red] CSV file not found at '{csv_path}'")
        sys.exit(1)

    engine = create_engine(
        args.database_url,
        echo=False,
        pool_pre_ping=True,
    )
    register_audit_listeners()

    with Session(engine) as session:
        runner = ScenarioRunner(session=session, csv_path=csv_path)

        if args.case_id:
            case_id = args.case_id.upper()
            if case_id not in runner.scenarios:
                console.print(
                    f"[bold red]Error:[/bold red] Case ID '{case_id}' not found. "
                    f"Available cases: {', '.join(sorted(runner.scenarios.keys()))}"
                )
                sys.exit(1)

            res = runner.run_case(case_id)
            display_scenario_playback(res)
            session.rollback()

            if not res.success:
                sys.exit(1)

        elif args.all:
            results = runner.run_all()
            for _case_id, res in results.items():
                display_scenario_playback(res)

            display_all_summary(results)
            session.rollback()

            if not all(r.success for r in results.values()):
                sys.exit(1)


if __name__ == "__main__":
    main()
