#!/usr/bin/env python3
"""Optional MQTT broadcast seam for canonical operator snapshots.

This module is intentionally narrow:
- it derives payloads from the canonical operator snapshot/read-model
- it is safe to leave disabled
- publish failures degrade to notes/logging rather than altering mechanics flow

Real network delivery is kept behind a tiny publisher callable seam so tests can
prove payload shape without requiring a broker.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from .operator_data import (
        OperatorSnapshotRead,
        clip,
        iso_now,
        resolve_operator_snapshot,
        snapshot_current,
        snapshot_initiative,
        snapshot_last_completed,
        snapshot_project,
        snapshot_queue,
        snapshot_reconciliation,
        snapshot_status,
        snapshot_updated_at,
        snapshot_warnings,
    )
except ImportError:  # pragma: no cover - script-mode fallback
    from operator_data import (
        OperatorSnapshotRead,
        clip,
        iso_now,
        resolve_operator_snapshot,
        snapshot_current,
        snapshot_initiative,
        snapshot_last_completed,
        snapshot_queue,
        snapshot_project,
        snapshot_reconciliation,
        snapshot_status,
        snapshot_updated_at,
        snapshot_warnings,
    )

MQTT_SNAPSHOT_CONTRACT = {
    "name": "agentrunner.operator-mqtt-snapshot",
    "version": 1,
}
DEFAULT_TOPIC_PREFIX = "agentrunner/operator"
PUBLISH_STATE_FILENAME = "operator_mqtt_publish_state.json"

PublishFn = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class OperatorMqttPublishResult:
    enabled: bool
    attempted: bool
    changed: bool
    published: bool
    topic: str | None
    note: str
    payload: dict[str, Any] | None = None


def load_operator_mqtt_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    broker = cfg.get("broker") if isinstance(cfg.get("broker"), dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "broker": {
            "host": broker.get("host") if isinstance(broker.get("host"), str) and broker.get("host").strip() else None,
            "port": int(broker.get("port", 1883)) if str(broker.get("port", 1883)).strip() else 1883,
            "usernameEnv": broker.get("usernameEnv") if isinstance(broker.get("usernameEnv"), str) and broker.get("usernameEnv").strip() else None,
            "passwordEnv": broker.get("passwordEnv") if isinstance(broker.get("passwordEnv"), str) and broker.get("passwordEnv").strip() else None,
        },
        "topicPrefix": str(cfg.get("topicPrefix") or DEFAULT_TOPIC_PREFIX).strip() or DEFAULT_TOPIC_PREFIX,
        "qos": int(cfg.get("qos", 1)),
        "retain": bool(cfg.get("retain", True)),
    }


def publish_state_path(state_dir: Path) -> Path:
    return state_dir / PUBLISH_STATE_FILENAME


def load_publish_state(state_dir: Path) -> dict[str, Any]:
    path = publish_state_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_publish_state(state_dir: Path, obj: dict[str, Any]) -> Path:
    path = publish_state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def snapshot_subset(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Derive the MQTT snapshot body from canonical snapshot accessors only."""
    return {
        "status": snapshot_status(snapshot),
        "current": snapshot_current(snapshot),
        "queue": snapshot_queue(snapshot),
        "initiative": snapshot_initiative(snapshot),
        "lastCompleted": snapshot_last_completed(snapshot),
        "warnings": snapshot_warnings(snapshot),
        "reconciliation": snapshot_reconciliation(snapshot),
        "updatedAt": snapshot_updated_at(snapshot),
    }


def build_publish_payload(snapshot_read: OperatorSnapshotRead) -> dict[str, Any] | None:
    artifact = snapshot_read.artifact
    if not isinstance(artifact, dict):
        return None
    return {
        "contract": dict(MQTT_SNAPSHOT_CONTRACT),
        "project": snapshot_project(artifact),
        "publishedAt": iso_now(),
        "source": {
            "kind": "operator_status.json",
            "path": str(snapshot_read.artifact_path),
        },
        "snapshot": snapshot_subset(artifact),
    }


def snapshot_fingerprint(payload: dict[str, Any]) -> str:
    stable = {
        "project": payload.get("project"),
        "source": payload.get("source"),
        "snapshot": payload.get("snapshot"),
        "contract": payload.get("contract"),
    }
    return json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def publish_topic(*, topic_prefix: str, project: str) -> str:
    return f"{topic_prefix.rstrip('/')}/{project}/snapshot"


