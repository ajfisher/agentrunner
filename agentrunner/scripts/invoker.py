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

This invoker uses:
- role prompt templates in `agentrunner/prompts/<role>.txt`
- structured worker footer: `AGENTRUNNER_RESULT_JSON: {...}`
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import shutil
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




def openclaw_bin() -> str:
    # Prefer explicit env var, then common npm-global path, then PATH.
    candidates = [
        os.environ.get("OPENCLAW_BIN"),
        "/home/openclaw/.npm-global/bin/openclaw",
        shutil.which("openclaw"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    # Return plain name as last resort (lets subprocess raise a useful error).
    return "openclaw"

def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def script_path(rel: str) -> str:
    return os.path.join("/home/openclaw/projects/agentrunner", rel)


def materialize_queue(state_dir: str) -> None:
    events = os.path.join(state_dir, "queue_events.ndjson")
    out = os.path.join(state_dir, "queue.json")
    if not os.path.exists(events):
        return
    cmd = ["python3", script_path("agentrunner/scripts/queue_ledger.py"), "--events", events, "--out", out]
    rc, out_s, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"queue materialize failed rc={rc} err={err.strip()} out={out_s.strip()}")


def append_queue_event(state_dir: str, kind: str, *, item: dict | None = None, id: str | None = None, status: str | None = None) -> None:
    events = os.path.join(state_dir, "queue_events.ndjson")
    out = os.path.join(state_dir, "queue.json")

    cmd = [
        "python3",
        script_path("agentrunner/scripts/queue_ledger.py"),
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
        script_path("agentrunner/scripts/log_append.py"),
        "--path",
        ticks_path,
        "--record",
        json.dumps(record, ensure_ascii=False),
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"tick append failed rc={rc} err={err.strip()} out={out.strip()}")


def load_role_prompt(role: str) -> str:
    path = script_path(f"agentrunner/prompts/{role}.txt")
    if not os.path.exists(path):
        raise RuntimeError(f"missing role prompt template: {path}")
    return open(path, "r", encoding="utf-8").read().strip() + "\n"


def parse_result_footer(summary: str) -> dict | None:
    cmd = ["python3", script_path("agentrunner/scripts/result_parser.py"), "--text", summary]
    rc, out, err = run_cmd(cmd)
    if rc == 0:
        return json.loads(out)
    return None


def schedule_one_shot(queue_item: dict, *, at_iso: str, announce: bool, channel: str, to: str, timeout_seconds: int) -> str:
    name = f"agentrunner:{queue_item.get('project')}:{queue_item.get('role')}:{queue_item.get('id')}"

    role = str(queue_item.get("role"))
    role_prompt = load_role_prompt(role)

    header = (
        "You are running under agentrunner (mechanics-driven).\n"
        "The mechanics layer owns state/queue/logs; you MUST NOT modify them.\n\n"
    )

    msg = header + role_prompt + "\nQUEUE_ITEM_JSON:\n" + json.dumps(queue_item, indent=2, ensure_ascii=False)

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
    cmd = [openclaw_bin(), "cron", "runs", "--id", job_id, "--limit", "1"]
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

    state = load_json(state_path, {"project": args.project, "running": False, "updatedAt": iso_now(), "current": None, "limits": {"maxExtraDevTurns": 1}, "policy": {"extraDevTurnReset": "on_branch_change"}, "runtime": {"extraDevTurnsUsed": 0, "lastBranch": None}})

    # If running, poll for completion and unlock.
    if state.get("running") and state.get("current") and state["current"].get("jobId"):
        job_id = state["current"]["jobId"]
        entry = poll_job(job_id)
        if entry is None:
            state["updatedAt"] = iso_now()
            save_json(state_path, state)
            return 0

        if entry.get("action") == "finished":
            raw_status = entry.get("status") or "error"
            qid = state["current"].get("queueItemId")
            role = state["current"].get("role")

            result = parse_result_footer(entry.get("summary") or "")
            status = (result.get("status") if isinstance(result, dict) else None) or raw_status

            # Queue ledger DONE
            if qid and os.path.exists(os.path.join(args.state_dir, "queue_events.ndjson")):
                append_queue_event(args.state_dir, "DONE", id=str(qid), status=str(status))

            rec = {
                "project": args.project,
                "queueItemId": qid,
                "role": role,
                "status": status,
                "jobId": job_id,
                "summary": entry.get("summary"),
                "result": result,
                "runAtMs": entry.get("runAtMs"),
                "durationMs": entry.get("durationMs"),
            }
            append_tick(args.state_dir, rec)

            # Bounded extra dev turn insertion
            if isinstance(result, dict) and result.get("request_extra_dev_turn"):
                used = int((state.get("runtime") or {}).get("extraDevTurnsUsed") or 0)
                max_extra = int((state.get("limits") or {}).get("maxExtraDevTurns") or 1)
                if used < max_extra:
                    extra_id = f"{qid}-extra-{used+1}"

                    base_item = (state.get("current") or {}).get("queueItem")
                    # If we have the original queue item, clone it (B-mode) so repo_path/branch/checks persist.
                    if isinstance(base_item, dict):
                        extra_item = dict(base_item)
                        extra_item["id"] = extra_id
                        extra_item["createdAt"] = iso_now()
                        extra_item["origin"] = {"requestedBy": qid, "reason": result.get("request_reason")}
                        # clarify goal for the extra turn without losing original goal
                        orig_goal = extra_item.get("goal")
                        extra_item["goal"] = f"(extra dev turn) {result.get('request_reason')}\n\nORIGINAL_GOAL: {orig_goal}"
                        extra_item["role"] = "developer"
                    else:
                        # Fallback (A-mode): minimal extra dev item
                        extra_item = {
                            "id": extra_id,
                            "project": args.project,
                            "role": "developer",
                            "createdAt": iso_now(),
                            "goal": f"Extra dev turn requested: {result.get('request_reason')}",
                            "origin": {"requestedBy": qid, "reason": result.get("request_reason")},
                        }

                    if os.path.exists(os.path.join(args.state_dir, "queue_events.ndjson")):
                        append_queue_event(args.state_dir, "INSERT_FRONT", item=extra_item)
                    else:
                        q = load_json(queue_path, [])
                        q.insert(0, extra_item)
                        save_json(queue_path, q)

                    state.setdefault("runtime", {})
                    state["runtime"]["extraDevTurnsUsed"] = used + 1

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

        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    # Idle: pop next queue item
    queue = load_json(queue_path, [])
    if not queue:
        state["updatedAt"] = iso_now()
        save_json(state_path, state)
        return 0

    item = queue[0]
    qid = str(item.get("id"))

    # deterministic reset policy for extra developer turns
    state.setdefault("runtime", {})
    state.setdefault("policy", {})
    reset_policy = state["policy"].get("extraDevTurnReset", "on_branch_change")
    item_role = str(item.get("role"))
    item_branch = item.get("branch")
    last_branch = state["runtime"].get("lastBranch")

    should_reset = False
    if reset_policy == "on_non_dev" and item_role != "developer":
        should_reset = True
    elif reset_policy == "on_branch_change" and item_branch != last_branch:
        should_reset = True
    elif reset_policy == "on_review_start" and item_role == "reviewer":
        should_reset = True

    if should_reset:
        state["runtime"]["extraDevTurnsUsed"] = 0

    # Schedule first; only consume queue item if scheduling succeeds.
    job_id = schedule_one_shot(
        item,
        at_iso=iso_in(args.schedule_delay_seconds),
        announce=args.announce,
        channel=args.channel,
        to=args.to,
        timeout_seconds=args.timeout_seconds,
    )

    # Now commit the dequeue transaction.
    queue.pop(0)
    if os.path.exists(os.path.join(args.state_dir, "queue_events.ndjson")):
        append_queue_event(args.state_dir, "DEQUEUE", id=qid)

    state["runtime"]["lastBranch"] = item_branch
    state["running"] = True
    state["updatedAt"] = iso_now()
    state["current"] = {
        "queueItemId": qid,
        "role": item.get("role"),
        "queueItem": item,
        "jobId": job_id,
        "startedAt": iso_now(),
        "lastHeartbeatAt": None,
    }

    save_json(queue_path, queue)
    save_json(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
