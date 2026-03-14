#!/usr/bin/env python3
"""Append-only NDJSON logger.

This is the only supported interface for writing ticks.ndjson.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="ticks.ndjson path")
    ap.add_argument("--record", required=True, help="JSON object string")
    args = ap.parse_args()

    rec = json.loads(args.record)
    rec.setdefault("ts", iso_now())

    os.makedirs(os.path.dirname(args.path), exist_ok=True)
    with open(args.path, "a", encoding="utf-8") as f:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
