#!/usr/bin/env python3
"""Shared read-only operator snapshot/data-layer helpers for AgentRunner.

This module names the per-project operator snapshot contract and centralizes the
canonical artifact load/build/write path so operator-facing surfaces do not
re-implement it ad hoc.

It is intentionally stdlib-only. Loading helpers are read-only; rebuild/write is
an explicit caller action.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from .initiative_status import status_message_summary
    from .reconciliation_policy import reconcile_runtime_state
except ImportError:  # pragma: no cover - script-mode fallback
    from initiative_status import status_message_summary
    from reconciliation_policy import reconcile_runtime_state

DEFAULT_PROJECTS_ROOT = Path.home() / ".agentrunner" / "projects"
OPERATOR_STATUS_FILENAME = "operator_status.json"
OPERATOR_SNAPSHOT_CONTRACT = {
    "name": "agentrunner.operator-status-snapshot",
    "version": 2,
    "filename": OPERATOR_STATUS_FILENAME,
    "pathPattern": "~/.agentrunner/projects/<project>/operator_status.json",
    "ownership": "derivative operator-facing snapshot",
}


class CliUsageError(RuntimeError):
    """Raised when operator input is incomplete or contradictory."""


BuildArtifact = Callable[..., dict[str, Any]]
WriteArtifact = Callable[[Path, dict[str, Any]], Path]


@dataclass(frozen=True)
class OperatorSnapshotRead:
    """Resolved operator snapshot plus bounded rebuild notes for non-CLI callers."""

    state_dir: Path
    artifact_path: Path
    artifact: dict[str, Any] | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class OperatorScreenSection:
    """Stable screen section for operator-facing adapters like the TUI."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class OperatorScreenView:
    """Importable view-model assembled strictly from the canonical snapshot/read model."""

    project: str
    mode_line: str
    status_line: str
    updated_line: str
    notes: tuple[str, ...]
    sections: tuple[OperatorScreenSection, ...]


def snapshot_contract(artifact: dict[str, Any]) -> dict[str, Any]:
    return artifact.get("contract") if isinstance(artifact.get("contract"), dict) else {}


def snapshot_project(artifact: dict[str, Any]) -> str | None:
    value = artifact.get("project")
    return value if isinstance(value, str) and value.strip() else None


def snapshot_status(artifact: dict[str, Any]) -> str | None:
    value = artifact.get("status")
    return value if isinstance(value, str) and value.strip() else None


def snapshot_current(artifact: dict[str, Any]) -> dict[str, Any] | None:
    value = artifact.get("current")
    return value if isinstance(value, dict) else None


def snapshot_queue(artifact: dict[str, Any]) -> dict[str, Any]:
    value = artifact.get("queue")
    return value if isinstance(value, dict) else {}


def snapshot_queue_preview(artifact: dict[str, Any], *, queue_preview: int) -> list[dict[str, Any]]:
    queue = snapshot_queue(artifact)
    preview = queue.get("preview")
    if not isinstance(preview, list):
        return []
    items: list[dict[str, Any]] = []
    for item in preview[: max(0, queue_preview)]:
        if isinstance(item, dict):
            items.append(item)
    return items


def snapshot_initiative(artifact: dict[str, Any]) -> dict[str, Any] | None:
    value = artifact.get("initiative")
    return value if isinstance(value, dict) else None


def snapshot_closure(artifact: dict[str, Any]) -> dict[str, Any] | None:
    value = artifact.get("closure")
    return value if isinstance(value, dict) else None


def snapshot_last_completed(artifact: dict[str, Any]) -> dict[str, Any] | None:
    value = artifact.get("lastCompleted")
    return value if isinstance(value, dict) else None


def snapshot_runtime(artifact: dict[str, Any]) -> dict[str, Any] | None:
    value = artifact.get("runtime")
    return value if isinstance(value, dict) else None


def snapshot_reconciliation(artifact: dict[str, Any]) -> dict[str, Any] | None:
    value = artifact.get("reconciliation")
    return value if isinstance(value, dict) else None


def snapshot_result_hint(artifact: dict[str, Any]) -> str | None:
    value = artifact.get("resultHint")
    return value if isinstance(value, str) and value.strip() else None


def snapshot_updated_at(artifact: dict[str, Any]) -> str | None:
    value = artifact.get("updatedAt")
    return value if isinstance(value, str) and value.strip() else None


