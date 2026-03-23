#!/usr/bin/env python3
"""Small status/audit helper for agentrunner runtime state.

Shows:
- current state
- queue length + head item
- last completed
- recent ticks
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--ticks", type=int, default=5)
    args = ap.parse_args()

    sd = Path(args.state_dir)
    state = load_json(sd / "state.json", {})
    queue = load_json(sd / "queue.json", [])

    print(f"project: {state.get('project')}")
    print(f"running: {state.get('running')}")
    print(f"updatedAt: {state.get('updatedAt')}")
    print(f"current: {json.dumps(state.get('current'), ensure_ascii=False)}")
    print(f"lastCompleted: {json.dumps(state.get('lastCompleted'), ensure_ascii=False)}")
    print(f"policy: {json.dumps(state.get('policy'), ensure_ascii=False)}")
    print(f"runtime: {json.dumps(state.get('runtime'), ensure_ascii=False)}")
    print("--- queue")
    print(f"length: {len(queue)}")
    if queue:
        print(json.dumps(queue[0], indent=2, ensure_ascii=False))
    print("--- recent ticks")
    ticks_path = sd / "ticks.ndjson"
    if ticks_path.exists():
        lines = ticks_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        for line in lines[-args.ticks:]:
            try:
                obj = json.loads(line)
                print(json.dumps({
                    'ts': obj.get('ts'),
                    'queueItemId': obj.get('queueItemId'),
                    'role': obj.get('role'),
                    'status': obj.get('status'),
                    'result': obj.get('result'),
                }, ensure_ascii=False))
            except Exception:
                print(line)
    else:
        print('(no ticks yet)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
