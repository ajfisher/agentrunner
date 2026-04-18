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


def short_id(value: Any, limit: int = 18) -> str:
    text = clip(value, limit)
    if len(text) <= limit:
        return text
    return text


def summarize_checks(checks: Any) -> str | None:
    if not isinstance(checks, list) or not checks:
        return None
    total = len(checks)
    ok = blocked = error = other = 0
    names: list[str] = []
    for check in checks:
        status = None
        name = None
        if isinstance(check, dict):
            status = check.get("status")
            name = check.get("name")
        status_text = str(status or "").lower()
        if status_text == "ok":
            ok += 1
        elif status_text == "blocked":
            blocked += 1
        elif status_text == "error":
            error += 1
        else:
            other += 1
        if name and len(names) < 2:
            names.append(clip(name, 28))
    parts = [f"checks {ok}/{total} ok"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if error:
        parts.append(f"{error} error")
    if other:
        parts.append(f"{other} other")
    if names:
        parts.append("e.g. " + ", ".join(names))
    return ", ".join(parts)


def summarize_findings(findings: Any) -> str | None:
    if not isinstance(findings, list) or not findings:
        return None
    samples: list[str] = []
    for item in findings:
        if isinstance(item, dict):
            bits = [item.get("severity"), item.get("title"), item.get("summary"), item.get("path")]
            text = next((clip(bit, 44) for bit in bits if bit), None)
            if text:
                samples.append(text)
        elif item:
            samples.append(clip(item, 44))
        if len(samples) >= 2:
            break
    if samples:
        return f"findings {len(findings)}: " + "; ".join(samples)
    return f"findings {len(findings)}"


def summarize_result(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    bits: list[str] = []
    status = result.get("status")
    summary = result.get("summary")
    commit = result.get("commit")
    approved = result.get("approved")
    merged = result.get("merged")

    if status:
        bits.append(f"result {clip(status, 12)}")
    if summary:
        bits.append(clip(summary, 88))
    checks = summarize_checks(result.get("checks"))
    if checks:
        bits.append(checks)
    findings = summarize_findings(result.get("findings"))
    if findings:
        bits.append(findings)
    if commit:
        bits.append(f"commit {clip(commit, 12)}")
    if approved is True:
        bits.append("approved")
    elif approved is False:
        bits.append("not approved")
    if merged is True:
        bits.append("merged")
    elif merged is False:
        bits.append("not merged")
    if not bits:
        return "result present"
    return " ; ".join(bits)


def tick_detail(record: dict[str, Any]) -> str | None:
    summary = record.get("summary")
    if summary:
        return clip(summary, 120)

    result_summary = summarize_result(record.get("result"))
    if result_summary:
        return clip(result_summary, 120)

    checks = summarize_checks(record.get("checks"))
    if checks:
        return clip(checks, 120)

    findings = summarize_findings(record.get("findings"))
    if findings:
        return clip(findings, 120)

    session_key = record.get("sessionKey")
    if session_key:
        return f"session {clip(session_key, 48)}"

    return None


def format_tick(record: dict[str, Any]) -> str:
    head = [
        clip(record.get("ts") or "?", 25),
        short_id(record.get("queueItemId") or "?", 24),
        clip(record.get("role") or "?", 12),
        clip(record.get("status") or "?", 10),
    ]
    branch = record.get("branch")
    if branch:
        head.append(f"branch {clip(branch, 24)}")
    detail = tick_detail(record)
    if detail:
        head.append(detail)
    return " | ".join(head)


def tail_valid_ticks(path: Path, count: int) -> tuple[list[dict[str, Any]], int, int]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
            end_offset = handle.tell()
    except Exception:
        return [], 0, 0

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
        return [], malformed, end_offset
    return parsed[-count:], malformed, end_offset


def iter_follow_records(path: Path, start_offset: int) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        handle.seek(start_offset)
        while True:
            line = handle.readline()
            if line:
                record = parse_tick_line(line)
                if record is not None:
                    yield record
                continue

            try:
                current_size = path.stat().st_size
            except Exception:
                current_size = handle.tell()
            if current_size < handle.tell():
                handle.seek(0)
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

    ticks, malformed, end_offset = tail_valid_ticks(ticks_path, args.lines)
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
        for tick in iter_follow_records(ticks_path, end_offset):
            print(format_tick(tick), flush=True)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
