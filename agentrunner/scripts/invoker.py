#!/usr/bin/env python3
"""Invoker supervisor (mechanics layer).

Designed to run from *system cron* (every minute, or faster if you want).

Responsibilities:
- Load per-project state + queue (materialized view)
- Enforce a simple run-lock (one job at a time)
- If not running, pop next queue item
- Schedule an OpenClaw **one-shot** cron job for that item (session=isolated)

This keeps orchestration mechanics outside the agent's control.

Runtime state directory (recommended):
  /home/openclaw/.agentrunner/projects/<project>/

Queue file:
  queue.json (materialized runnable queue)

Append-only logs (optional, but recommended):
  queue_events.ndjson
  ticks.ndjson

NOTE: This script uses the OpenClaw CLI (`openclaw cron add --json`) as the
scheduling bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def iso_in(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


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


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def schedule_one_shot(queue_item: dict, *, at_iso: str, announce: bool, channel: str, to: str, timeout_seconds: int) -> str:
    """Schedule an OpenClaw one-shot job and return jobId."""

    name = f"agentrunner:{queue_item.get('project')}:{queue_item.get('role')}:{queue_item.get('id')}"

    # The worker prompt is intentionally self-contained.
    # Later we can templatize this via prompts/<role>.txt + a worker harness.
    msg = (
        "You are running under agentrunner (mechanics-driven).\n\n"
        "You have ONE job: execute the queue item below.\n"
        "- Follow role discipline (developer/reviewer/manager/merger/architect).\n"
        "- Work only within the project repo path provided.\n"
        "- If role=developer: commit changes to the specified branch; shipped==committed.\n"
        "- Do not modify agentrunner state/queue/ticks directly.\n\n"
        "QUEUE_ITEM_JSON:\n" + json.dumps(queue_item, indent=2, ensure_ascii=False)
    )

    cmd = [
        "openclaw",
        "cron",
        "add",
        "--json",
        "--name",
        name,
        "--at",
        at_iso,
        "--session",
        "isolated",
        "--message",
        msg,
        "--timeout-seconds",
        str(timeout_seconds),
    ]

    if announce:
        cmd += ["--announce", "--channel", channel, "--to", to, "--best-effort-deliver"]
    else:
        cmd += ["--no-deliver"]

    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"openclaw cron add failed rc={rc} err={err.strip()} out={out.strip()}")

    job = json.loads(out)
    job_id = job.get("id") or job.get("jobId")
    if not job_id:
        raise RuntimeError(f"openclaw cron add returned JSON without id/jobId: {job}")
    return job_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--state-dir", required=True, help="/home/openclaw/.agentrunner/projects/<project>")
    ap.add_argument("--announce", action="store_true", help="deliver to chat via cron announce")
    ap.add_argument("--channel", default="discord")
    ap.add_argument("--to", default="", help="delivery target, e.g. channel:<id>")
    ap.add_argument("--timeout-seconds", type=int, default=540)
    ap.add_argument("--schedule-delay-seconds", type=int, default=5, help="schedule one-shot this many seconds in the future")
    args = ap.parse_args()

    state_path = os.path.join(args.state_dir, "state.json")
    queue_path = os.path.join(args.state_dir, "queue.json")

    state = load_json(state_path, {"project": args.project, "running": False, "updatedAt": iso_now(), "current": None})
    queue = load_json(queue_path, [])

    # Lock discipline
    if state.get("running"):
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    if not queue:
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    item = queue.pop(0)

    # Schedule slightly in the future so the gateway has time to persist the job.
    job_id = schedule_one_shot(
        item,
        at_iso=iso_in(args.schedule_delay_seconds),
        announce=args.announce,
        channel=args.channel,
        to=args.to,
        timeout_seconds=args.timeout_seconds,
    )

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
