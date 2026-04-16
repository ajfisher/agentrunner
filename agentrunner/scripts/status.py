#!/usr/bin/env python3
"""Compact status/audit helper for agentrunner runtime state.

Prints a small operator snapshot for a runtime state dir:
- active/idle status
- concise queue view
- last completed item
- compact last tick/result hint

The helper is intentionally plain-text and defensive: missing or partially-written
runtime files should degrade to short hints rather than stack traces.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def tail_lines(path: Path, count: int) -> list[str]:
    if count <= 0 or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    return lines[-count:]


def tail_ndjson(path: Path, count: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in tail_lines(path, max(count * 3, count)):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out[-count:]


def clip(value: Any, limit: int = 96) -> str:
    if value is None:
        return "-"
    text = str(value).strip().replace("\n", " ")
    text = " ".join(text.split())
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def summarize_checks(checks: Any) -> str | None:
    if not isinstance(checks, list) or not checks:
        return None
    total = len(checks)
    ok = 0
    blocked = 0
    error = 0
    other = 0
    for check in checks:
        status = None
        if isinstance(check, dict):
            status = check.get("status")
        status = str(status or "").lower()
        if status == "ok":
            ok += 1
        elif status == "blocked":
            blocked += 1
        elif status == "error":
            error += 1
        else:
            other += 1
    parts = [f"checks {ok}/{total} ok"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if error:
        parts.append(f"{error} error")
    if other:
        parts.append(f"{other} other")
    return ", ".join(parts)


def queue_item_line(item: Any) -> str:
    if not isinstance(item, dict):
        return "? malformed queue item"
    bits = [clip(item.get("id") or "?", 40), clip(item.get("role") or "?", 16)]
    branch = item.get("branch")
    if branch:
        bits.append(clip(branch, 36))
    goal = item.get("goal")
    if goal:
        bits.append(clip(goal, 80))
    return " | ".join(bits)


def completed_line(item: Any) -> str:
    if not isinstance(item, dict):
        return "-"
    bits = [clip(item.get("queueItemId") or "?", 40), clip(item.get("role") or "?", 16), clip(item.get("status") or "?", 16)]
    ended = item.get("endedAt") or item.get("ts")
    if ended:
        bits.append(clip(ended, 32))
    return " | ".join(bits)


def result_hint(result: Any) -> str:
    if not isinstance(result, dict):
        return "-"
    operator_summary = result.get("operatorSummary")
    if isinstance(operator_summary, str) and operator_summary.strip():
        lines = [ln.strip(" -") for ln in operator_summary.splitlines() if ln.strip()]
        for line in lines[1:]:
            if line:
                return clip(line, 120)
        if lines:
            return clip(lines[0], 120)
    summary = result.get("summary")
    if summary:
        return clip(summary, 120)
    checks = summarize_checks(result.get("checks"))
    if checks:
        return checks
    return "-"


def tick_line(tick: Any) -> str:
    if not isinstance(tick, dict):
        return "-"
    bits = [
        clip(tick.get("ts") or "?", 32),
        clip(tick.get("queueItemId") or "?", 40),
        clip(tick.get("role") or "?", 16),
        clip(tick.get("status") or "?", 16),
    ]
    summary = tick.get("summary")
    if summary:
        bits.append(clip(summary, 88))
    return " | ".join(bits)


def read_last_result_hint(state_dir: Path, state: dict[str, Any], tick: dict[str, Any] | None) -> str:
    if tick and isinstance(tick.get("result"), dict):
        return result_hint(tick.get("result"))

    qid = None
    current = state.get("current")
    last_completed = state.get("lastCompleted")
    if isinstance(last_completed, dict):
        qid = last_completed.get("queueItemId")
    if not qid and isinstance(current, dict):
        qid = current.get("queueItemId")
    if not qid:
        return "-"

    result = load_json(state_dir / "results" / f"{qid}.json", None)
    return result_hint(result)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--queue", type=int, default=3, help="how many queued items to show")
    ap.add_argument("--ticks", type=int, default=1, help="how many recent ticks to inspect")
    args = ap.parse_args()

    sd = Path(args.state_dir)
    state = load_json(sd / "state.json", {})
    queue = load_json(sd / "queue.json", [])
    if not isinstance(state, dict):
        state = {}
    if not isinstance(queue, list):
        queue = []

    project = state.get("project") or sd.name
    running = bool(state.get("running"))
    current = state.get("current") if isinstance(state.get("current"), dict) else None
    last_completed = state.get("lastCompleted") if isinstance(state.get("lastCompleted"), dict) else None
    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else {}
    ticks = tail_ndjson(sd / "ticks.ndjson", max(args.ticks, 1))
    last_tick = ticks[-1] if ticks else None

    print(f"project: {project}")
    if running and current:
        print(f"status: ACTIVE | {clip(current.get('queueItemId') or '?', 40)} | {clip(current.get('role') or '?', 16)}")
        started_at = current.get("startedAt")
        if started_at:
            print(f"started: {clip(started_at, 32)}")
    else:
        print("status: IDLE")

    updated = state.get("updatedAt")
    if updated:
        print(f"updated: {clip(updated, 32)}")

    queue_count = len(queue)
    print(f"queue: {queue_count} item(s)")
    if queue_count:
        for idx, item in enumerate(queue[: max(args.queue, 0)], start=1):
            print(f"  {idx}. {queue_item_line(item)}")
        remaining = queue_count - max(args.queue, 0)
        if remaining > 0:
            print(f"  … +{remaining} more")
    else:
        print("  (empty)")

    print(f"last completed: {completed_line(last_completed)}")

    if runtime:
        extra = runtime.get("extraDevTurnsUsed")
        branch = runtime.get("lastBranch")
        bits = []
        if extra is not None:
            bits.append(f"extraDevTurnsUsed={extra}")
        if branch:
            bits.append(f"lastBranch={clip(branch, 36)}")
        if bits:
            print(f"runtime: {', '.join(bits)}")

    if last_tick:
        print(f"last tick: {tick_line(last_tick)}")
    elif (sd / "ticks.ndjson").exists():
        print("last tick: (unreadable or partial)")
    else:
        print("last tick: (none)")

    print(f"result hint: {read_last_result_hint(sd, state, last_tick)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
