#!/usr/bin/env python3
"""Shared contract + persistence helpers for initiative status messages.

This module defines the compact mechanics-owned contract for initiative status
messaging without binding the core lifecycle to a specific chat provider.
Concrete adapters (Discord first, later Telegram/Slack/etc.) should implement
three operations over the same payload family:
- create: emit the first initiative status message and return a stable handle
- update: edit/refresh the existing initiative status message in place
- finalize: write the terminal initiative state and mark the handle finalized

Important boundaries:
- initiative execution must remain correct even if status-message delivery fails
- persistence is initiative-local (initiatives/<id>/state.json), not main state
- adapters persist a normalized message handle plus delivery metadata so future
  updates do not fork into multiple messages accidentally
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

STATUS_MESSAGE_CONTRACT = {
    "name": "agentrunner.initiative-status-message",
    "version": 1,
}

VALID_STATUS_MESSAGE_OPERATIONS = ("create", "update", "finalize")
VALID_STATUS_LIFECYCLE_EVENTS = (
    "initiative_activated",
    "initiative_phase_changed",
    "subtask_started",
    "review_approved",
    "review_blocked",
    "remediation_queued",
    "merge_blocked",
    "merge_completed",
    "initiative_completed",
    "initiative_blocked",
    "initiative_failed",
)


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def clip(value: Any, limit: int = 280) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def default_status_message_state(*, initiative_id: str | None, branch: str | None = None, base: str | None = None) -> dict[str, Any]:
    return {
        "contract": dict(STATUS_MESSAGE_CONTRACT),
        "initiativeId": initiative_id,
        "branch": branch,
        "base": base,
        "adapter": None,
        "target": None,
        "handle": None,
        "delivery": {
            "createdAt": None,
            "updatedAt": None,
            "finalizedAt": None,
            "status": "idle",
            "lastOperation": None,
            "lastError": None,
            "providerMessageId": None,
            "providerChannelId": None,
            "providerThreadId": None,
            "metadata": {},
        },
        "lastEvent": None,
        "history": [],
    }


def ensure_status_message_state(initiative_state: dict[str, Any]) -> dict[str, Any]:
    current = initiative_state.get("statusMessage") if isinstance(initiative_state.get("statusMessage"), dict) else {}
    seeded = default_status_message_state(
        initiative_id=initiative_state.get("initiativeId"),
        branch=initiative_state.get("branch"),
        base=initiative_state.get("base"),
    )
    merged = deepcopy(seeded)
    merged.update({k: v for k, v in current.items() if k in merged and k not in {"delivery", "history"}})

    delivery = deepcopy(seeded["delivery"])
    raw_delivery = current.get("delivery") if isinstance(current.get("delivery"), dict) else {}
    delivery.update({k: v for k, v in raw_delivery.items() if k in delivery})
    if not isinstance(delivery.get("metadata"), dict):
        delivery["metadata"] = {}
    merged["delivery"] = delivery

    history = current.get("history") if isinstance(current.get("history"), list) else []
    merged["history"] = [item for item in history if isinstance(item, dict)][-12:]
    initiative_state["statusMessage"] = merged
    return merged


def build_status_message_event(
    *,
    operation: str,
    lifecycle_event: str,
    initiative_state: dict[str, Any],
    summary: str | None = None,
    queue_item: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    if operation not in VALID_STATUS_MESSAGE_OPERATIONS:
        raise ValueError(f"unsupported status-message operation: {operation}")
    if lifecycle_event not in VALID_STATUS_LIFECYCLE_EVENTS:
        raise ValueError(f"unsupported status-message lifecycle event: {lifecycle_event}")

    event = {
        "contract": dict(STATUS_MESSAGE_CONTRACT),
        "operation": operation,
        "lifecycleEvent": lifecycle_event,
        "initiative": {
            "initiativeId": initiative_state.get("initiativeId"),
            "phase": initiative_state.get("phase"),
            "currentSubtaskId": initiative_state.get("currentSubtaskId"),
            "branch": initiative_state.get("branch"),
            "base": initiative_state.get("base"),
        },
        "summary": clip(summary, 240),
        "blockedReason": clip(blocked_reason, 240),
        "queueItem": {
            "queueItemId": queue_item.get("id") if isinstance(queue_item, dict) else None,
            "role": queue_item.get("role") if isinstance(queue_item, dict) else None,
            "goal": clip(queue_item.get("goal"), 160) if isinstance(queue_item, dict) else None,
        },
        "result": {
            "status": result.get("status") if isinstance(result, dict) else None,
            "commit": result.get("commit") if isinstance(result, dict) else None,
            "merged": result.get("merged") if isinstance(result, dict) else None,
            "approved": result.get("approved") if isinstance(result, dict) else None,
            "summary": clip(result.get("summary"), 200) if isinstance(result, dict) else None,
        },
        "writtenAt": iso_now(),
    }
    return event


def normalize_message_handle(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip():
        return {"id": raw.strip()}
    if not isinstance(raw, dict):
        return None
    handle = {
        "id": raw.get("id") or raw.get("messageId") or raw.get("message_id"),
        "channelId": raw.get("channelId") or raw.get("channel_id"),
        "threadId": raw.get("threadId") or raw.get("thread_id"),
        "provider": raw.get("provider") or raw.get("channel"),
        "url": raw.get("url"),
    }
    handle = {k: v for k, v in handle.items() if isinstance(v, str) and v.strip()}
    return handle or None


def apply_status_message_delivery(
    initiative_state: dict[str, Any],
    *,
    operation: str,
    lifecycle_event: str,
    adapter: str | None,
    target: dict[str, Any] | None = None,
    handle: dict[str, Any] | str | None = None,
    delivery_metadata: dict[str, Any] | None = None,
    error: str | None = None,
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = ensure_status_message_state(initiative_state)
    state["adapter"] = adapter or state.get("adapter")
    if isinstance(target, dict) and target:
        state["target"] = deepcopy(target)

    normalized_handle = normalize_message_handle(handle)
    if normalized_handle is not None:
        state["handle"] = normalized_handle

    delivery = state["delivery"]
    now = iso_now()
    delivery["lastOperation"] = operation
    delivery["updatedAt"] = now
    if operation == "create" and normalized_handle is not None and not delivery.get("createdAt"):
        delivery["createdAt"] = now
    if operation == "finalize":
        delivery["finalizedAt"] = now

    if error:
        delivery["status"] = "error"
        delivery["lastError"] = clip(error, 240)
    else:
        delivery["status"] = "finalized" if operation == "finalize" else "active"
        delivery["lastError"] = None

    if normalized_handle is not None:
        delivery["providerMessageId"] = normalized_handle.get("id") or delivery.get("providerMessageId")
        delivery["providerChannelId"] = normalized_handle.get("channelId") or delivery.get("providerChannelId")
        delivery["providerThreadId"] = normalized_handle.get("threadId") or delivery.get("providerThreadId")

    if isinstance(delivery_metadata, dict) and delivery_metadata:
        metadata = delivery.get("metadata") if isinstance(delivery.get("metadata"), dict) else {}
        metadata.update(delivery_metadata)
        delivery["metadata"] = metadata

    event_record = {
        "operation": operation,
        "lifecycleEvent": lifecycle_event,
        "adapter": state.get("adapter"),
        "status": delivery.get("status"),
        "handle": deepcopy(state.get("handle")),
        "error": delivery.get("lastError"),
        "writtenAt": now,
    }
    if isinstance(event, dict) and event:
        state["lastEvent"] = deepcopy(event)
        event_record["eventSummary"] = event.get("summary")
        event_record["phase"] = event.get("initiative", {}).get("phase") if isinstance(event.get("initiative"), dict) else None
    state["history"] = [*state.get("history", []), event_record][-12:]
    return state


def status_message_summary(initiative_state: dict[str, Any]) -> dict[str, Any] | None:
    state = ensure_status_message_state(initiative_state)
    handle = state.get("handle") if isinstance(state.get("handle"), dict) else None
    delivery = state.get("delivery") if isinstance(state.get("delivery"), dict) else {}
    if not handle and delivery.get("status") == "idle" and not state.get("lastEvent"):
        return None
    return {
        "adapter": state.get("adapter"),
        "status": delivery.get("status"),
        "messageId": handle.get("id") if handle else None,
        "channelId": handle.get("channelId") if handle else None,
        "updatedAt": delivery.get("updatedAt"),
        "finalizedAt": delivery.get("finalizedAt"),
        "lastOperation": delivery.get("lastOperation"),
        "lastError": delivery.get("lastError"),
        "lastLifecycleEvent": (state.get("lastEvent") or {}).get("lifecycleEvent") if isinstance(state.get("lastEvent"), dict) else None,
    }
