#!/usr/bin/env python3
"""Canonical runtime state reconciliation policy for operator-facing status.

This module is intentionally stdlib-only and read-only. It reconciles several
candidate truth sources into a stable operator decision plus machine-readable
reasons. It does not mutate mechanics state.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

STALE_RUN_AFTER = timedelta(minutes=12)
STALE_STATE_AFTER = timedelta(minutes=12)


def parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _reason(*, code: str, source: str, summary: str, precedence: int, severity: str = "info", details: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "source": source,
        "severity": severity,
        "summary": summary,
        "details": details,
        "precedence": precedence,
    }


def _source(*, name: str, present: bool, precedence: int, freshness: str, authority: str, details: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "present": present,
        "precedence": precedence,
        "freshness": freshness,
        "authority": authority,
        "details": details,
    }


def reconcile_runtime_state(
    *,
    now: datetime,
    state: dict[str, Any],
    queue: list[Any],
    ticks: list[dict[str, Any]],
    current: dict[str, Any] | None,
    initiative: dict[str, Any] | None,
    last_completed: dict[str, Any] | None,
    live_repo: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the canonical reconciliation decision.

    Decisions are intentionally stable and explicit:
    - conflicted: sources disagree or mechanics state is internally inconsistent
    - blocked: runtime is blocked/stale or last completed item ended blocked
    - active: mechanics says a run is active and the claim is fresh/consistent
    - idle-pending: nothing active, but queued work or non-terminal closure follow-up still exists
    - idle-clean: nothing active and no queued work or closure follow-up remains
    """
    running_flag = bool(state.get("running"))
    queue_depth = len(queue)
    state_updated = parse_iso(state.get("updatedAt"))
    current_started = parse_iso((current or {}).get("startedAt"))
    current_age_seconds = max(0, int((now - current_started).total_seconds())) if current_started else None
    state_age_seconds = max(0, int((now - state_updated).total_seconds())) if state_updated else None
    last_completed_status = str((last_completed or {}).get("status") or "").lower()
    current_queue_item_id = (current or {}).get("queueItemId")
    repo_present = bool(live_repo and live_repo.get("present"))
    repo_freshness = str((live_repo or {}).get("freshness") or "missing")
    repo_details = (live_repo or {}).get("details") if isinstance((live_repo or {}).get("details"), dict) else {}
    repo_clean = bool(repo_details.get("cleanWorktree"))
    repo_head_present = bool(repo_details.get("headPresent"))
    repo_branch_matches = bool(repo_details.get("branchMatchesExpected"))
    repo_branch_is_base = bool(repo_details.get("branchIsBase"))
    repo_expected_branch_merged_into_base = bool(repo_details.get("expectedBranchIsAncestorOfBase"))
    repo_satisfies_clean_tail_override = repo_branch_matches or (
        repo_branch_is_base and repo_expected_branch_merged_into_base
    )
    queued_ids = {str(item.get("id")) for item in queue if isinstance(item, dict) and item.get("id")}
    recent_tick_qid = ticks[-1].get("queueItemId") if ticks and isinstance(ticks[-1], dict) else None
    initiative_phase = str((initiative or {}).get("phase") or "").strip() or None
    closure_remediation = (initiative or {}).get("closureRemediation") if isinstance((initiative or {}).get("closureRemediation"), dict) else None
    closure_remediation_active = isinstance(closure_remediation, dict) and (
        closure_remediation.get("activeAttempt") is not None or isinstance(closure_remediation.get("halted"), dict)
    )
    closure_follow_up_pending = initiative_phase in {"review-manager", "replan-architect", "closure-merger"} or closure_remediation_active

    current_freshness = "missing"
    if current_started is not None:
        current_freshness = "stale" if (now - current_started) >= STALE_RUN_AFTER else "fresh"
    state_freshness = "missing"
    if state_updated is not None:
        state_freshness = "stale" if (now - state_updated) >= STALE_STATE_AFTER else "fresh"

    sources = [
        _source(
            name="runtime_state",
            present=bool(state),
            precedence=1,
            freshness=state_freshness,
            authority="mechanics lock/current pointer",
            details={
                "running": running_flag,
                "updatedAt": state.get("updatedAt"),
                "ageSeconds": state_age_seconds,
            },
        ),
        _source(
            name="live_runtime",
            present=current is not None,
            precedence=2,
            freshness=current_freshness,
            authority="state.current active run claim",
            details={
                "queueItemId": current_queue_item_id,
                "startedAt": (current or {}).get("startedAt"),
                "ageSeconds": current_age_seconds,
            },
        ),
        _source(
            name="queue",
            present=True,
            precedence=3,
            freshness="fresh",
            authority="materialized backlog view",
            details={"depth": queue_depth, "nextIds": sorted(queued_ids)[:5]},
        ),
        _source(
            name="live_repo",
            present=repo_present,
            precedence=4,
            freshness=repo_freshness,
            authority="live git/worktree inspection",
            details=repo_details or None,
        ),
        _source(
            name="initiative",
            present=initiative is not None,
            precedence=5,
            freshness="contextual",
            authority="initiative pointer/context",
            details={
                "initiativeId": (initiative or {}).get("initiativeId"),
                "phase": (initiative or {}).get("phase"),
            },
        ),
        _source(
            name="recent_ticks",
            present=bool(ticks),
            precedence=6,
            freshness="recent" if ticks else "missing",
            authority="append-only completion history",
            details={"count": len(ticks), "latestQueueItemId": recent_tick_qid},
        ),
        _source(
            name="result_artifacts",
            present=last_completed is not None,
            precedence=7,
            freshness="recent" if last_completed else "missing",
            authority="last completed run/result summary",
            details={
                "queueItemId": (last_completed or {}).get("queueItemId"),
                "status": (last_completed or {}).get("status"),
            },
        ),
    ]

    reasons: list[dict[str, Any]] = []

    if running_flag and current is None:
        reasons.append(_reason(
            code="running_without_current",
            source="runtime_state",
            severity="error",
            summary="state.json marks the project running, but current run details are missing",
            details={"running": running_flag},
            precedence=1,
        ))
    if current is not None and not running_flag:
        reasons.append(_reason(
            code="current_without_running",
            source="runtime_state",
            severity="error",
            summary="state.current exists, but the running flag is false",
            details={"queueItemId": current_queue_item_id},
            precedence=1,
        ))
    if current_queue_item_id and current_queue_item_id in queued_ids:
        reasons.append(_reason(
            code="current_item_still_queued",
            source="queue",
            severity="error",
            summary="the active queue item is also still present in the queued backlog",
            details={"queueItemId": current_queue_item_id},
            precedence=1,
        ))
    if running_flag and current_started is None:
        reasons.append(_reason(
            code="current_missing_started_at",
            source="live_runtime",
            severity="error",
            summary="running work has no valid startedAt timestamp, so freshness cannot be reconciled",
            details={"queueItemId": current_queue_item_id},
            precedence=1,
        ))

    if reasons:
        decision = "conflicted"
    elif running_flag and current is not None and current_freshness == "stale":
        reasons.append(_reason(
            code="stale_run",
            source="live_runtime",
            severity="warning",
            summary=f"current run has been active for {current_age_seconds}s without completion",
            details={"queueItemId": current_queue_item_id, "ageSeconds": current_age_seconds},
            precedence=2,
        ))
        decision = "blocked"
    elif (
        last_completed_status == "blocked"
        and queue_depth == 0
        and not running_flag
        and current is None
        and repo_present
        and repo_freshness == "fresh"
        and repo_clean
        and repo_head_present
        and repo_satisfies_clean_tail_override
    ):
        reasons.append(_reason(
            code="live_repo_clean_overrides_stale_blocked_artifact",
            source="live_repo",
            severity="info",
            summary="live repo truth is clean/current, so it outranks a stale blocked completion artifact",
            details={
                "queueItemId": (last_completed or {}).get("queueItemId"),
                "repoPath": repo_details.get("repoPath"),
                "head": repo_details.get("head"),
                "branch": repo_details.get("branch"),
                "branchIsBase": repo_details.get("branchIsBase"),
                "expectedBranchIsAncestorOfBase": repo_details.get("expectedBranchIsAncestorOfBase"),
            },
            precedence=3,
        ))
        decision = "idle-clean"
    elif last_completed_status == "blocked":
        reasons.append(_reason(
            code="last_completed_blocked",
            source="result_artifacts",
            severity="warning",
            summary="most recent completed item ended blocked",
            details={"queueItemId": (last_completed or {}).get("queueItemId")},
            precedence=4,
        ))
        decision = "blocked"
    elif running_flag and current is not None:
        reasons.append(_reason(
            code="active_run",
            source="live_runtime",
            severity="info",
            summary="runtime lock and active run details agree on a live in-flight item",
            details={"queueItemId": current_queue_item_id, "ageSeconds": current_age_seconds},
            precedence=5,
        ))
        decision = "active"
    elif queue_depth > 0:
        if state_freshness == "stale":
            reasons.append(_reason(
                code="stale_status_with_backlog",
                source="runtime_state",
                severity="warning",
                summary="queue has pending work but runtime state has not been refreshed recently",
                details={"queueDepth": queue_depth, "ageSeconds": state_age_seconds},
                precedence=5,
            ))
        else:
            reasons.append(_reason(
                code="pending_queue",
                source="queue",
                severity="info",
                summary="queued work is present, but nothing is actively running right now",
                details={"queueDepth": queue_depth},
                precedence=6,
            ))
        decision = "idle-pending"
    elif closure_follow_up_pending:
        reasons.append(_reason(
            code="closure_follow_up_pending",
            source="initiative",
            severity="info",
            summary="runtime is quiet, but non-terminal closure follow-up still remains before handoff is clean",
            details={
                "initiativeId": (initiative or {}).get("initiativeId"),
                "phase": initiative_phase,
                "closureRemediationActive": closure_remediation_active,
            },
            precedence=6,
        ))
        decision = "idle-pending"
    else:
        reasons.append(_reason(
            code="idle_clean",
            source="queue",
            severity="info",
            summary="no active run, no queued work, and no blocking completion state is visible",
            details=None,
            precedence=7,
        ))
        decision = "idle-clean"

    rank = {"conflicted": 0, "blocked": 1, "active": 2, "idle-pending": 3, "idle-clean": 4}
    sorted_reasons = sorted(
        reasons,
        key=lambda item: (int(item.get("precedence") or 999), int(rank.get(decision, 999))),
    )

    return {
        "decision": decision,
        "summary": sorted_reasons[0]["summary"] if sorted_reasons else decision,
        "reasons": sorted_reasons,
        "sources": sources,
        "policy": {
            "name": "canonical_runtime_reconciliation",
            "version": 2,
            "freshness": {
                "staleRunAfterSeconds": int(STALE_RUN_AFTER.total_seconds()),
                "staleStateAfterSeconds": int(STALE_STATE_AFTER.total_seconds()),
            },
            "precedenceOrder": [
                "integrity_conflicts",
                "stale_active_runtime",
                "live_repo_clean_overrides_stale_blocked_artifact",
                "last_completed_blocked",
                "active_runtime_lock",
                "queued_backlog_without_active_run",
                "closure_follow_up_without_live_queue",
                "idle_clean",
            ],
        },
    }
