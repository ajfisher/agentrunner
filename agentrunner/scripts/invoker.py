#!/usr/bin/env python3
"""Invoker supervisor (mechanics layer).

Run this from *system cron* (every minute, or faster).

Responsibilities:
- Maintain per-project run-lock in state.json
- Maintain materialized queue.json from append-only queue_events.ndjson
- If a job is running: poll OpenClaw cron runs for completion and unlock
- If idle: pop next queue item and schedule a one-shot OpenClaw cron agentTurn
- Append a tick record to ticks.ndjson when a run finishes

This keeps orchestration mechanics outside agent control.
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


def materialize_queue(state_dir: str) -> None:
    events = os.path.join(state_dir, "queue_events.ndjson")
    out = os.path.join(state_dir, "queue.json")
    if not os.path.exists(events):
        return
    cmd = ["python3", "/home/openclaw/projects/agentrunner/agentrunner/scripts/queue_ledger.py", "--events", events, "--out", out]
    rc, out_s, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"queue materialize failed rc={rc} err={err.strip()} out={out_s.strip()}")


def append_queue_event(state_dir: str, kind: str, *, item: dict | None = None, id: str | None = None, status: str | None = None) -> None:
    events = os.path.join(state_dir, "queue_events.ndjson")
    out = os.path.join(state_dir, "queue.json")
    payload: dict = {"kind": kind}
    if item is not None:
        payload["item"] = item
    if id is not None:
        payload["id"] = id
    if status is not None:
        payload["status"] = status
    cmd = [
        "python3",
        "/home/openclaw/projects/agentrunner/agentrunner/scripts/queue_ledger.py",
        "--events",
        events,
        "--out",
        out,
        "--append",
        "--kind",
        kind,
    ]
    if id is not None:
        cmd += ["--id", id]
    if status is not None:
        cmd += ["--status", status]
    if item is not None:
        cmd += ["--item", json.dumps(item, ensure_ascii=False)]

    rc, out_s, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"append_queue_event failed rc={rc} err={err.strip()} out={out_s.strip()}")


def append_tick(state_dir: str, record: dict) -> None:
    ticks_path = os.path.join(state_dir, "ticks.ndjson")
    cmd = [
        "python3",
        "/home/openclaw/projects/agentrunner/agentrunner/scripts/log_append.py",
        "--path",
        ticks_path,
        "--record",
        json.dumps(record, ensure_ascii=False),
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"tick append failed rc={rc} err={err.strip()} out={out.strip()}")


def schedule_one_shot(queue_item: dict, *, at_iso: str, announce: bool, channel: str, to: str, timeout_seconds: int) -> str:
    name = f"agentrunner:{queue_item.get('project')}:{queue_item.get('role')}:{queue_item.get('id')}"

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
        "--keep-after-run",
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


def poll_job(job_id: str) -> dict | None:
    cmd = ["openclaw", "cron", "runs", "--id", job_id, "--limit", "1"]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"openclaw cron runs failed rc={rc} err={err.strip()} out={out.strip()}")
    data = json.loads(out)
    entries = data.get("entries") or []
    if not entries:
        return None
    return entries[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--state-dir", required=True, help="/home/openclaw/.agentrunner/projects/<project>")
    ap.add_argument("--announce", action="store_true")
    ap.add_argument("--channel", default="discord")
    ap.add_argument("--to", default="")
    ap.add_argument("--timeout-seconds", type=int, default=540)
    ap.add_argument("--schedule-delay-seconds", type=int, default=5)
    args = ap.parse_args()

    state_path = os.path.join(args.state_dir, "state.json")
    queue_path = os.path.join(args.state_dir, "queue.json")

    # Always materialize queue view if a ledger exists.
    materialize_queue(args.state_dir)

    state = load_json(state_path, {"project": args.project, "running": False, "updatedAt": iso_now(), "current": None, "limits": {"maxExtraDevTurns": 1}})

    # If running, poll for completion and unlock.
    if state.get("running") and state.get("current") and state["current"].get("jobId"):
        job_id = state["current"]["jobId"]
        entry = poll_job(job_id)
        # Not started / not recorded yet
        if entry is None:
            state["updatedAt"] = iso_now()
            save_json(state_path, state)
            return 0

        if entry.get("action") == "finished":
            status = entry.get("status") or "error"
            qid = state["current"].get("queueItemId")
            role = state["current"].get("role")
            branch = (state.get("current") or {}).get("branch") or None

            # Append DONE to queue ledger if it exists.
            if qid and os.path.exists(os.path.join(args.state_dir, "queue_events.ndjson")):
                append_queue_event(args.state_dir, "DONE", id=str(qid), status=str(status))

            # Append tick record
            rec = {
                "project": args.project,
                "queueItemId": qid,
                "role": role,
                "status": status,
                "jobId": job_id,
                "summary": entry.get("summary"),
                "runAtMs": entry.get("runAtMs"),
                "durationMs": entry.get("durationMs"),
            }
            append_tick(args.state_dir, rec)

            # Unlock
            state["running"] = False
            state["updatedAt"] = iso_now()
            state["lastCompleted"] = {
                "queueItemId": qid,
                "role": role,
                "jobId": job_id,
                "endedAt": iso_now(),
                "status": status,
            }
            state["current"] = None
            save_json(state_path, state)
            return 0

        # Still running or other action
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    # Idle: pop next queue item.
    queue = load_json(queue_path, [])
    if not queue:
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    item = queue.pop(0)
    qid = str(item.get("id"))

    # Ledger: record DEQUEUE
    if os.path.exists(os.path.join(args.state_dir, "queue_events.ndjson")):
        append_queue_event(args.state_dir, "DEQUEUE", id=qid)

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
        "queueItemId": qid,
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
