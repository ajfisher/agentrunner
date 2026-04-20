#!/usr/bin/env python3
"""Discord-backed initiative status message adapter.

This module is intentionally narrow:
- it sits behind the shared initiative-status contract
- it uses the existing OpenClaw `message` tool seam instead of bespoke HTTP/API clients
- it returns normalized durable handles so later lifecycle updates can edit the same message
- delivery failures degrade to compact error metadata instead of interrupting initiative execution
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
    from .initiative_status import apply_status_message_delivery, clip, normalize_message_handle
except ImportError:  # pragma: no cover - script-mode fallback
    from initiative_status import apply_status_message_delivery, clip, normalize_message_handle

DISCORD_ADAPTER = "discord"
DEFAULT_CHANNEL = "discord"
DEFAULT_TITLE = "AgentRunner Initiative Status"

GatewayInvokeFn = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class DiscordStatusMessageResult:
    ok: bool
    operation: str
    action: str
    target: dict[str, Any]
    handle: dict[str, Any] | None
    message: str
    response: dict[str, Any] | None
    error: str | None = None


def load_discord_status_target(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    metadata = cfg.get("metadata") if isinstance(cfg.get("metadata"), dict) else {}
    target = {
        "channel": str(cfg.get("channel") or DEFAULT_CHANNEL).strip() or DEFAULT_CHANNEL,
        "target": clip(cfg.get("target") or cfg.get("to"), 160),
        "threadId": clip(cfg.get("threadId") or cfg.get("thread_id"), 80),
        "messageId": clip(cfg.get("messageId") or cfg.get("message_id"), 80),
        "title": clip(cfg.get("title") or DEFAULT_TITLE, 120),
        "metadata": {str(k): v for k, v in metadata.items() if isinstance(k, str) and str(k).strip()},
    }
    return {k: v for k, v in target.items() if v not in (None, {}, "")}


def merge_status_target(base: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    merged = load_discord_status_target(base)
    extra = load_discord_status_target(override)
    metadata = dict(merged.get("metadata") or {})
    metadata.update(extra.get("metadata") or {})
    merged.update({k: v for k, v in extra.items() if k != "metadata"})
    if metadata:
        merged["metadata"] = metadata
    elif "metadata" in merged:
        merged.pop("metadata", None)
    return merged


def _first_dict(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _gateway_response_error(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None

    failure_flag = False
    if response.get("ok") is False or response.get("success") is False:
        failure_flag = True
    nested = _first_dict(response.get("error"), response.get("err"), response.get("details"))
    if isinstance(nested, dict) and (nested.get("ok") is False or nested.get("success") is False):
        failure_flag = True

    if not failure_flag:
        return None

    parts: list[str] = []
    for value in (
        response.get("error"),
        response.get("message"),
        response.get("detail"),
        response.get("reason"),
        response.get("code"),
    ):
        text = clip(value, 120)
        if text and text not in parts:
            parts.append(text)

    if isinstance(nested, dict):
        for value in (
            nested.get("message"),
            nested.get("detail"),
            nested.get("reason"),
            nested.get("code"),
        ):
            text = clip(value, 120)
            if text and text not in parts:
                parts.append(text)

    return " | ".join(parts[:3]) or "discord status-message delivery failed"


def normalize_discord_message_handle(raw: Any, *, fallback_target: dict[str, Any] | None = None) -> dict[str, Any] | None:
    target = fallback_target if isinstance(fallback_target, dict) else {}
    candidate = raw
    if isinstance(raw, dict):
        candidate = _first_dict(raw.get("message"), raw.get("result"), raw.get("data"), raw.get("response")) or raw
    handle = normalize_message_handle(candidate)
    if handle is None and isinstance(candidate, dict):
        nested = _first_dict(candidate.get("message"), candidate.get("result"), candidate.get("data"), candidate.get("response"))
        handle = normalize_message_handle(nested)
    if handle is None and isinstance(raw, dict):
        handle = normalize_message_handle(raw)
    if handle is None:
        return None

    merged = dict(handle)
    if not merged.get("provider"):
        merged["provider"] = DISCORD_ADAPTER
    if not merged.get("channelId") and isinstance(target.get("target"), str):
        target_value = str(target.get("target") or "")
        if target_value.startswith("channel:"):
            merged["channelId"] = target_value.split(":", 1)[1] or merged.get("channelId")
    if not merged.get("threadId") and isinstance(target.get("threadId"), str):
        merged["threadId"] = target.get("threadId")
    return {k: v for k, v in merged.items() if isinstance(v, str) and v.strip()}


def render_discord_status_message(event: dict[str, Any], *, title: str | None = None) -> str:
    initiative = event.get("initiative") if isinstance(event.get("initiative"), dict) else {}
    queue_item = event.get("queueItem") if isinstance(event.get("queueItem"), dict) else {}
    result = event.get("result") if isinstance(event.get("result"), dict) else {}

    initiative_id = initiative.get("initiativeId") or "unknown-initiative"
    phase = initiative.get("phase") or "unknown"
    subtask = initiative.get("currentSubtaskId") or "-"
    lifecycle = event.get("lifecycleEvent") or "status_update"
    summary = clip(event.get("summary"), 220) or "No summary provided."
    blocked_reason = clip(event.get("blockedReason"), 220)

    lines = [f"**{title or DEFAULT_TITLE}**"]
    lines.append(f"- Initiative: `{initiative_id}`")
    lines.append(f"- Lifecycle: `{lifecycle}`")
    lines.append(f"- Phase: `{phase}` | Subtask: `{subtask}`")

    role = queue_item.get("role")
    queue_item_id = queue_item.get("queueItemId")
    if role or queue_item_id:
        bits = [bit for bit in (queue_item_id, role) if isinstance(bit, str) and bit.strip()]
        if bits:
            lines.append(f"- Current item: {' | '.join(bits)}")

    result_bits: list[str] = []
    if isinstance(result.get("status"), str) and result.get("status"):
        result_bits.append(f"status={result['status']}")
    if isinstance(result.get("commit"), str) and result.get("commit"):
        result_bits.append(f"commit={result['commit'][:12]}")
    if result.get("approved") is True:
        result_bits.append("approved=yes")
    if result.get("merged") is True:
        result_bits.append("merged=yes")
    elif result.get("merged") is False:
        result_bits.append("merged=no")
    if result_bits:
        lines.append(f"- Result: {' | '.join(result_bits)}")

    lines.append(f"- Summary: {summary}")
    if blocked_reason:
        lines.append(f"- Blocked: {blocked_reason}")
    lines.append(f"- Updated: {event.get('writtenAt')}")
    return "\n".join(lines)


def _build_send_args(target: dict[str, Any], message: str) -> dict[str, Any]:
    args = {
        "action": "send",
        "channel": str(target.get("channel") or DEFAULT_CHANNEL),
        "message": message,
    }
    if target.get("target"):
        args["target"] = target["target"]
    if target.get("threadId"):
        args["threadId"] = target["threadId"]
    return args


def _build_edit_args(target: dict[str, Any], handle: dict[str, Any], message: str) -> dict[str, Any]:
    args = {
        "action": "edit",
        "channel": str(target.get("channel") or DEFAULT_CHANNEL),
        "message": message,
        "messageId": handle.get("id"),
    }
    if target.get("target"):
        args["target"] = target["target"]
    channel_id = handle.get("channelId") or target.get("channelId")
    if channel_id:
        args["channelId"] = channel_id
    thread_id = handle.get("threadId") or target.get("threadId")
    if thread_id:
        args["threadId"] = thread_id
    return args


def deliver_discord_status_message(
    *,
    operation: str,
    event: dict[str, Any],
    target: dict[str, Any] | None,
    invoke_gateway: GatewayInvokeFn,
    existing_handle: dict[str, Any] | None = None,
) -> DiscordStatusMessageResult:
    resolved_target = load_discord_status_target(target)
    message = render_discord_status_message(event, title=resolved_target.get("title"))

    if operation == "create":
        action = "send"
        args = _build_send_args(resolved_target, message)
    elif operation in {"update", "finalize"}:
        if not isinstance(existing_handle, dict) or not existing_handle.get("id"):
            return DiscordStatusMessageResult(
                ok=False,
                operation=operation,
                action="edit",
                target=resolved_target,
                handle=None,
                message=message,
                response=None,
                error="cannot edit initiative status message without a persisted handle id",
            )
        action = "edit"
        args = _build_edit_args(resolved_target, existing_handle, message)
    else:  # pragma: no cover - guarded by shared contract callers
        return DiscordStatusMessageResult(
            ok=False,
            operation=operation,
            action="unknown",
            target=resolved_target,
            handle=None,
            message=message,
            response=None,
            error=f"unsupported discord status-message operation: {operation}",
        )

    try:
        response = invoke_gateway("message", args)
    except Exception as exc:
        return DiscordStatusMessageResult(
            ok=False,
            operation=operation,
            action=action,
            target=resolved_target,
            handle=existing_handle,
            message=message,
            response=None,
            error=clip(exc, 240) or "discord status-message delivery failed",
        )

    response_payload = response if isinstance(response, dict) else {"result": response}
    response_error = _gateway_response_error(response_payload)
    handle = normalize_discord_message_handle(response_payload, fallback_target=resolved_target)
    if handle is None and action == "edit" and isinstance(existing_handle, dict):
        handle = normalize_discord_message_handle(existing_handle, fallback_target=resolved_target)
    if response_error:
        return DiscordStatusMessageResult(
            ok=False,
            operation=operation,
            action=action,
            target=resolved_target,
            handle=handle,
            message=message,
            response=response_payload,
            error=response_error,
        )
    return DiscordStatusMessageResult(
        ok=True,
        operation=operation,
        action=action,
        target=resolved_target,
        handle=handle,
        message=message,
        response=response_payload,
        error=None,
    )


def apply_discord_status_message(
    initiative_state: dict[str, Any],
    *,
    operation: str,
    lifecycle_event: str,
    event: dict[str, Any],
    invoke_gateway: GatewayInvokeFn,
    target: dict[str, Any] | None = None,
) -> DiscordStatusMessageResult:
    current = initiative_state.get("statusMessage") if isinstance(initiative_state.get("statusMessage"), dict) else {}
    resolved_target = merge_status_target(current.get("target") if isinstance(current, dict) else None, target)
    existing_handle = current.get("handle") if isinstance(current.get("handle"), dict) else None
    delivery_result = deliver_discord_status_message(
        operation=operation,
        event=event,
        target=resolved_target,
        existing_handle=existing_handle,
        invoke_gateway=invoke_gateway,
    )
    apply_status_message_delivery(
        initiative_state,
        operation=operation,
        lifecycle_event=lifecycle_event,
        adapter=DISCORD_ADAPTER,
        target=resolved_target,
        handle=delivery_result.handle,
        delivery_metadata={
            "channel": resolved_target.get("channel"),
            "title": resolved_target.get("title"),
            "lastAction": delivery_result.action,
            "lastResponseOk": delivery_result.ok,
        },
        error=delivery_result.error,
        event=event,
    )
    return delivery_result
