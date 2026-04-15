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
    ap.add_argument('--initiative-id', required=True)
    ap.add_argument('--decision', required=True, choices=['complete', 'architect'])
    ap.add_argument('--reason', required=True)
    ap.add_argument('--note', action='append', default=[])
    ap.add_argument('--outcome-met', action='append', default=[])
    ap.add_argument('--outcome-missed', action='append', default=[])
    args = ap.parse_args()

    obj = {
        'initiativeId': args.initiative_id,
        'decision': args.decision,
        'reason': args.reason,
        'writtenAt': iso_now(),
    }
    if args.note:
        obj['notes'] = args.note
    if args.outcome_met:
        obj['outcomesMet'] = args.outcome_met
    if args.outcome_missed:
        obj['outcomesMissed'] = args.outcome_missed

    os.makedirs(os.path.dirname(args.path), exist_ok=True)
    tmp = args.path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, args.path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
