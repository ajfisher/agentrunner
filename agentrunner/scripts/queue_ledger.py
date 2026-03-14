#!/usr/bin/env python3
"""Append-only queue ledger + materializer.

We store queue mutations as NDJSON events (append-only), and maintain a
materialized runnable queue.json for fast pop/insert.

Event kinds:
- ENQUEUE {item}
- INSERT_FRONT {item}
- CANCEL {id}
- DEQUEUE {id}
- DONE {id, status}

This file is mechanics-layer only.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def append_ndjson(path: str, rec: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = dict(rec)
    rec.setdefault("ts", iso_now())
    with open(path, "a", encoding="utf-8") as f:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_events(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def materialize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    canceled: set[str] = set()
    dequeued_or_done: set[str] = set()

    for ev in events:
        kind = ev.get("kind")
        if kind in ("ENQUEUE", "INSERT_FRONT"):
            item = ev.get("item")
            if not isinstance(item, dict) or "id" not in item:
                continue
            item_id = str(item["id"])
            if item_id in canceled or item_id in dequeued_or_done:
                continue
            if kind == "ENQUEUE":
                queue.append(item)
            else:
                queue.insert(0, item)
        elif kind == "CANCEL":
            canceled.add(str(ev.get("id")))
            queue = [it for it in queue if str(it.get("id")) not in canceled]
        elif kind in ("DEQUEUE", "DONE"):
            dequeued_or_done.add(str(ev.get("id")))
            queue = [it for it in queue if str(it.get("id")) not in dequeued_or_done]

    return queue


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True, help="queue_events.ndjson")
    ap.add_argument("--out", required=True, help="queue.json")
    ap.add_argument("--append", action="store_true", help="append an event")
    ap.add_argument("--kind", help="event kind")
    ap.add_argument("--id", help="event id (for CANCEL/DEQUEUE/DONE)")
    ap.add_argument("--item", help="JSON item (for ENQUEUE/INSERT_FRONT)")
    ap.add_argument("--status", help="DONE status")
    args = ap.parse_args()

    if args.append:
        ev: dict[str, Any] = {"kind": args.kind}
        if args.id:
            ev["id"] = args.id
        if args.status:
            ev["status"] = args.status
        if args.item:
            ev["item"] = json.loads(args.item)
        append_ndjson(args.events, ev)

    events = read_events(args.events)
    q = materialize(events)
    write_json(args.out, q)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
