#!/usr/bin/env python3
"""Small read-only terminal surface for the canonical AgentRunner operator snapshot.

This module intentionally stays bounded:
- local terminal only
- read-only over the canonical operator snapshot/read model
- no queue/state mutation actions
- stdlib-only refresh/render loop so the first contract does not add a heavy UI runtime

The current implementation is deliberately simple. It redraws a compact snapshot view
from ``operator_data`` and can either render once (useful for tests/smoke checks) or
refresh in-place until interrupted.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

from agentrunner.scripts import operator_data


def _lines_for_snapshot(project: str, resolved: operator_data.OperatorSnapshotRead) -> list[str]:
    view = operator_data.build_operator_screen_view(project, resolved, queue_preview=5)

    lines = [
        f"AgentRunner TUI · project={view.project}",
        view.mode_line,
        view.status_line,
        view.updated_line,
    ]

    if view.notes:
        lines.append("")
        lines.append("notes:")
        lines.extend(f"- {note}" for note in view.notes)

    for section in view.sections:
        lines.append("")
        lines.append(f"{section.title}:")
        lines.extend(f"- {line}" for line in section.lines)

    lines.append("")
    lines.append("controls: Ctrl-C quit | read-only surface (no queue/state mutation actions)")
    return lines


def render_snapshot(project: str, resolved: operator_data.OperatorSnapshotRead) -> str:
    return "\n".join(_lines_for_snapshot(project, resolved)) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the optional local read-only AgentRunner terminal UI"
    )
    parser.add_argument("--project", required=True, help="Project id to inspect")
    parser.add_argument("--state-dir", help="Explicit runtime state dir override")
    parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=2.0,
        help="Refresh cadence for the local redraw loop (default: 2.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render a single snapshot and exit (useful for smoke tests)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear the terminal between redraws",
    )
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
    return parser


def _clear_screen() -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def _load(args: argparse.Namespace) -> operator_data.OperatorSnapshotRead:
    return operator_data.resolve_operator_snapshot(
        project=args.project,
        state_dir=args.state_dir,
        rebuild_missing=args.rebuild_missing,
        rebuild_malformed=args.rebuild_malformed,
        write_rebuild=args.write_rebuild,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.refresh_seconds <= 0:
        parser.error("--refresh-seconds must be > 0")

    if args.once:
        sys.stdout.write(render_snapshot(args.project, _load(args)))
        return 0

    try:
        while True:
            if not args.no_clear:
                _clear_screen()
            sys.stdout.write(render_snapshot(args.project, _load(args)))
            sys.stdout.flush()
            time.sleep(args.refresh_seconds)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
