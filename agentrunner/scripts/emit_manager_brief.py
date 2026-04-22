#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_json_object(raw: str | None, *, default):
    if raw is None:
        return default
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit('expected JSON object')
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--initiative-id', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--objective', required=True)
    ap.add_argument('--desired-outcome', action='append', default=[])
    ap.add_argument('--definition-of-done', action='append', default=[])
    ap.add_argument('--constraint-json')
    ap.add_argument('--priority', default='normal')
    ap.add_argument('--note', action='append', default=[])
    ap.add_argument('--risk', action='append', default=[])
    ap.add_argument('--project')
    ap.add_argument('--repo-path')
    ap.add_argument('--base-branch', default='main')
    ap.add_argument('--suggested-branch')
    ap.add_argument('--max-subtasks', type=int)
    args = ap.parse_args()

    obj = {
        'initiativeId': args.initiative_id,
        'title': args.title,
        'objective': args.objective,
        'desiredOutcomes': args.desired_outcome,
        'constraints': parse_json_object(args.constraint_json, default={}),
        'definitionOfDone': args.definition_of_done,
        'priority': args.priority,
        'writtenAt': iso_now(),
    }
    if args.note:
        obj['notes'] = args.note
    if args.risk:
        obj['risks'] = args.risk
    if args.project:
        obj['project'] = args.project
    if args.repo_path:
        obj['repoPath'] = args.repo_path
    if args.base_branch:
        obj['baseBranch'] = args.base_branch
    if args.suggested_branch:
        obj['suggestedBranch'] = args.suggested_branch
    if args.max_subtasks is not None:
        obj['maxSubtasks'] = args.max_subtasks

    os.makedirs(os.path.dirname(args.path), exist_ok=True)
    tmp = args.path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, args.path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
