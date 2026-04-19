#!/usr/bin/env python3
"""Explicit rebuild/debug helper for the canonical operator status artifact.

For normal operator reads, prefer ``operator_cli.py`` which consumes
``operator_status.json`` first. This script remains the manual rebuild path:
run with ``--write`` to refresh ``operator_status.json`` on demand for
recovery/debugging.
"""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .status_artifact import build_status_artifact, format_status_lines, write_status_artifact
except ImportError:  # pragma: no cover - script-mode fallback
    from status_artifact import build_status_artifact, format_status_lines, write_status_artifact


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--queue", type=int, default=3, help="how many queued items to show")
    ap.add_argument("--ticks", type=int, default=3, help="how many recent ticks to inspect")
    ap.add_argument("--write", action="store_true", help="refresh operator_status.json before printing")
    args = ap.parse_args()

    state_dir = Path(args.state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=args.queue, tick_count=args.ticks)
    if args.write:
        write_status_artifact(state_dir, artifact)
    for line in format_status_lines(artifact, queue_preview=args.queue):
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
