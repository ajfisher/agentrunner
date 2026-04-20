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
    snapshot = resolved.artifact or {}
    queue = operator_data.snapshot_queue(snapshot)
    initiative = operator_data.snapshot_initiative(snapshot)
    current = operator_data.snapshot_current(snapshot)
    last_completed = operator_data.snapshot_last_completed(snapshot)
    warnings = operator_data.snapshot_warnings(snapshot)
    result_hint = operator_data.snapshot_result_hint(snapshot)

    lines = [
        f"AgentRunner TUI · project={project}",
        "mode: local read-only operator surface over the canonical snapshot",
        f"status: {operator_data.snapshot_status(snapshot).upper()}",
        f"updated: {snapshot.get('updatedAt', 'unknown')}",
    ]

    if resolved.notes:
        lines.append("")
        lines.append("notes:")
        lines.extend(f"- {note}" for note in resolved.notes)

    lines.append("")
    lines.append("current:")
    if current:
        lines.extend(
            [
                f"- queue item: {current.get('queueItemId', '-')}",
                f"- role: {current.get('role', '-')}",
                f"- branch: {current.get('branch', '-')}",
                f"- started: {current.get('startedAt', '-')}",
                f"- age seconds: {current.get('ageSeconds', '-')}",
            ]
        )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("queue:")
    lines.append(f"- depth: {queue.get('depth', 0)}")
    next_ids = queue.get('nextIds') or []
    preview = queue.get('preview') or []
    lines.append(f"- next ids: {', '.join(next_ids) if next_ids else '(empty)'}")
    if preview:
        lines.append("- preview:")
        for item in preview[:5]:
            lines.append(
                f"  - {item.get('id', '-')} [{item.get('role', '-')}] {item.get('branch', '-') or '-'}"
            )

    lines.append("")
    lines.append("initiative:")
    if initiative:
        lines.extend(
            [
                f"- id: {initiative.get('initiativeId', '-')}",
                f"- phase: {initiative.get('phase', '-')}",
                f"- subtask: {initiative.get('currentSubtaskId', '-')}",
            ]
        )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("last completed:")
    if last_completed:
        lines.extend(
            [
                f"- queue item: {last_completed.get('queueItemId', '-')}",
                f"- role: {last_completed.get('role', '-')}",
                f"- status: {last_completed.get('status', '-')}",
                f"- summary: {last_completed.get('summary', '-')}",
            ]
        )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("warnings:")
    if warnings:
        for warning in warnings:
            lines.append(
                f"- {warning.get('severity', 'info')}:{warning.get('code', 'unknown')} {warning.get('summary', '')}".rstrip()
            )
    else:
        lines.append("- none")

    lines.append("")
    lines.append("result hint:")
    if result_hint:
        lines.append(f"- {result_hint}")
    else:
        lines.append("- none")

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
