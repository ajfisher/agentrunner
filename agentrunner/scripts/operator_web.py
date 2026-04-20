#!/usr/bin/env python3
"""Small local read-only browser surface for the canonical AgentRunner operator snapshot.

This module deliberately stays thin:
- localhost-oriented stdlib HTTP server
- GET/HEAD only
- HTML and JSON page-model routes derived from the canonical snapshot/read model
- no direct mechanics-file archaeology inside the web surface
- no write/control actions

The browser-facing shaping here is presentation-only. The underlying data continues
to come from ``operator_data.resolve_operator_snapshot(...)`` and the canonical
snapshot contract.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from . import operator_data
except ImportError:  # pragma: no cover - script-mode fallback
    import operator_data

PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
READ_ONLY_METHODS = {"GET", "HEAD"}


@dataclass(frozen=True)
class WebSection:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class OperatorPageModel:
    project: str
    artifact_path: str
    state_dir: str
    mode_line: str
    status_line: str
    updated_line: str
    notes: tuple[str, ...]
    sections: tuple[WebSection, ...]


SAMPLE_PROJECT = "sample-project"
SAMPLE_RESOLVED = operator_data.OperatorSnapshotRead(
    state_dir=operator_data.Path.cwd(),
    artifact_path=operator_data.Path.cwd() / f"{SAMPLE_PROJECT}-operator_status.sample.json",
    artifact={
        "contract": dict(operator_data.OPERATOR_SNAPSHOT_CONTRACT),
        "project": SAMPLE_PROJECT,
        "status": "running",
        "updatedAt": "2026-04-20T11:00:00+10:00",
        "current": {
            "queueItemId": "sample-dev-001",
            "role": "developer",
            "branch": "feature/operator-web-ui",
            "startedAt": "2026-04-20T10:53:00+10:00",
            "ageSeconds": 420,
        },
        "queue": {
            "depth": 2,
            "nextIds": ["sample-review-002", "sample-merge-003"],
            "preview": [
                {
                    "queueItemId": "sample-review-002",
                    "role": "reviewer",
                    "branch": "feature/operator-web-ui",
                    "goal": "Review the thin read-only browser surface",
                },
                {
                    "queueItemId": "sample-merge-003",
                    "role": "merger",
                    "branch": "feature/operator-web-ui",
                    "goal": "Merge the browser adapter once checks pass",
                },
            ],
        },
        "initiative": {
            "initiativeId": "agentrunner-operator-web-ui",
            "phase": "implementation",
            "currentSubtaskId": "operator-web-ui-http-and-viewmodel-seam",
        },
        "lastCompleted": {
            "queueItemId": "sample-arch-000",
            "role": "architect",
            "status": "ok",
            "summary": "Defined the web UI as a thin adapter over the canonical snapshot.",
        },
        "warnings": [
            {
                "code": "sample_fixture",
                "severity": "info",
                "summary": "Using the built-in smoke sample; no live mechanics reads.",
            }
        ],
        "reconciliation": {"decision": "running", "reasons": []},
        "resultHint": "Browser page model is derived from the canonical snapshot contract.",
    },
    notes=("info: using built-in sample snapshot (no mechanics reads)",),
)


def json_bytes(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def html_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def error_payload(*, status: int, code: str, message: str, details: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "error": code,
        "message": message,
    }
    if details is not None:
        payload["details"] = details
    return payload


def build_page_model(project: str, resolved: operator_data.OperatorSnapshotRead, *, queue_preview: int = 5) -> OperatorPageModel:
    view = operator_data.build_operator_screen_view(project, resolved, queue_preview=queue_preview)
    return OperatorPageModel(
        project=view.project,
        artifact_path=str(resolved.artifact_path),
        state_dir=str(resolved.state_dir),
        mode_line=view.mode_line,
        status_line=view.status_line,
        updated_line=view.updated_line,
        notes=tuple(resolved.notes),
        sections=tuple(WebSection(title=section.title, lines=tuple(section.lines)) for section in view.sections),
    )


def page_model_payload(model: OperatorPageModel) -> dict[str, Any]:
    return {
        "project": model.project,
        "artifactPath": model.artifact_path,
        "stateDir": model.state_dir,
        "modeLine": model.mode_line,
        "statusLine": model.status_line,
        "updatedLine": model.updated_line,
        "notes": list(model.notes),
        "sections": [asdict(section) for section in model.sections],
    }


def render_html(model: OperatorPageModel) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    note_items = "".join(f"<li>{esc(note)}</li>" for note in model.notes) or "<li>No snapshot notes.</li>"
    section_cards = []
    for section in model.sections:
        line_items = "".join(f"<li>{esc(line)}</li>" for line in section.lines) or "<li>none</li>"
        section_cards.append(
            "<section class=\"card\">"
            f"<h2>{esc(section.title)}</h2>"
            f"<ul>{line_items}</ul>"
            "</section>"
        )
    cards = "".join(section_cards)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>AgentRunner operator · {esc(model.project)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --border: #334155;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 1.25rem; border-bottom: 1px solid var(--border); background: rgba(17,24,39,.9); position: sticky; top: 0; }}
    main {{ padding: 1.25rem; display: grid; gap: 1rem; }}
    .meta {{ display: grid; gap: .35rem; color: var(--muted); }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 1rem; }}
    h1, h2 {{ margin: 0 0 .75rem 0; }}
    h1 {{ font-size: 1.25rem; }}
    h2 {{ font-size: 1rem; color: var(--accent); text-transform: capitalize; }}
    ul {{ margin: 0; padding-left: 1.1rem; }}
    li {{ margin: .3rem 0; }}
    code {{ color: var(--accent); }}
    footer {{ padding: 0 1.25rem 1.25rem; color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>AgentRunner operator · {esc(model.project)}</h1>
    <div class=\"meta\">
      <div>{esc(model.mode_line)}</div>
      <div>{esc(model.status_line)}</div>
      <div>{esc(model.updated_line)}</div>
      <div>artifact: <code>{esc(model.artifact_path)}</code></div>
      <div>state dir: <code>{esc(model.state_dir)}</code></div>
    </div>
  </header>
  <main>
    <section class=\"card\">
      <h2>snapshot notes</h2>
      <ul>{note_items}</ul>
    </section>
    <div class=\"card-grid\">{cards}</div>
  </main>
  <footer>Read-only local inspection surface over the canonical operator snapshot contract.</footer>
</body>
</html>
"""


