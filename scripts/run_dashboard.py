"""CLI entrypoint for launching the CCE Clinical Obligation Oversight Dashboard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

from cce.dashboard.db import DashboardDatabase
from cce.dashboard.server import DashboardApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Clinical Completion Engine (CCE) Clinical Obligation Oversight Dashboard."
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="HTTP port to listen on (default: 8080)"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional SQLAlchemy database URL (defaults to CCE_DASHBOARD_DATABASE_URL/DATABASE_URL or SQLite in-memory)",
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=None,
        help="Optional path to SYNTHETIC CASES V1.csv",
    )
    args = parser.parse_args(argv)

    db = DashboardDatabase(database_url=args.database_url, csv_path=args.csv_path)
    app = DashboardApp(db=db)

    print(f"CCE Clinical Oversight Dashboard running at http://{args.host}:{args.port}")
    print(
        f"Database backend: {db.backend_name}"
        + (f" ({db.fallback_reason})" if db.fallback_reason else "")
    )
    print(
        f"Seeded {len(db.benchmark_results)} synthetic benchmark scenarios "
        f"({sum(1 for b in db.benchmark_results.values() if b['passed'])}/{len(db.benchmark_results)} passing)."
    )

    with make_server(args.host, args.port, app) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down CCE Clinical Oversight Dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