def snapshot_warnings(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    warnings = artifact.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [warning for warning in warnings if isinstance(warning, dict)]


def build_operator_screen_view(
    project: str,
    resolved: OperatorSnapshotRead,
    *,
    queue_preview: int = 5,
) -> OperatorScreenView:
    """Map the canonical snapshot/read-model into stable operator screen sections."""
    snapshot = resolved.artifact or {}
    current = snapshot_current(snapshot)
    initiative = snapshot_initiative(snapshot)
    closure = snapshot_closure(snapshot)
    last_completed = snapshot_last_completed(snapshot)
    warnings = snapshot_warnings(snapshot)
    result_hint_value = snapshot_result_hint(snapshot)

    queue = snapshot_queue(snapshot)
    next_ids = queue.get("nextIds") if isinstance(queue.get("nextIds"), list) else []
    queue_lines = [f"depth: {queue.get('depth', 0)}"]
    queue_lines.append(f"next ids: {', '.join(str(item) for item in next_ids) if next_ids else '(empty)'}")
    preview = snapshot_queue_preview(snapshot, queue_preview=queue_preview)
    if preview:
        queue_lines.append('preview:')
        for item in preview:
            queue_lines.append(
                f"  - {item.get('queueItemId', '-')} [{item.get('role', '-')}] {item.get('branch', '-') or '-'}"
            )
    else:
        queue_lines.append('preview: (empty)')

    current_lines = (
        (
            f"queue item: {current.get('queueItemId', '-')}",
            f"role: {current.get('role', '-')}",
            f"branch: {current.get('branch', '-')}",
            f"started: {current.get('startedAt', '-')}",
            f"age seconds: {current.get('ageSeconds', '-')}",
        )
        if current
        else ('none',)
    )
    initiative_lines = (
        (
            f"id: {initiative.get('initiativeId', '-')}",
            f"phase: {initiative.get('phase', '-')}",
            f"subtask: {initiative.get('currentSubtaskId', '-')}",
        )
        if initiative
        else ('none',)
    )
    closure_lines = (
        (
            f"state: {closure.get('state', '-')}",
            f"handoff safe: {closure.get('handoffSafe', '-')}",
            f"quiet: {closure.get('quiet', '-')}",
            f"phase: {closure.get('initiativePhase', '-')}",
            f"reason: {closure.get('reason', '-')}",
        )
        if closure
        else ('none',)
    )
    last_completed_lines = (
        (
            f"queue item: {last_completed.get('queueItemId', '-')}",
            f"role: {last_completed.get('role', '-')}",
            f"status: {last_completed.get('status', '-')}",
            f"summary: {last_completed.get('summary', '-')}",
        )
        if last_completed
        else ('none',)
    )
    warning_lines = tuple(
        f"{warning.get('severity', 'info')}:{warning.get('code', 'unknown')} {warning.get('summary', '')}".rstrip()
        for warning in warnings
    ) or ('none',)
    result_hint_lines = (result_hint_value,) if result_hint_value else ('none',)

    return OperatorScreenView(
        project=project,
        mode_line='mode: local read-only operator surface over the canonical snapshot',
        status_line=f"status: {str(snapshot_status(snapshot) or 'unknown').upper()}",
        updated_line=f"updated: {snapshot_updated_at(snapshot) or 'unknown'}",
        notes=tuple(resolved.notes),
        sections=(
            OperatorScreenSection(title='current', lines=current_lines),
            OperatorScreenSection(title='queue', lines=tuple(queue_lines)),
            OperatorScreenSection(title='initiative', lines=initiative_lines),
            OperatorScreenSection(title='closure', lines=closure_lines),
            OperatorScreenSection(title='last completed', lines=last_completed_lines),
            OperatorScreenSection(title='warnings', lines=warning_lines),
            OperatorScreenSection(title='result hint', lines=result_hint_lines),
        ),
    )


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


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


def parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def parse_artifact(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} did not contain a JSON object")
    return data


def infer_state_dir(*, state_dir: str | None = None, project: str | None = None) -> Path:
    if state_dir:
        return Path(state_dir).expanduser().resolve()
    if project:
        return (DEFAULT_PROJECTS_ROOT / project).resolve()
    raise CliUsageError("provide --project or --state-dir")


def operator_snapshot_path(state_dir: Path) -> Path:
    return state_dir / OPERATOR_STATUS_FILENAME


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
    expected_branch_merged_into_base = None
    if base and expected_branch:
        import subprocess

        proc = subprocess.run(["git", "merge-base", "--is-ancestor", base, expected_branch], cwd=repo, capture_output=True, text=True)
        merge_base_ok = proc.returncode == 0 if proc.returncode in (0, 1) else None
        merged_proc = subprocess.run(["git", "merge-base", "--is-ancestor", expected_branch, base], cwd=repo, capture_output=True, text=True)
        expected_branch_merged_into_base = merged_proc.returncode == 0 if merged_proc.returncode in (0, 1) else None

    present = head is not None and branch is not None
    details = {
        "repoPath": str(repo),
        "inspectedAt": iso_now(),
        "branch": branch,
        "expectedBranch": expected_branch,
        "branchMatchesExpected": bool(branch and expected_branch and branch == expected_branch) if expected_branch else True,
        "base": base,
        "baseIsAncestorOfExpectedBranch": merge_base_ok,
        "expectedBranchIsAncestorOfBase": expected_branch_merged_into_base,
        "branchIsBase": bool(branch and base and branch == base) if base else False,
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
    return {
        "queueItemId": current.get("queueItemId"),
        "role": current.get("role"),
        "branch": current.get("queueItem", {}).get("branch") if isinstance(current.get("queueItem"), dict) else current.get("branch"),
        "startedAt": started_at,
        "ageSeconds": age_seconds,
        "runId": current.get("runId"),
        "sessionKey": current.get("sessionKey"),
        "resultPath": current.get("resultPath"),
    }


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

    closure_remediation = None
    if isinstance(loaded, dict):
        remediation = loaded.get("remediation") if isinstance(loaded.get("remediation"), dict) else None
        if remediation:
            closure_remediation = {
                "activeAttempt": remediation.get("activeAttempt"),
                "lastAttempt": remediation.get("lastAttempt"),
                "halted": remediation.get("halted") if isinstance(remediation.get("halted"), dict) else None,
            }

    status_message = status_message_summary(loaded or seed) if isinstance(loaded or seed, dict) else None
    return {
        "initiativeId": initiative_id,
        "phase": phase,
        "currentSubtaskId": current_subtask_id,
        "branch": branch,
        "base": base,
        "statePath": state_path,
        "statusMessage": status_message,
        "closureRemediation": closure_remediation,
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


def derive_closure_state(*, status: str | None, current: dict[str, Any] | None, queue: list[Any], initiative: dict[str, Any] | None) -> dict[str, Any]:
    """Derive the bounded closure/handoff taxonomy exposed to operators.

    This keeps closure semantics hierarchical rather than overloading the main
    operator status enum with every initiative phase.
    """
    status_value = str(status or "").strip() or None
    phase = str((initiative or {}).get("phase") or "").strip() or None
    remediation = (initiative or {}).get("closureRemediation") if isinstance((initiative or {}).get("closureRemediation"), dict) else None
    remediation_active = isinstance(remediation, dict) and (
        remediation.get("activeAttempt") is not None or isinstance(remediation.get("halted"), dict)
    )
    quiet = current is None and len(queue) == 0
    terminal_success = phase in {"completed", "closed"}
    closure_phases = {"review-manager", "replan-architect", "closure-merger"}

    if status_value in {"blocked", "conflicted"}:
        closure_state = "blocked"
        reason = "operator status is blocked/conflicted, so the initiative is not handoff-safe"
    elif phase in closure_phases or remediation_active:
        closure_state = "closure-active"
        reason = "initiative is in a closure-phase or closure remediation/passback follow-up"
    elif status_value == "idle-clean" and quiet and (initiative is None or terminal_success):
        closure_state = "idle-clean"
        reason = "runtime is quiet and no non-terminal initiative closure work remains"
    else:
        closure_state = "execution-active"
        reason = "initiative is still in design/execution or runtime work remains before closure is settled"

    handoff_safe = closure_state == "idle-clean"
    return {
        "state": closure_state,
        "handoffSafe": handoff_safe,
        "quiet": quiet,
        "initiativePhase": phase,
        "reason": reason,
        "policy": {
            "name": "agentrunner.closure-state-taxonomy",
            "version": 1,
            "sourceOfTruth": "operator_status.json.closure",
            "states": ["execution-active", "closure-active", "blocked", "idle-clean"],
            "closurePhases": ["review-manager", "replan-architect", "closure-merger"],
            "closureExecutionFollowUps": ["closure remediation", "proof hardening", "passback follow-up"],
            "handoffSafeRequires": [
                "closure.state == idle-clean",
                "closure.quiet == true",
                "initiative.phase absent or terminal-success",
            ],
        },
    }


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

    closure = derive_closure_state(
        status=reconciliation.get("decision"),
        current=current,
        queue=queue,
        initiative=initiative,
    )

    artifact = {
        "contract": dict(OPERATOR_SNAPSHOT_CONTRACT),
        "project": state.get("project") or state_dir.name,
        "status": reconciliation.get("decision"),
        "current": current,
        "queue": {
            "depth": len(queue),
            "nextIds": [str(item.get("id")) for item in queue if isinstance(item, dict) and item.get("id")][: max(0, queue_preview)],
            "preview": queue_preview_items,
        },
        "initiative": initiative,
        "closure": closure,
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
    path = operator_snapshot_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_operator_snapshot(
    state_dir: Path,
    *,
    queue_preview: int,
    tick_count: int,
    rebuild_missing: bool,
    rebuild_malformed: bool,
    write_rebuild: bool,
    build_status_artifact: BuildArtifact | None = None,
    write_status_artifact: WriteArtifact | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Load the canonical operator snapshot, with explicit bounded rebuild fallback.

    The loader itself is read-only. Rebuild/write only occurs when the caller has
    explicitly opted into the bounded fallback path.
    """
    notes: list[str] = []
    artifact_path = operator_snapshot_path(state_dir)
    artifact: dict[str, Any] | None = None
    build_fn = build_status_artifact or globals()["build_status_artifact"]
    write_fn = write_status_artifact or globals()["write_status_artifact"]

    if artifact_path.exists():
        try:
            artifact = parse_artifact(artifact_path)
        except Exception as exc:
            notes.append(f"warning: {OPERATOR_STATUS_FILENAME} is malformed: {clip(exc, 160)}")
            if rebuild_malformed:
                artifact = build_fn(state_dir, queue_preview=queue_preview, tick_count=tick_count)
                notes.append("info: rebuilt operator status from mechanics files because --rebuild-malformed was set")
                if write_rebuild:
                    write_fn(state_dir, artifact)
                    notes.append(f"info: refreshed {artifact_path}")
            else:
                notes.append("hint: rerun with --rebuild-malformed to use the bounded manual fallback")
    else:
        notes.append(f"warning: operator status artifact missing at {artifact_path}")
        if rebuild_missing:
            artifact = build_fn(state_dir, queue_preview=queue_preview, tick_count=tick_count)
            notes.append("info: rebuilt operator status from mechanics files because --rebuild-missing was set")
            if write_rebuild:
                write_fn(state_dir, artifact)
                notes.append(f"info: wrote {artifact_path}")
        else:
            notes.append("hint: rerun with --rebuild-missing for a bounded manual rebuild")

    return artifact, notes


def resolve_operator_snapshot(
    *,
    state_dir: str | Path | None = None,
    project: str | None = None,
    queue_preview: int = 3,
    tick_count: int = 3,
    rebuild_missing: bool = False,
    rebuild_malformed: bool = False,
    write_rebuild: bool = False,
    build_status_artifact: BuildArtifact | None = None,
    write_status_artifact: WriteArtifact | None = None,
) -> OperatorSnapshotRead:
    """Resolve a project/state-dir and load the canonical operator snapshot.

    This is the smallest read-model seam for non-CLI consumers: it resolves the
    runtime location, returns the canonical artifact path, and preserves bounded
    rebuild notes as structured data instead of human-formatted CLI output.
    """
    resolved_state_dir = infer_state_dir(
        state_dir=str(state_dir) if state_dir is not None else None,
        project=project,
    )
    artifact, notes = load_operator_snapshot(
        resolved_state_dir,
        queue_preview=queue_preview,
        tick_count=tick_count,
        rebuild_missing=rebuild_missing,
        rebuild_malformed=rebuild_malformed,
        write_rebuild=write_rebuild,
        build_status_artifact=build_status_artifact,
        write_status_artifact=write_status_artifact,
    )
    return OperatorSnapshotRead(
        state_dir=resolved_state_dir,
        artifact_path=operator_snapshot_path(resolved_state_dir),
        artifact=artifact,
        notes=tuple(notes),
    )
