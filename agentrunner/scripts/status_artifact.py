#!/usr/bin/env python3
"""Canonical operator status artifact builder for AgentRunner runtimes.

This script reads mechanics-owned runtime truth defensively and derives a compact
operator-facing summary artifact. It never mutates queue/state authority; it only
writes the derivative ``operator_status.json`` when asked.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .reconciliation_policy import STALE_RUN_AFTER, reconcile_runtime_state
except ImportError:  # pragma: no cover - script-mode fallback
    from reconciliation_policy import STALE_RUN_AFTER, reconcile_runtime_state


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def clip(value: Any, limit: int = 160) -> str:
    if value is None:
        return "-"
    text = str(value).strip().replace("\n", " ")
    text = " ".join(text.split())
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def git_output(repo_path: Path, *args: str) -> str | None:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return proc.stdout.strip()


def derive_repo_context(
    state: dict[str, Any],
    current: dict[str, Any] | None,
    initiative: dict[str, Any] | None,
    last_completed: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    candidates: list[dict[str, Any]] = []
    raw_current = state.get("current") if isinstance(state.get("current"), dict) else None
    queue_item = raw_current.get("queueItem") if isinstance(raw_current, dict) and isinstance(raw_current.get("queueItem"), dict) else None
    if isinstance(queue_item, dict):
        candidates.append(queue_item)
    if isinstance(current, dict):
        candidates.append(current)
    if isinstance(last_completed, dict):
        candidates.append(last_completed)
    if isinstance(initiative, dict):
        candidates.append(initiative)

    repo_path = branch = base = None
    for candidate in candidates:
        if repo_path is None and isinstance(candidate.get("repo_path"), str) and candidate.get("repo_path").strip():
            repo_path = candidate.get("repo_path")
        if repo_path is None and isinstance(candidate.get("repoPath"), str) and candidate.get("repoPath").strip():
            repo_path = candidate.get("repoPath")
        if branch is None and isinstance(candidate.get("branch"), str) and candidate.get("branch").strip():
            branch = candidate.get("branch")
        if base is None and isinstance(candidate.get("base"), str) and candidate.get("base").strip():
            base = candidate.get("base")
    return repo_path, branch, base


def inspect_live_repo(*, repo_path: str | None, expected_branch: str | None, base: str | None) -> dict[str, Any]:
    if not repo_path:
        return {
            "present": False,
            "freshness": "missing",
            "details": {"repoPath": None, "reason": "no repo path available"},
        }
    repo = Path(repo_path)
    if not repo.exists() or not repo.is_dir():
        return {
            "present": False,
            "freshness": "missing",
            "details": {"repoPath": repo_path, "reason": "repo path missing"},
        }

    head = git_output(repo, "rev-parse", "HEAD")
    branch = git_output(repo, "rev-parse", "--abbrev-ref", "HEAD")
    status_porcelain = git_output(repo, "status", "--short")
    merge_base_ok = None
    if base and expected_branch:
        import subprocess

        proc = subprocess.run(["git", "merge-base", "--is-ancestor", base, expected_branch], cwd=repo, capture_output=True, text=True)
        merge_base_ok = proc.returncode == 0 if proc.returncode in (0, 1) else None

    present = head is not None and branch is not None
    details = {
        "repoPath": str(repo),
        "inspectedAt": iso_now(),
        "branch": branch,
        "expectedBranch": expected_branch,
        "branchMatchesExpected": bool(branch and expected_branch and branch == expected_branch) if expected_branch else True,
        "base": base,
        "baseIsAncestorOfExpectedBranch": merge_base_ok,
        "head": head,
        "headPresent": bool(head),
        "cleanWorktree": status_porcelain == "" if status_porcelain is not None else False,
        "statusPorcelain": status_porcelain,
    }
    return {
        "present": present,
        "freshness": "fresh" if present else "missing",
        "details": details,
    }


def load_json(path: Path, default: Any, *, warnings: list[dict[str, Any]] | None = None, code_prefix: str | None = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        if warnings is not None and code_prefix:
            warnings.append({
                "code": f"malformed_{code_prefix}",
                "severity": "warning",
                "summary": f"Could not parse {path.name}",
                "details": clip(exc, 200),
            })
        return default


def tail_lines(path: Path, count: int) -> list[str]:
    if count <= 0 or not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-count:]
    except Exception:
        return []


def tail_ndjson(path: Path, count: int, *, warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    malformed = 0
    for raw in tail_lines(path, max(count * 4, count)):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            malformed += 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
    if malformed:
        warnings.append({
            "code": "malformed_ticks",
            "severity": "warning",
            "summary": f"Skipped {malformed} malformed tick line(s)",
            "details": str(path),
        })
    return out[-count:]


def summarize_checks(checks: Any) -> str | None:
    if not isinstance(checks, list) or not checks:
        return None
    total = len(checks)
    ok = blocked = error = other = 0
    for check in checks:
        status = check.get("status") if isinstance(check, dict) else None
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


def result_hint(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    operator_summary = result.get("operatorSummary")
    if isinstance(operator_summary, str) and operator_summary.strip():
        lines = [ln.strip(" -") for ln in operator_summary.splitlines() if ln.strip()]
        generic_prefixes = (
            "status:",
            "commit:",
            "approved:",
            "merged:",
            "checks:",
        )
        informative = [line for line in lines[1:] if line and not line.lower().startswith(generic_prefixes)]
        if informative:
            return clip(informative[0], 160)
        for line in lines[1:]:
            if line:
                return clip(line, 160)
        if lines:
            return clip(lines[0], 160)
    summary = result.get("summary")
    if summary:
        return clip(summary, 160)
    checks = summarize_checks(result.get("checks"))
    if checks:
        return clip(checks, 160)
    return None


def queue_item_summary(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "queueItemId": item.get("id"),
        "role": item.get("role"),
        "branch": item.get("branch"),
        "goal": clip(item.get("goal"), 160) if item.get("goal") else None,
    }


def current_summary(current: Any, *, now: datetime) -> dict[str, Any] | None:
    if not isinstance(current, dict):
        return None
    started_at = current.get("startedAt") if isinstance(current.get("startedAt"), str) else None
    age_seconds = None
    started_dt = parse_iso(started_at)
    if started_dt is not None:
        age_seconds = max(0, int((now - started_dt).total_seconds()))
    summary = {
        "queueItemId": current.get("queueItemId"),
        "role": current.get("role"),
        "branch": current.get("queueItem", {}).get("branch") if isinstance(current.get("queueItem"), dict) else current.get("branch"),
        "startedAt": started_at,
        "ageSeconds": age_seconds,
        "runId": current.get("runId"),
        "sessionKey": current.get("sessionKey"),
        "resultPath": current.get("resultPath"),
    }
    return summary


def completed_summary(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    queue_item = item.get("queueItem") if isinstance(item.get("queueItem"), dict) else {}
    return {
        "queueItemId": item.get("queueItemId"),
        "role": item.get("role"),
        "status": item.get("status"),
        "summary": clip(item.get("summary"), 160) if item.get("summary") else None,
        "endedAt": item.get("endedAt") or item.get("ts"),
        "runId": item.get("runId"),
        "sessionKey": item.get("sessionKey"),
        "branch": queue_item.get("branch") if queue_item else item.get("branch"),
        "base": queue_item.get("base") if queue_item else item.get("base"),
        "repo_path": queue_item.get("repo_path") if queue_item else item.get("repo_path"),
    }


def initiative_summary(state_dir: Path, state: dict[str, Any], *, warnings: list[dict[str, Any]]) -> dict[str, Any] | None:
    pointer = state.get("initiative") if isinstance(state.get("initiative"), dict) else None
    current = state.get("current") if isinstance(state.get("current"), dict) else None
    queue_item = current.get("queueItem") if isinstance(current, dict) and isinstance(current.get("queueItem"), dict) else None
    queue_initiative = queue_item.get("initiative") if isinstance(queue_item, dict) and isinstance(queue_item.get("initiative"), dict) else None
    seed = pointer or queue_initiative
    if not isinstance(seed, dict):
        return None

    initiative_id = seed.get("initiativeId")
    phase = seed.get("phase")
    current_subtask_id = seed.get("subtaskId") or seed.get("currentSubtaskId")
    branch = seed.get("branch")
    base = seed.get("base")
    state_path = seed.get("statePath")

    loaded: dict[str, Any] | None = None
    if isinstance(state_path, str) and state_path.strip():
        loaded = load_json(Path(state_path), {}, warnings=warnings, code_prefix="initiative_state")
    elif isinstance(initiative_id, str) and initiative_id.strip():
        guess = state_dir / "initiatives" / initiative_id / "state.json"
        if guess.exists():
            loaded = load_json(guess, {}, warnings=warnings, code_prefix="initiative_state")
            state_path = str(guess)
    if isinstance(loaded, dict) and loaded:
        initiative_id = loaded.get("initiativeId") or initiative_id
        phase = loaded.get("phase") or phase
        current_subtask_id = loaded.get("currentSubtaskId") or current_subtask_id
        branch = loaded.get("branch") or branch
        base = loaded.get("base") or base

    return {
        "initiativeId": initiative_id,
        "phase": phase,
        "currentSubtaskId": current_subtask_id,
        "branch": branch,
        "base": base,
        "statePath": state_path,
    }


def derive_last_completed(state_dir: Path, state: dict[str, Any], ticks: list[dict[str, Any]], *, warnings: list[dict[str, Any]]) -> dict[str, Any] | None:
    last_completed = state.get("lastCompleted") if isinstance(state.get("lastCompleted"), dict) else None
    tick = ticks[-1] if ticks else None
    if isinstance(tick, dict):
        summary = completed_summary(tick) or {}
        hint = result_hint(tick.get("result"))
        if hint and not summary.get("summary"):
            summary["summary"] = hint
        return summary or None
    summary = completed_summary(last_completed)
    if not summary:
        return None
    qid = summary.get("queueItemId")
    if qid:
        result = load_json(state_dir / "results" / f"{qid}.json", None, warnings=warnings, code_prefix="result")
        hint = result_hint(result)
        if hint and not summary.get("summary"):
            summary["summary"] = hint
    return summary


def build_status_artifact(state_dir: Path, *, queue_preview: int = 3, tick_count: int = 3, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc).astimezone()
    warnings: list[dict[str, Any]] = []

    state = load_json(state_dir / "state.json", {}, warnings=warnings, code_prefix="state")
    queue_path = state_dir / "queue.json"
    queue = load_json(queue_path, [], warnings=warnings, code_prefix="queue")
    if not isinstance(state, dict):
        warnings.append({"code": "invalid_state_shape", "severity": "warning", "summary": "state.json was not an object", "details": None})
        state = {}
    if not isinstance(queue, list):
        warnings.append({"code": "invalid_queue_shape", "severity": "warning", "summary": "queue.json was not a list", "details": None})
        queue = []
    elif not queue_path.exists():
        warnings.append({"code": "missing_queue", "severity": "info", "summary": "queue.json missing; treating queue as empty", "details": None})

    ticks = tail_ndjson(state_dir / "ticks.ndjson", max(1, tick_count), warnings=warnings)
    current = current_summary(state.get("current"), now=now)
    initiative = initiative_summary(state_dir, state, warnings=warnings)
    last_completed = derive_last_completed(state_dir, state, ticks, warnings=warnings)
    repo_path, repo_branch, repo_base = derive_repo_context(state, current, initiative, last_completed)
    live_repo = inspect_live_repo(repo_path=repo_path, expected_branch=repo_branch, base=repo_base)

    queue_preview_items = []
    for item in queue[: max(0, queue_preview)]:
        summary = queue_item_summary(item)
        if summary:
            queue_preview_items.append(summary)
        else:
            warnings.append({"code": "malformed_queue_item", "severity": "warning", "summary": "Encountered malformed queue item", "details": None})

    reconciliation = reconcile_runtime_state(
        now=now,
        state=state,
        queue=queue,
        ticks=ticks,
        current=current,
        initiative=initiative,
        last_completed=last_completed,
        live_repo=live_repo,
    )
    warnings.extend([
        {
            "code": reason.get("code"),
            "severity": reason.get("severity"),
            "summary": reason.get("summary"),
            "details": reason.get("details"),
            "source": reason.get("source"),
            "precedence": reason.get("precedence"),
        }
        for reason in reconciliation.get("reasons", [])
        if isinstance(reason, dict) and str(reason.get("severity") or "").lower() in {"warning", "error"}
    ])

    artifact = {
        "project": state.get("project") or state_dir.name,
        "status": reconciliation.get("decision"),
        "current": current,
        "queue": {
            "depth": len(queue),
            "nextIds": [str(item.get("id")) for item in queue if isinstance(item, dict) and item.get("id")][: max(0, queue_preview)],
            "preview": queue_preview_items,
        },
        "initiative": initiative,
        "lastCompleted": last_completed,
        "warnings": warnings,
        "reconciliation": reconciliation,
        "updatedAt": iso_now(),
    }

    if ticks:
        artifact["recentTicks"] = ticks
        artifact["resultHint"] = result_hint((ticks[-1] or {}).get("result"))
    elif last_completed and last_completed.get("queueItemId"):
        qid = last_completed["queueItemId"]
        result = load_json(state_dir / "results" / f"{qid}.json", None, warnings=warnings, code_prefix="result")
        artifact["resultHint"] = result_hint(result)
    else:
        artifact["resultHint"] = None

    runtime = state.get("runtime") if isinstance(state.get("runtime"), dict) else None
    if runtime:
        artifact["runtime"] = {
            "extraDevTurnsUsed": runtime.get("extraDevTurnsUsed"),
            "lastBranch": runtime.get("lastBranch"),
        }

    return artifact


def write_status_artifact(state_dir: Path, artifact: dict[str, Any]) -> Path:
    path = state_dir / "operator_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def format_current_line(artifact: dict[str, Any]) -> str:
    current = artifact.get("current") if isinstance(artifact.get("current"), dict) else None
    status = str(artifact.get("status") or "idle").upper()
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
    queue = artifact.get("queue") if isinstance(artifact.get("queue"), dict) else {}
    depth = int(queue.get("depth") or 0)
    next_ids = queue.get("nextIds") if isinstance(queue.get("nextIds"), list) else []
    bits = [f"{depth} item(s)"]
    if next_ids:
        bits.append("next=" + ", ".join(clip(item, 32) for item in next_ids[: max(0, queue_preview)]))
    lines = [f"queue: {' | '.join(bits)}"]
    if not include_items:
        return lines
    preview = queue.get("preview") if isinstance(queue.get("preview"), list) else []
    if preview:
        for idx, item in enumerate(preview[: max(0, queue_preview)], start=1):
            if not isinstance(item, dict):
                continue
            bits = [clip(item.get("queueItemId") or "?", 40), clip(item.get("role") or "?", 16)]
            if item.get("branch"):
                bits.append(clip(item.get("branch"), 36))
            if item.get("goal"):
                bits.append(clip(item.get("goal"), 80))
            lines.append(f"  {idx}. {' | '.join(bits)}")
        remaining = depth - len(preview[: max(0, queue_preview)])
        if remaining > 0:
            lines.append(f"  … +{remaining} more")
    else:
        lines.append("  (empty)")
    return lines


def format_initiative_summary_line(artifact: dict[str, Any]) -> str:
    initiative = artifact.get("initiative") if isinstance(artifact.get("initiative"), dict) else None
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
    last_completed = artifact.get("lastCompleted") if isinstance(artifact.get("lastCompleted"), dict) else None
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
    runtime = artifact.get("runtime") if isinstance(artifact.get("runtime"), dict) else None
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
    result_hint_value = artifact.get("resultHint")
    return f"result hint: {clip(result_hint_value, 120) if result_hint_value else '-'}"


def format_reconciliation_line(artifact: dict[str, Any]) -> str:
    reconciliation = artifact.get("reconciliation") if isinstance(artifact.get("reconciliation"), dict) else None
    if not reconciliation:
        return "reconciliation: -"
    bits = [clip(reconciliation.get("decision") or "-", 24)]
    summary = reconciliation.get("summary")
    if summary:
        bits.append(clip(summary, 120))
    reasons = reconciliation.get("reasons") if isinstance(reconciliation.get("reasons"), list) else []
    if reasons:
        bits.append(f"reasons={len(reasons)}")
    return f"reconciliation: {' | '.join(bits)}"


def format_warning_summary_line(artifact: dict[str, Any]) -> str:
    warnings = artifact.get("warnings") if isinstance(artifact.get("warnings"), list) else []
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
    current = artifact.get("current") if isinstance(artifact.get("current"), dict) else None
    if current and current.get("startedAt"):
        lines.append(f"started: {clip(current.get('startedAt'), 32)}")
    if artifact.get("updatedAt"):
        lines.append(f"updated: {clip(artifact.get('updatedAt'), 32)}")
    lines.extend(format_queue_summary_lines(artifact, queue_preview=queue_preview, include_items=True))
    lines.append(format_initiative_summary_line(artifact))
    lines.append(format_last_completed_line(artifact))
    runtime_line = format_runtime_line(artifact)
    if runtime_line:
        lines.append(runtime_line)
    lines.append(format_reconciliation_line(artifact))
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
