#!/usr/bin/env python3
"""Operator-facing CLI for the canonical AgentRunner status artifact.

This command intentionally prefers ``operator_status.json`` as the blessed
operator surface. Raw reconstruction is only used in explicitly bounded cases
requested by the operator (for example ``--rebuild-missing``).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

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

DEFAULT_PROJECTS_ROOT = Path.home() / ".agentrunner" / "projects"


class CliUsageError(RuntimeError):
    """Raised when operator input is incomplete or contradictory."""


def clip(value: Any, limit: int = 120) -> str:
    if value is None:
        return "-"
    text = str(value).strip().replace("\n", " ")
    text = " ".join(text.split())
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


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


def parse_artifact(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} did not contain a JSON object")
    return data


def infer_state_dir(args: argparse.Namespace) -> Path:
    if args.state_dir:
        return Path(args.state_dir).expanduser().resolve()
    if getattr(args, "project", None):
        return (DEFAULT_PROJECTS_ROOT / args.project).resolve()
    raise CliUsageError("provide --project or --state-dir")


def load_operator_status(
    state_dir: Path,
    *,
    queue_preview: int,
    tick_count: int,
    rebuild_missing: bool,
    rebuild_malformed: bool,
    write_rebuild: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    notes: list[str] = []
    artifact_path = state_dir / "operator_status.json"
    artifact: dict[str, Any] | None = None

    if artifact_path.exists():
        try:
            artifact = parse_artifact(artifact_path)
        except Exception as exc:
            notes.append(f"warning: operator_status.json is malformed: {clip(exc, 160)}")
            if rebuild_malformed:
                artifact = build_status_artifact(state_dir, queue_preview=queue_preview, tick_count=tick_count)
                notes.append("info: rebuilt operator status from mechanics files because --rebuild-malformed was set")
                if write_rebuild:
                    write_status_artifact(state_dir, artifact)
                    notes.append(f"info: refreshed {artifact_path}")
            else:
                notes.append("hint: rerun with --rebuild-malformed to use the bounded manual fallback")
    else:
        notes.append(f"warning: operator status artifact missing at {artifact_path}")
        if rebuild_missing:
            artifact = build_status_artifact(state_dir, queue_preview=queue_preview, tick_count=tick_count)
            notes.append("info: rebuilt operator status from mechanics files because --rebuild-missing was set")
            if write_rebuild:
                write_status_artifact(state_dir, artifact)
                notes.append(f"info: wrote {artifact_path}")
        else:
            notes.append("hint: rerun with --rebuild-missing for a bounded manual rebuild")

    return artifact, notes


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


def watch_loop(args: argparse.Namespace, state_dir: Path) -> int:
    iterations = 0
    while True:
        artifact, notes = load_operator_status(
            state_dir,
            queue_preview=args.queue,
            tick_count=args.ticks,
            rebuild_missing=args.rebuild_missing,
            rebuild_malformed=args.rebuild_malformed,
            write_rebuild=args.write_rebuild,
        )
        if iterations:
            print()
        print(f"== {time.strftime('%Y-%m-%d %H:%M:%S %z')} ==")
        print(f"state dir: {state_dir}")
        print(f"source: {'operator_status.json' if artifact is not None else 'missing-artifact'}")
        if artifact is not None:
            print_lines(render_command("status", artifact, queue_preview=args.queue))
        else:
            print("status: unavailable")
        if notes:
            print("notes:")
            for note in notes:
                print(f"  - {note}")
        iterations += 1
        if args.count and iterations >= args.count:
            return 0
        time.sleep(max(1.0, float(args.interval)))


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
        state_dir = infer_state_dir(args)
        if args.command == "watch":
            return watch_loop(args, state_dir)
        artifact, notes = load_operator_status(
            state_dir,
            queue_preview=args.queue,
            tick_count=args.ticks,
            rebuild_missing=args.rebuild_missing,
            rebuild_malformed=args.rebuild_malformed,
            write_rebuild=args.write_rebuild,
        )
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
