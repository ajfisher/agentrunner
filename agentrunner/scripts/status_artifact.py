#!/usr/bin/env python3
"""Canonical operator status artifact formatter/debug CLI for AgentRunner.

The canonical snapshot build/write logic lives in ``operator_data.py`` so other
operator-facing consumers can import a single shared data layer. This module
keeps the human-readable formatting helpers plus a small explicit rebuild/debug
entrypoint.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .operator_data import (
        build_status_artifact,
        clip,
        snapshot_current,
        snapshot_initiative,
        snapshot_last_completed,
        snapshot_queue,
        snapshot_queue_preview,
        snapshot_reconciliation,
        snapshot_result_hint,
        snapshot_runtime,
        snapshot_status,
        snapshot_updated_at,
        snapshot_warnings,
        write_status_artifact,
    )
    from .reconciliation_policy import STALE_RUN_AFTER
except ImportError:  # pragma: no cover - script-mode fallback
    from operator_data import (
        build_status_artifact,
        clip,
        snapshot_current,
        snapshot_initiative,
        snapshot_last_completed,
        snapshot_queue,
        snapshot_queue_preview,
        snapshot_reconciliation,
        snapshot_result_hint,
        snapshot_runtime,
        snapshot_status,
        snapshot_updated_at,
        snapshot_warnings,
        write_status_artifact,
    )
    from reconciliation_policy import STALE_RUN_AFTER


def format_current_line(artifact: dict[str, Any]) -> str:
    current = snapshot_current(artifact)
    status = str(snapshot_status(artifact) or "idle").upper()
    if current:
        bits = [
            status,
            clip(current.get("queueItemId") or "?", 40),
            clip(current.get("role") or "?", 16),
        ]
        if current.get("branch"):
            bits.append(clip(current.get("branch"), 36))
        if current.get("ageSeconds") is not None:
            bits.append(f"age={current.get('ageSeconds')}s")
        return f"status: {' | '.join(bits)}"
    return f"status: {status}"


def format_queue_summary_lines(artifact: dict[str, Any], *, queue_preview: int = 3, include_items: bool = True) -> list[str]:
    queue = snapshot_queue(artifact)
    depth = int(queue.get("depth") or 0)
    next_ids = queue.get("nextIds") if isinstance(queue.get("nextIds"), list) else []
    bits = [f"{depth} item(s)"]
    if next_ids:
        bits.append("next=" + ", ".join(clip(item, 32) for item in next_ids[: max(0, queue_preview)]))
    lines = [f"queue: {' | '.join(bits)}"]
    if not include_items:
        return lines
    preview = snapshot_queue_preview(artifact, queue_preview=queue_preview)
    if preview:
        for idx, item in enumerate(preview, start=1):
            if not isinstance(item, dict):
                continue
            bits = [clip(item.get("queueItemId") or "?", 40), clip(item.get("role") or "?", 16)]
            if item.get("branch"):
                bits.append(clip(item.get("branch"), 36))
            if item.get("goal"):
                bits.append(clip(item.get("goal"), 80))
            lines.append(f"  {idx}. {' | '.join(bits)}")
        remaining = depth - len(preview)
        if remaining > 0:
            lines.append(f"  … +{remaining} more")
    else:
        lines.append("  (empty)")
    return lines


def format_initiative_summary_line(artifact: dict[str, Any]) -> str:
    initiative = snapshot_initiative(artifact)
    if not initiative or not initiative.get("initiativeId"):
        return "initiative: -"
    bits = [clip(initiative.get("initiativeId"), 40)]
    if initiative.get("phase"):
        bits.append(f"phase={clip(initiative.get('phase'), 24)}")
    if initiative.get("currentSubtaskId"):
        bits.append(f"subtask={clip(initiative.get('currentSubtaskId'), 32)}")
    if initiative.get("branch"):
        bits.append(f"branch={clip(initiative.get('branch'), 36)}")
    if initiative.get("base"):
        bits.append(f"base={clip(initiative.get('base'), 24)}")
    return f"initiative: {' | '.join(bits)}"


def format_last_completed_line(artifact: dict[str, Any]) -> str:
    last_completed = snapshot_last_completed(artifact)
    if not last_completed:
        return "last completed: -"
    bits = [
        clip(last_completed.get("queueItemId") or "?", 40),
        clip(last_completed.get("role") or "?", 16),
        clip(last_completed.get("status") or "?", 16),
    ]
    if last_completed.get("endedAt"):
        bits.append(clip(last_completed.get("endedAt"), 32))
    if last_completed.get("summary"):
        bits.append(clip(last_completed.get("summary"), 88))
    return f"last completed: {' | '.join(bits)}"


def format_runtime_line(artifact: dict[str, Any]) -> str | None:
    runtime = snapshot_runtime(artifact)
    if not runtime:
        return None
    bits = []
    if runtime.get("extraDevTurnsUsed") is not None:
        bits.append(f"extraDevTurnsUsed={runtime.get('extraDevTurnsUsed')}")
    if runtime.get("lastBranch"):
        bits.append(f"lastBranch={clip(runtime.get('lastBranch'), 36)}")
    if bits:
        return f"runtime: {', '.join(bits)}"
    return None


def format_result_hint_line(artifact: dict[str, Any]) -> str:
    result_hint_value = snapshot_result_hint(artifact)
    return f"result hint: {clip(result_hint_value, 120) if result_hint_value else '-'}"


def format_reconciliation_line(artifact: dict[str, Any]) -> str:
    reconciliation = snapshot_reconciliation(artifact)
    if not reconciliation:
        return "reconciliation: -"
    bits = [clip(reconciliation.get("decision") or "-", 24)]
    reasons = reconciliation.get("reasons") if isinstance(reconciliation.get("reasons"), list) else []
    winning_reason = reasons[0] if reasons and isinstance(reasons[0], dict) else None
    if winning_reason:
        source = winning_reason.get("source")
        code = winning_reason.get("code")
        precedence = winning_reason.get("precedence")
        winner_bits = []
        if source:
            winner_bits.append(f"source={clip(source, 24)}")
        if code:
            winner_bits.append(f"rule={clip(code, 48)}")
        if precedence is not None:
            winner_bits.append(f"p{precedence}")
        if winner_bits:
            bits.append("winner=" + ", ".join(winner_bits))
    summary = reconciliation.get("summary")
    if summary:
        bits.append(clip(summary, 120))
    if reasons:
        bits.append(f"reasons={len(reasons)}")
    return f"reconciliation: {' | '.join(bits)}"


def format_reconciliation_policy_line(artifact: dict[str, Any]) -> str:
    reconciliation = snapshot_reconciliation(artifact)
    if not reconciliation:
        return "operator hierarchy: -"
    policy = reconciliation.get("policy") if isinstance(reconciliation.get("policy"), dict) else None
    if not policy:
        return "operator hierarchy: -"
    order = policy.get("precedenceOrder") if isinstance(policy.get("precedenceOrder"), list) else []
    policy_name = clip(policy.get("name") or "-", 48)
    version = policy.get("version")
    prefix = policy_name if version is None else f"{policy_name} v{version}"
    if not order:
        return f"operator hierarchy: {prefix}"
    return f"operator hierarchy: {prefix} | {' > '.join(clip(item, 43) for item in order)}"


def format_warning_summary_line(artifact: dict[str, Any]) -> str:
    warnings = snapshot_warnings(artifact)
    if not warnings:
        return "warnings: -"
    warning_bits = []
    for warning in warnings[:3]:
        if not isinstance(warning, dict):
            continue
        warning_bits.append(f"{warning.get('code')}: {clip(warning.get('summary'), 72)}")
    if warning_bits:
        return "warnings: " + " | ".join(warning_bits)
    return "warnings: -"


def format_status_lines(artifact: dict[str, Any], *, queue_preview: int = 3) -> list[str]:
    lines: list[str] = []
    lines.append(f"project: {artifact.get('project')}")
    lines.append(format_current_line(artifact))
    current = snapshot_current(artifact)
    if current and current.get("startedAt"):
        lines.append(f"started: {clip(current.get('startedAt'), 32)}")
    updated_at = snapshot_updated_at(artifact)
    if updated_at:
        lines.append(f"updated: {clip(updated_at, 32)}")
    lines.extend(format_queue_summary_lines(artifact, queue_preview=queue_preview, include_items=True))
    lines.append(format_initiative_summary_line(artifact))
    lines.append(format_last_completed_line(artifact))
    runtime_line = format_runtime_line(artifact)
    if runtime_line:
        lines.append(runtime_line)
    lines.append(format_reconciliation_line(artifact))
    lines.append(format_reconciliation_policy_line(artifact))
    lines.append(format_result_hint_line(artifact))
    lines.append(format_warning_summary_line(artifact))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Build or print canonical AgentRunner operator status artifact")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--queue", type=int, default=3, help="How many queued items to include in previews")
    ap.add_argument("--ticks", type=int, default=3, help="How many recent ticks to inspect")
    ap.add_argument("--write", action="store_true", help="Write operator_status.json to the runtime state dir")
    ap.add_argument("--print", dest="print_summary", action="store_true", help="Print human summary lines")
    ap.add_argument("--json", dest="print_json", action="store_true", help="Print artifact JSON to stdout")
    args = ap.parse_args()

    state_dir = Path(args.state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=args.queue, tick_count=args.ticks)
    if args.write:
        write_status_artifact(state_dir, artifact)
    if args.print_summary or (not args.write and not args.print_json):
        for line in format_status_lines(artifact, queue_preview=args.queue):
            print(line)
    if args.print_json:
        print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
