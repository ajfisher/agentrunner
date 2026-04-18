#!/usr/bin/env python3
"""Compact operator helper for tailing agentrunner tick logs."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable

RUNTIME_ROOT = Path("/home/openclaw/.agentrunner/projects")
POLL_INTERVAL_SECONDS = 1.0


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


def parse_tick_line(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def format_tick(record: dict[str, Any]) -> str:
    parts = [
        clip(record.get("ts") or "?", 32),
        clip(record.get("queueItemId") or "?", 48),
        clip(record.get("role") or "?", 16),
        clip(record.get("status") or "?", 16),
    ]
    summary = record.get("summary")
    if summary:
        parts.append(clip(summary, 120))
    return " | ".join(parts)


def tail_valid_ticks(path: Path, count: int) -> tuple[list[dict[str, Any]], int]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return [], 0

    parsed: list[dict[str, Any]] = []
    malformed = 0
    for line in lines:
        record = parse_tick_line(line)
        if record is None:
            if line.strip():
                malformed += 1
            continue
        parsed.append(record)
    if count <= 0:
        return [], malformed
    return parsed[-count:], malformed


def iter_follow_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        handle.seek(0, 2)
        while True:
            line = handle.readline()
            if line:
                record = parse_tick_line(line)
                if record is not None:
                    yield record
                continue
            time.sleep(POLL_INTERVAL_SECONDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="project name under ~/.agentrunner/projects/")
    ap.add_argument("-n", "--lines", type=int, default=10, help="number of valid tick records to print")
    ap.add_argument("--follow", action="store_true", help="follow appended valid tick records")
    args = ap.parse_args()

    if args.lines < 0:
        print("error: --lines must be >= 0")
        return 2

    state_dir = RUNTIME_ROOT / args.project
    if not state_dir.exists() or not state_dir.is_dir():
        print(f"project not found: {state_dir}")
        return 1

    ticks_path = state_dir / "ticks.ndjson"
    if not ticks_path.exists():
        print(f"ticks log not found: {ticks_path}")
        return 1

    ticks, malformed = tail_valid_ticks(ticks_path, args.lines)
    if ticks:
        for tick in ticks:
            print(format_tick(tick))
    else:
        print(f"no valid tick records in {ticks_path}")

    if malformed:
        print(f"note: skipped {malformed} malformed line(s)")

    if not args.follow:
        return 0

    try:
        for tick in iter_follow_records(ticks_path):
            print(format_tick(tick), flush=True)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
