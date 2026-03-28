#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--source-queue-item-id', required=True)
    ap.add_argument('--source-role', required=True)
    ap.add_argument('--target-role', required=True)
    ap.add_argument('--project', required=True)
    ap.add_argument('--repo-path')
    ap.add_argument('--branch')
    ap.add_argument('--base')
    ap.add_argument('--goal', required=True)
    ap.add_argument('--check', action='append', default=[])
    ap.add_argument('--finding-json', action='append', default=[])
    ap.add_argument('--context-file', action='append', default=[])
    ap.add_argument('--constraint-json')
    args = ap.parse_args()

    findings = [json.loads(raw) for raw in args.finding_json]
    constraints = json.loads(args.constraint_json) if args.constraint_json else {}

    obj = {
        'sourceQueueItemId': args.source_queue_item_id,
        'sourceRole': args.source_role,
        'targetRole': args.target_role,
        'project': args.project,
        'repoPath': args.repo_path,
        'branch': args.branch,
        'base': args.base,
        'goal': args.goal,
        'checks': args.check,
        'findings': findings,
        'constraints': constraints,
        'contextFiles': args.context_file,
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
