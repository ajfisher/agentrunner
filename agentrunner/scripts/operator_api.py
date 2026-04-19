#!/usr/bin/env python3
"""Tiny stdlib HTTP entrypoint for the canonical AgentRunner operator snapshot.

This module intentionally exposes a *read-only* local JSON surface. It only
serves the canonical per-project operator snapshot and rejects unsupported
methods/paths with explicit 4xx responses.
"""
from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from .operator_data import resolve_operator_snapshot
except ImportError:  # pragma: no cover - script-mode fallback
    from operator_data import resolve_operator_snapshot

PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
READ_ONLY_METHODS = {"GET", "HEAD"}


def json_bytes(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def error_payload(*, status: int, code: str, message: str, details: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "error": code,
        "message": message,
    }
    if details is not None:
        payload["details"] = details
    return payload


class OperatorApiHandler(BaseHTTPRequestHandler):
    server_version = "AgentRunnerOperatorAPI/1"
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

    def reject_method(self) -> None:
        self.send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            error_payload(
                status=HTTPStatus.METHOD_NOT_ALLOWED,
                code="method_not_allowed",
                message="This API is read-only. Use GET or HEAD.",
                details={"allowedMethods": sorted(READ_ONLY_METHODS)},
            ),
            headers={"Allow": ", ".join(sorted(READ_ONLY_METHODS))},
        )

    def handle_read(self, *, head_only: bool = False) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/v1/operator/snapshot":
            self.send_json(
                HTTPStatus.NOT_FOUND,
                error_payload(
                    status=HTTPStatus.NOT_FOUND,
                    code="not_found",
                    message="Unknown endpoint. Use /v1/operator/snapshot?project=<project>.",
                ),
                head_only=head_only,
            )
            return

        params = parse_qs(parsed.query, keep_blank_values=True)
        values = params.get("project", [])
        if not values:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                error_payload(
                    status=HTTPStatus.BAD_REQUEST,
                    code="missing_project",
                    message="Missing required query parameter: project",
                ),
                head_only=head_only,
            )
            return
        if len(values) != 1:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                error_payload(
                    status=HTTPStatus.BAD_REQUEST,
                    code="invalid_project",
                    message="Provide exactly one project value.",
                    details={"received": values},
                ),
                head_only=head_only,
            )
            return

        project = values[0].strip()
        if not project:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                error_payload(
                    status=HTTPStatus.BAD_REQUEST,
                    code="invalid_project",
                    message="Project must not be blank.",
                ),
                head_only=head_only,
            )
            return
        if not PROJECT_RE.fullmatch(project):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                error_payload(
                    status=HTTPStatus.BAD_REQUEST,
                    code="invalid_project",
                    message="Project may only contain letters, digits, dot, underscore, or hyphen.",
                    details={"project": project},
                ),
                head_only=head_only,
            )
            return

        snapshot = resolve_operator_snapshot(project=project)
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

        self.send_json(
            HTTPStatus.OK,
            {
                "project": project,
                "artifactPath": str(snapshot.artifact_path),
                "notes": list(snapshot.notes),
                "snapshot": snapshot.artifact,
            },
            head_only=head_only,
        )

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
    parser = argparse.ArgumentParser(description="Serve the read-only local AgentRunner operator snapshot API")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), OperatorApiHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
