#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_bool(v: str | None):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ('1', 'true', 'yes', 'y'):
        return True
    if s in ('0', 'false', 'no', 'n'):
        return False
    raise argparse.ArgumentTypeError(f'invalid boolean: {v}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--role', required=True, choices=['developer', 'reviewer', 'manager', 'merger', 'architect'])
    ap.add_argument('--status', required=True, choices=['ok', 'blocked', 'error'])
    ap.add_argument('--summary')
    ap.add_argument('--commit')
    ap.add_argument('--approved')
    ap.add_argument('--merged')
    ap.add_argument('--request-extra-dev-turn')
    ap.add_argument('--request-reason')
    ap.add_argument('--check', action='append', default=[])
    ap.add_argument('--finding-json', action='append', default=[])
    ap.add_argument('--operator-line', action='append', default=[])
    ap.add_argument('--blocker-classification')
    ap.add_argument('--blocker-kind')
    ap.add_argument('--blocker-detail')
    ap.add_argument('--passback-role')
    ap.add_argument('--passback-action')
    ap.add_argument('--passback-reason')
    ap.add_argument('--passback-requires-rereview')
    ap.add_argument('--passback-requires-merge-retry')
    ap.add_argument('--stop-condition', action='append', default=[])
    args = ap.parse_args()

    checks = []
    for raw in args.check:
        if '=' in raw:
            name, status = raw.rsplit('=', 1)
            checks.append({'name': name, 'status': status})
        else:
            checks.append({'name': raw, 'status': 'ok'})

    findings = []

    def append_finding(value):
        if isinstance(value, list):
            for item in value:
                append_finding(item)
            return
        if isinstance(value, dict) and isinstance(value.get('findings'), list) and len(value) == 1:
            append_finding(value.get('findings'))
            return
        findings.append(value)

    for raw in args.finding_json:
        append_finding(json.loads(raw))

    prefix = {
        'developer': 'Developer ›',
        'reviewer': 'Reviewer ›',
        'manager': 'Manager ›',
        'merger': 'Merger ›',
        'architect': 'Architect ›',
    }[args.role]
    operator_lines = [prefix] + [f'- {line}' for line in args.operator_line]

    merge_blocker = None
    if any([
        args.blocker_classification,
        args.blocker_kind,
        args.blocker_detail,
        args.passback_role,
        args.passback_action,
        args.passback_reason,
        args.passback_requires_rereview is not None,
        args.passback_requires_merge_retry is not None,
        args.stop_condition,
    ]):
        merge_blocker = {
            'classification': args.blocker_classification,
            'kind': args.blocker_kind,
            'detail': args.blocker_detail,
        }
        passback = {
            'targetRole': args.passback_role,
            'action': args.passback_action,
            'reason': args.passback_reason,
            'requiresReReview': parse_bool(args.passback_requires_rereview),
            'requiresMergeRetry': parse_bool(args.passback_requires_merge_retry),
        }
        if any(value is not None for value in passback.values()):
            merge_blocker['passback'] = passback
        if args.stop_condition:
            merge_blocker['stopConditions'] = list(args.stop_condition)

    obj = {
        'status': args.status,
        'role': args.role,
        'summary': args.summary,
        'commit': args.commit,
        'approved': parse_bool(args.approved),
        'merged': parse_bool(args.merged),
        'checks': checks,
        'findings': findings,
        'requestExtraDevTurn': parse_bool(args.request_extra_dev_turn),
        'requestReason': args.request_reason,
        'operatorSummary': '\n'.join(operator_lines[:6]),
        'writtenAt': iso_now(),
    }
    if merge_blocker is not None:
        obj['mergeBlocker'] = merge_blocker

    os.makedirs(os.path.dirname(args.path), exist_ok=True)
    tmp = args.path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, args.path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
