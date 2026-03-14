#!/usr/bin/env python3
"""Parse structured result footer from a cron run summary.

We require the worker to emit a line:
  AGENTRUNNER_RESULT_JSON: { ... }

This parser extracts that JSON object.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

PAT = re.compile(r"^AGENTRUNNER_RESULT_JSON:\s*(\{.*\})\s*$", re.MULTILINE)


def parse(text: str) -> dict[str, Any] | None:
    m = PAT.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="summary text")
    ap.add_argument("--path", help="path to file containing summary")
    args = ap.parse_args()

    if args.path:
        text = open(args.path, "r", encoding="utf-8", errors="ignore").read()
    else:
        text = args.text or sys.stdin.read()

    obj = parse(text)
    if obj is None:
        return 2
    print(json.dumps(obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
