#!/usr/bin/env python3
"""Invoker supervisor (mechanics layer).

Intended to run via system cron every minute.

Responsibilities:
- Load per-project state + queue
- If not running, pop next queue item
- Schedule an OpenClaw one-shot cron job for that item

NOTE: This is scaffold-only. The actual scheduling call is left as a stub
until we decide whether to use the OpenClaw HTTP API or the `openclaw` CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def schedule_one_shot_stub(queue_item: dict) -> str:
    """Return a fake jobId.

    Replace with:
    - `openclaw cron add ...` (CLI)
    - or OpenClaw gateway HTTP endpoint
    """
    # Placeholder: we just return a pseudo id.
    return "stub-jobid-" + queue_item["id"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--state-dir", required=True, help="/home/openclaw/.agentrunner/projects/<project>")
    args = ap.parse_args()

    state_path = os.path.join(args.state_dir, "state.json")
    queue_path = os.path.join(args.state_dir, "queue.json")

    state = load_json(state_path, {"project": args.project, "running": False, "updatedAt": iso_now()})
    queue = load_json(queue_path, [])

    # If running, do nothing (future: stale lock detection)
    if state.get("running"):
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    if not queue:
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    item = queue.pop(0)
    job_id = schedule_one_shot_stub(item)

    state["running"] = True
    state["updatedAt"] = iso_now()
    state["current"] = {
        "queueItemId": item.get("id"),
        "role": item.get("role"),
        "jobId": job_id,
        "startedAt": iso_now(),
        "lastHeartbeatAt": None,
    }

    save_json(queue_path, queue)
    save_json(state_path, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
