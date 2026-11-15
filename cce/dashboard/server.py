"""Standard-library WSGI HTTP application for the CCE Clinical Oversight Dashboard."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from cce.dashboard.db import DashboardDatabase

if TYPE_CHECKING:
    from wsgiref.types import StartResponse, WSGIEnvironment

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


class DashboardApp:
    """Zero-dependency WSGI server exposing the CCE oversight SPA and REST JSON API."""

    def __init__(self, db: DashboardDatabase | None = None) -> None:
        self.db = db or DashboardDatabase()

    def __call__(
        self,
        environ: WSGIEnvironment,
        start_response: StartResponse,
    ) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        query = parse_qs(str(environ.get("QUERY_STRING", "")))

        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self._serve_file(
                    TEMPLATES_DIR / "index.html", "text/html; charset=utf-8", start_response
                )

            if method == "GET" and path.startswith("/static/"):
                rel = path.removeprefix("/static/").lstrip("/")
                target = (STATIC_DIR / rel).resolve()
                static_root = STATIC_DIR.resolve()
                if not rel or not target.is_relative_to(static_root) or not target.is_file():
                    return self._json_response(
                        {"error": "Static asset not found"}, 404, start_response
                    )
                guessed, _ = mimetypes.guess_type(target.name)
                ctype = guessed or "application/octet-stream"
                if ctype.startswith("text/") or ctype == "application/javascript":
                    ctype = f"{ctype}; charset=utf-8"
                return self._serve_file(target, ctype, start_response)

            if method == "GET" and path == "/api/state":
                case_param = query.get("case_id", [None])[0]
                return self._json_response(
                    self.db.get_state(active_case_id=case_param), 200, start_response
                )

            if method == "GET" and path == "/api/scenarios":
                return self._json_response(
                    {"scenarios": self.db.get_state()["scenarios"]}, 200, start_response
                )

            if method == "POST" and path == "/api/reset":
                self.db.reset_and_seed()
                return self._json_response(self.db.get_state(), 200, start_response)

            if method == "POST" and path == "/api/scenarios/run":
                body = self._read_json_body(environ)
                case_id = str(body.get("case_id") or "ALL")
                state = self.db.run_scenario(case_id)
                return self._json_response(state, 200, start_response)

            if method == "POST" and path == "/api/review-queue/simulate":
                state = self.db.simulate_ambiguous_ingestion()
                return self._json_response(state, 200, start_response)

            if (
                method == "POST"
                and path.startswith("/api/obligations/")
                and path.endswith("/action")
            ):
                obl_id = path.removeprefix("/api/obligations/").removesuffix("/action").strip("/")
                body = self._read_json_body(environ)
                action = str(body.get("action") or "").strip()
                if not action:
                    return self._json_response(
                        {"error": "Missing 'action' field"}, 400, start_response
                    )
                state = self.db.obligation_action(obl_id, action, body)
                return self._json_response(state, 200, start_response)

            if (
                method == "POST"
                and path.startswith("/api/review-queue/")
                and path.endswith("/adjudicate")
            ):
                item_id = (
                    path.removeprefix("/api/review-queue/").removesuffix("/adjudicate").strip("/")
                )
                body = self._read_json_body(environ)
                decision = str(body.get("decision") or "").strip()
                if not decision:
                    return self._json_response(
                        {"error": "Missing 'decision' field"}, 400, start_response
                    )
                state = self.db.adjudicate_review_item(item_id, decision, body)
                return self._json_response(state, 200, start_response)

            return self._json_response(
                {"error": f"Route not found: {method} {path}"}, 404, start_response
            )
        except KeyError as exc:
            return self._json_response(
                {"error": str(exc), "state": self.db.get_state()}, 404, start_response
            )
        except ValueError as exc:
            return self._json_response(
                {"error": str(exc), "state": self.db.get_state()}, 422, start_response
            )
        except Exception as exc:  # noqa: BLE001
            return self._json_response(
                {"error": f"Internal server error: {exc}"}, 500, start_response
            )

    def _read_json_body(self, environ: WSGIEnvironment) -> dict[str, Any]:
        length_raw = environ.get("CONTENT_LENGTH") or "0"
        try:
            length = max(0, int(length_raw))
        except ValueError:
            return {}
        if length == 0:
            return {}
        stream = environ.get("wsgi.input")
        if stream is None:
            return {}
        raw = stream.read(length)
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON request body must be an object")
        return parsed

    def _serve_file(
        self,
        file_path: Path,
        content_type: str,
        start_response: StartResponse,
    ) -> list[bytes]:
        if not file_path.is_file():
            return self._json_response({"error": "File not found"}, 404, start_response)
        data = file_path.read_bytes()
        headers = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(data))),
            ("Cache-Control", "no-store"),
        ]
        start_response("200 OK", headers)
        return [data]

    def _json_response(
        self,
        payload: dict[str, Any],
        status_code: int,
        start_response: StartResponse,
    ) -> list[bytes]:
        reason_map = {
            200: "200 OK",
            400: "400 Bad Request",
            404: "404 Not Found",
            422: "422 Unprocessable Entity",
            500: "500 Internal Server Error",
        }
        body = json.dumps(payload, default=str).encode("utf-8")
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ]
        start_response(reason_map.get(status_code, f"{status_code} Error"), headers)
        return [body]