class OperatorWebHandler(BaseHTTPRequestHandler):
    server_version = "AgentRunnerOperatorWeb/1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self.handle_read()

    def do_HEAD(self) -> None:  # noqa: N802
        self.handle_read(head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        self.reject_method()

    def do_PUT(self) -> None:  # noqa: N802
        self.reject_method()

    def do_PATCH(self) -> None:  # noqa: N802
        self.reject_method()

    def do_DELETE(self) -> None:  # noqa: N802
        self.reject_method()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    @property
    def config(self) -> argparse.Namespace:
        return self.server.operator_web_config  # type: ignore[attr-defined]

    def reject_method(self) -> None:
        payload = error_payload(
            status=HTTPStatus.METHOD_NOT_ALLOWED,
            code="method_not_allowed",
            message="This web surface is read-only. Use GET or HEAD.",
            details={"allowedMethods": sorted(READ_ONLY_METHODS)},
        )
        self.send_json(HTTPStatus.METHOD_NOT_ALLOWED, payload, headers={"Allow": ", ".join(sorted(READ_ONLY_METHODS))})

    def handle_read(self, *, head_only: bool = False) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.handle_page(parsed, head_only=head_only)
            return
        if parsed.path == "/v1/operator/page-model":
            self.handle_page_model(parsed, head_only=head_only)
            return
        self.send_json(
            HTTPStatus.NOT_FOUND,
            error_payload(
                status=HTTPStatus.NOT_FOUND,
                code="not_found",
                message="Unknown endpoint. Use / or /v1/operator/page-model.",
            ),
            head_only=head_only,
        )

    def resolve_project(self, parsed) -> tuple[str | None, dict[str, Any] | None]:
        params = parse_qs(parsed.query, keep_blank_values=True)
        values = params.get("project", [])
        if len(values) > 1:
            return None, error_payload(
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_project",
                message="Provide exactly one project value.",
                details={"received": values},
            )
        project = values[0].strip() if values else (self.config.project or "").strip()
        if self.config.smoke_sample:
            return project or SAMPLE_PROJECT, None
        if not project:
            return None, error_payload(
                status=HTTPStatus.BAD_REQUEST,
                code="missing_project",
                message="Missing project. Provide ?project=<project> or launch with --project.",
            )
        if not PROJECT_RE.fullmatch(project):
            return None, error_payload(
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_project",
                message="Project may only contain letters, digits, dot, underscore, or hyphen.",
                details={"project": project},
            )
        return project, None

    def load_snapshot(self, project: str) -> operator_data.OperatorSnapshotRead:
        if self.config.smoke_sample:
            artifact = dict(SAMPLE_RESOLVED.artifact or {})
            artifact["project"] = project
            return operator_data.OperatorSnapshotRead(
                state_dir=SAMPLE_RESOLVED.state_dir,
                artifact_path=SAMPLE_RESOLVED.artifact_path,
                artifact=artifact,
                notes=SAMPLE_RESOLVED.notes,
            )
        return operator_data.resolve_operator_snapshot(
            project=project,
            rebuild_missing=self.config.rebuild_missing,
            rebuild_malformed=self.config.rebuild_malformed,
            write_rebuild=self.config.write_rebuild,
        )

    def handle_page(self, parsed, *, head_only: bool) -> None:
        project, error = self.resolve_project(parsed)
        if error is not None:
            self.send_json(HTTPStatus.BAD_REQUEST, error, head_only=head_only)
            return
        assert project is not None
        snapshot = self.load_snapshot(project)
        if snapshot.artifact is None:
            self.send_json(
                HTTPStatus.NOT_FOUND,
                error_payload(
                    status=HTTPStatus.NOT_FOUND,
                    code="snapshot_unavailable",
                    message="Canonical operator snapshot is not available for this project.",
                    details={
                        "project": project,
                        "artifactPath": str(snapshot.artifact_path),
                        "notes": list(snapshot.notes),
                    },
                ),
                head_only=head_only,
            )
            return
        model = build_page_model(project, snapshot)
        self.send_html(HTTPStatus.OK, render_html(model), head_only=head_only)

    def handle_page_model(self, parsed, *, head_only: bool) -> None:
        project, error = self.resolve_project(parsed)
        if error is not None:
            self.send_json(HTTPStatus.BAD_REQUEST, error, head_only=head_only)
            return
        assert project is not None
        snapshot = self.load_snapshot(project)
        if snapshot.artifact is None:
            self.send_json(
                HTTPStatus.NOT_FOUND,
                error_payload(
                    status=HTTPStatus.NOT_FOUND,
                    code="snapshot_unavailable",
                    message="Canonical operator snapshot is not available for this project.",
                    details={
                        "project": project,
                        "artifactPath": str(snapshot.artifact_path),
                        "notes": list(snapshot.notes),
                    },
                ),
                head_only=head_only,
            )
            return
        model = build_page_model(project, snapshot)
        self.send_json(HTTPStatus.OK, page_model_payload(model), head_only=head_only)

    def send_html(self, status: HTTPStatus | int, content: str, *, head_only: bool = False) -> None:
        body = html_bytes(content)
        self.send_response(int(status))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def send_json(
        self,
        status: HTTPStatus | int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        head_only: bool = False,
    ) -> None:
        body = json_bytes(payload)
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local read-only AgentRunner operator web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8766, help="Bind port (default: 8766)")
    parser.add_argument("--project", help="Default project to inspect if ?project= is omitted")
    parser.add_argument(
        "--rebuild-missing",
        action="store_true",
        help="If operator_status.json is missing, do a bounded manual rebuild from mechanics files",
    )
    parser.add_argument(
        "--rebuild-malformed",
        action="store_true",
        help="If operator_status.json is malformed, do a bounded manual rebuild from mechanics files",
    )
    parser.add_argument(
        "--write-rebuild",
        action="store_true",
        help="Persist a bounded rebuild back to operator_status.json",
    )
    parser.add_argument(
        "--smoke-sample",
        action="store_true",
        help="Serve a built-in sample page model without live mechanics reads",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), OperatorWebHandler)
    server.operator_web_config = args  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