def mosquitto_publish(request: dict[str, Any]) -> None:
    mqtt_bin = shutil.which("mosquitto_pub")
    if not mqtt_bin:
        raise RuntimeError("mosquitto_pub not available")

    broker = request.get("broker") if isinstance(request.get("broker"), dict) else {}
    host = broker.get("host")
    if not isinstance(host, str) or not host.strip():
        raise RuntimeError("broker host missing")
    port = int(broker.get("port") or 1883)

    cmd = [
        mqtt_bin,
        "-h", host,
        "-p", str(port),
        "-q", str(int(request.get("qos") or 1)),
        "-t", str(request.get("topic") or ""),
        "-m", str(request.get("payloadText") or "{}"),
    ]
    if bool(request.get("retain", True)):
        cmd.append("-r")

    username_env = broker.get("usernameEnv")
    password_env = broker.get("passwordEnv")
    username = os.environ.get(username_env) if isinstance(username_env, str) and username_env else None
    password = os.environ.get(password_env) if isinstance(password_env, str) and password_env else None
    if username:
        cmd += ["-u", username]
    if password:
        cmd += ["-P", password]

    subprocess.run(cmd, check=True, capture_output=True, text=True)


def maybe_publish_operator_snapshot(
    *,
    state_dir: str | Path,
    config: dict[str, Any] | None,
    queue_preview: int = 3,
    tick_count: int = 3,
    publish_fn: PublishFn | None = None,
) -> OperatorMqttPublishResult:
    resolved_state_dir = Path(state_dir).expanduser().resolve()
    normalized = load_operator_mqtt_config(config)
    if not normalized.get("enabled"):
        return OperatorMqttPublishResult(
            enabled=False,
            attempted=False,
            changed=False,
            published=False,
            topic=None,
            note="operator MQTT disabled; skipping publish",
        )

    snapshot_read = resolve_operator_snapshot(
        state_dir=resolved_state_dir,
        queue_preview=queue_preview,
        tick_count=tick_count,
        rebuild_missing=False,
        rebuild_malformed=False,
        write_rebuild=False,
    )
    if not isinstance(snapshot_read.artifact, dict):
        return OperatorMqttPublishResult(
            enabled=True,
            attempted=False,
            changed=False,
            published=False,
            topic=None,
            note="operator MQTT enabled but canonical snapshot unavailable; skipping publish",
        )

    payload = build_publish_payload(snapshot_read)
    if payload is None:
        return OperatorMqttPublishResult(
            enabled=True,
            attempted=False,
            changed=False,
            published=False,
            topic=None,
            note="operator MQTT enabled but payload derivation failed; skipping publish",
        )
    project = payload.get("project")
    if not isinstance(project, str) or not project.strip():
        return OperatorMqttPublishResult(
            enabled=True,
            attempted=False,
            changed=False,
            published=False,
            topic=None,
            payload=payload,
            note="operator MQTT enabled but canonical snapshot project missing; skipping publish",
        )

    topic = publish_topic(topic_prefix=str(normalized.get("topicPrefix") or DEFAULT_TOPIC_PREFIX), project=project)
    fingerprint = snapshot_fingerprint(payload)
    previous = load_publish_state(resolved_state_dir)
    previous_fingerprint = previous.get("lastPublishedFingerprint") if isinstance(previous.get("lastPublishedFingerprint"), str) else None
    if previous_fingerprint == fingerprint:
        return OperatorMqttPublishResult(
            enabled=True,
            attempted=False,
            changed=False,
            published=False,
            topic=topic,
            payload=payload,
            note="operator MQTT snapshot unchanged; skipping publish",
        )

    request = {
        "topic": topic,
        "payload": payload,
        "payloadText": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "qos": normalized.get("qos", 1),
        "retain": normalized.get("retain", True),
        "broker": normalized.get("broker"),
    }
    sender = publish_fn or mosquitto_publish
    try:
        sender(request)
    except Exception as exc:
        return OperatorMqttPublishResult(
            enabled=True,
            attempted=True,
            changed=True,
            published=False,
            topic=topic,
            payload=payload,
            note=f"operator MQTT publish failed: {clip(exc, 200)}",
        )

    write_publish_state(resolved_state_dir, {
        "topic": topic,
        "lastPublishedFingerprint": fingerprint,
        "lastPublishedAt": iso_now(),
        "snapshotUpdatedAt": payload.get("snapshot", {}).get("updatedAt") if isinstance(payload.get("snapshot"), dict) else None,
    })
    return OperatorMqttPublishResult(
        enabled=True,
        attempted=True,
        changed=True,
        published=True,
        topic=topic,
        payload=payload,
        note="operator MQTT snapshot published",
    )
