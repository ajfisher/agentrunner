#!/usr/bin/env python3
"""Operator-facing CLI for the canonical AgentRunner operator snapshot.

This command intentionally prefers ``operator_status.json`` via the shared
``operator_data`` read model as the blessed operator surface. Raw
reconstruction is only used in explicitly bounded cases requested by the
operator (for example ``--rebuild-missing``).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from .operator_data import CliUsageError, clip, infer_state_dir, load_operator_snapshot, resolve_operator_snapshot
    from .status_artifact import (
        build_status_artifact,
        format_current_line,
        format_initiative_summary_line,
        format_last_completed_line,
        format_queue_summary_lines,
        format_result_hint_line,
        format_status_lines,
        format_warning_summary_line,
        write_status_artifact,
    )
except ImportError:  # pragma: no cover - script-mode fallback
    from operator_data import CliUsageError, clip, infer_state_dir, load_operator_snapshot, resolve_operator_snapshot
    from status_artifact import (
        build_status_artifact,
        format_current_line,
        format_initiative_summary_line,
        format_last_completed_line,
        format_queue_summary_lines,
        format_result_hint_line,
        format_status_lines,
        format_warning_summary_line,
        write_status_artifact,
    )


def warning_text(warning: Any) -> str | None:
    if not isinstance(warning, dict):
        return None
    code = clip(warning.get("code") or "warning", 48)
    severity = clip(warning.get("severity") or "info", 16)
    summary = clip(warning.get("summary") or "warning", 120)
    details = warning.get("details")
    if details:
        return f"{severity} {code}: {summary} ({clip(details, 120)})"
    return f"{severity} {code}: {summary}"


def format_queue_lines(artifact: dict[str, Any], *, queue_preview: int) -> list[str]:
    lines = [format_current_line(artifact)]
    lines.extend(format_queue_summary_lines(artifact, queue_preview=queue_preview, include_items=True))
    lines.append(format_initiative_summary_line(artifact))
    lines.append(format_last_completed_line(artifact))
    lines.append(format_warning_summary_line(artifact))
    return lines


def format_initiative_lines(artifact: dict[str, Any], *, queue_preview: int) -> list[str]:
    lines = [format_current_line(artifact)]
    lines.append(format_initiative_summary_line(artifact))
    lines.extend(format_queue_summary_lines(artifact, queue_preview=queue_preview, include_items=False))
    lines.append(format_last_completed_line(artifact))
    lines.append(format_result_hint_line(artifact))
    lines.append(format_warning_summary_line(artifact))
    return lines


def format_warning_lines(artifact: dict[str, Any]) -> list[str]:
    warnings = artifact.get("warnings") if isinstance(artifact.get("warnings"), list) else []
    if not warnings:
        return ["warnings: -"]
    lines = ["warnings:"]
    for warning in warnings:
        text = warning_text(warning)
        if text:
            lines.append(f"  - {text}")
    return lines


def render_command(command: str, artifact: dict[str, Any], *, queue_preview: int) -> list[str]:
    if command == "status":
        return format_status_lines(artifact, queue_preview=queue_preview)
    if command == "queue":
        return format_queue_lines(artifact, queue_preview=queue_preview)
    if command == "initiatives":
        return format_initiative_lines(artifact, queue_preview=queue_preview)
    raise CliUsageError(f"unsupported command: {command}")


def print_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)


def render_snapshot(command: str, artifact: dict[str, Any] | None, notes: list[str], *, queue_preview: int) -> list[str]:
    lines: list[str] = []
    if artifact is not None:
        lines.extend(render_command(command, artifact, queue_preview=queue_preview))
    else:
        lines.append("status: unavailable")
    if notes:
        lines.append("notes:")
        lines.extend(f"  - {note}" for note in notes)
    return lines


def watch_loop(args: argparse.Namespace, state_dir: Path) -> int:
    interval = max(1.0, float(args.interval))
    iterations = 0
    while True:
        artifact, notes = load_operator_snapshot(
            state_dir,
            queue_preview=args.queue,
            tick_count=args.ticks,
            rebuild_missing=args.rebuild_missing,
            rebuild_malformed=args.rebuild_malformed,
            write_rebuild=args.write_rebuild,
            build_status_artifact=build_status_artifact,
            write_status_artifact=write_status_artifact,
        )
        if iterations:
            print()
        print(f"== {time.strftime('%Y-%m-%d %H:%M:%S %z')} | every {interval:g}s ==")
        print(f"project: {args.project or state_dir.name}")
        print(f"state dir: {state_dir}")
        print_lines(render_snapshot("status", artifact, notes, queue_preview=args.queue))
        iterations += 1
        if args.count and iterations >= args.count:
            return 0
        time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operator CLI for the canonical AgentRunner status artifact",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--project", help="Project name under ~/.agentrunner/projects/")
        subparser.add_argument("--state-dir", help="Explicit runtime state dir (overrides --project)")
        subparser.add_argument("--queue", type=int, default=3, help="How many queued items to show")
        subparser.add_argument("--ticks", type=int, default=3, help="How many recent ticks a bounded rebuild should inspect")
        subparser.add_argument("--rebuild-missing", action="store_true", help="If operator_status.json is missing, do a bounded manual rebuild from mechanics files")
        subparser.add_argument("--rebuild-malformed", action="store_true", help="If operator_status.json is malformed, do a bounded manual rebuild from mechanics files")
        subparser.add_argument("--write-rebuild", action="store_true", help="Persist a bounded rebuild back to operator_status.json")
        subparser.add_argument("--json", action="store_true", help="Print the loaded artifact as JSON instead of human-readable lines")

    add_common(subparsers.add_parser("status", help="Show the canonical operator status view"))
    add_common(subparsers.add_parser("queue", help="Show the queued work preview from the canonical artifact"))
    add_common(subparsers.add_parser("initiatives", help="Show the active initiative summary from the canonical artifact"))

    watch = subparsers.add_parser("watch", help="Repeatedly show the canonical operator status view")
    add_common(watch)
    watch.add_argument("--interval", type=float, default=5.0, help="Seconds between refreshes")
    watch.add_argument("--count", type=int, default=0, help="Stop after N refreshes (0 means continue until interrupted)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        state_dir = infer_state_dir(state_dir=args.state_dir, project=args.project)
        if args.command == "watch":
            return watch_loop(args, state_dir)
        snapshot = resolve_operator_snapshot(
            state_dir=state_dir,
            queue_preview=args.queue,
            tick_count=args.ticks,
            rebuild_missing=args.rebuild_missing,
            rebuild_malformed=args.rebuild_malformed,
            write_rebuild=args.write_rebuild,
            build_status_artifact=build_status_artifact,
            write_status_artifact=write_status_artifact,
        )
        artifact = snapshot.artifact
        notes = list(snapshot.notes)
        if artifact is None:
            print_lines(notes)
            return 1
        if args.json:
            print(json.dumps(artifact, indent=2, ensure_ascii=False))
        else:
            print_lines(render_command(args.command, artifact, queue_preview=args.queue))
            if notes:
                print("notes:")
                for note in notes:
                    print(f"  - {note}")
        return 0
    except CliUsageError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
