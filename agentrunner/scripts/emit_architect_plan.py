#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_json_object(raw: str):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit('expected JSON object')
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--initiative-id', required=True)
    ap.add_argument('--approach-summary', required=True)
    ap.add_argument('--tradeoff', action='append', default=[])
    ap.add_argument('--review-focus', action='append', default=[])
    ap.add_argument('--subtask-json', action='append', default=[])
    args = ap.parse_args()

    subtasks = [parse_json_object(raw) for raw in args.subtask_json]
    if not subtasks:
        raise SystemExit('at least one --subtask-json is required')
    for idx, subtask in enumerate(subtasks):
        for key in ('subtaskId', 'title', 'goal', 'role', 'files', 'checks'):
            if key not in subtask:
                raise SystemExit(f'subtasks[{idx}] missing required key: {key}')

    obj = {
        'initiativeId': args.initiative_id,
        'approachSummary': args.approach_summary,
        'tradeoffs': args.tradeoff,
        'subtasks': subtasks,
        'reviewFocus': args.review_focus,
        'writtenAt': iso_now(),
    }

    os.makedirs(os.path.dirname(args.path), exist_ok=True)
    tmp = args.path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, args.path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
