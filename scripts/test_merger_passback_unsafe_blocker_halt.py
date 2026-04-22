#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')


def load_json(path: Path):
    return json.loads(path.read_text())


def run_case(repo_path: Path, *, state_dir: Path, initiative_id: str, blocker: dict, expected_detail_snippet: str) -> None:
    state_path = state_dir / 'state.json'
    queue_path = state_dir / 'queue.json'
    result_path = state_dir / 'results' / f'{initiative_id}-merger.json'
    initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'

    write_json(queue_path, [])
    write_json(initiative_state_path, {
        'initiativeId': initiative_id,
        'phase': 'closure-merger',
        'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
        'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
        'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
        'currentSubtaskId': None,
        'completedSubtasks': ['mechanics-passback-routing'],
        'pendingSubtasks': [],
        'branch': 'feature/agentrunner/merger-passback-remediation',
        'base': 'main',
        'remediation': {
            'attempts': [
                {
                    'attempt': 1,
                    'subtaskId': 'merger-remediation-1',
                    'queueItemId': f'{initiative_id}-merger-remediation-1',
                    'sourceQueueItemId': f'{initiative_id}-merger',
                    'status': 'merge-retry-queued',
                }
            ],
            'activeAttempt': 1,
            'lastAttempt': 1,
            'maxAttempts': 2,
        },
        'writtenAt': '2026-04-20T07:15:00+10:00',
    })
    write_json(result_path, {
        'status': 'blocked',
        'role': 'merger',
        'summary': 'Merge is blocked and should halt closure remediation because the blocker is outside the supported repairable taxonomy.',
        'merged': False,
        'commit': 'abc1234',
        'writtenAt': '2026-04-20T07:16:00+10:00',
        'checks': [
            {'name': 'git status --short', 'status': 'ok'},
            {'name': 'merge-policy ff-only', 'status': 'blocked'},
        ],
        'mergeBlocker': blocker,
    })
    write_json(state_path, {
        'project': 'agentrunner',
        'running': False,
        'current': None,
        'initiative': {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'statePath': str(initiative_state_path),
        },
        'lastCompleted': {
            'queueItemId': f'{initiative_id}-merger',
            'role': 'merger',
            'queueItem': {
                'id': f'{initiative_id}-merger',
                'project': 'agentrunner',
                'role': 'merger',
                'repo_path': str(repo_path),
                'branch': 'feature/agentrunner/merger-passback-remediation',
                'base': 'main',
                'goal': 'Attempt closure merge retry.',
                'checks': ['git status --short'],
                'contextFiles': ['agentrunner/scripts/initiative_coordinator.py'],
                'initiative': {
                    'initiativeId': initiative_id,
                    'phase': 'closure-merger',
                    'branch': 'feature/agentrunner/merger-passback-remediation',
                    'base': 'main',
                },
            },
            'resultPath': str(result_path),
            'summary': 'Merge blocked.',
            'status': 'blocked',
        },
        'updatedAt': '2026-04-20T07:16:30+10:00',
    })

    proc = subprocess.run([
        sys.executable,
        str(repo_path / 'agentrunner/scripts/initiative_coordinator.py'),
        '--state-dir', str(state_dir),
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f'initiative_coordinator failed: {proc.stdout}{proc.stderr}')

    changed = json.loads(proc.stdout)
    if changed != {'changed': False}:
        raise SystemExit(f'expected unsafe blocker case to halt without queue mutation, got: {changed}')

    queue_after = load_json(queue_path)
    if queue_after != []:
        raise SystemExit(f'expected no remediation item to be queued for unsafe blocker case, got: {queue_after}')

    initiative_state_after = load_json(initiative_state_path)
    remediation = initiative_state_after.get('remediation') or {}
    halted = remediation.get('halted') or {}
    if halted.get('reason') != 'unsafe_blocker_change':
        raise SystemExit(f'expected unsafe blocker halt marker, got: {initiative_state_after}')
    detail = str(halted.get('detail') or '')
    if expected_detail_snippet not in detail:
        raise SystemExit(f'expected halt detail to mention unsafe blocker stop, got: {initiative_state_after}')
    if remediation.get('activeAttempt') is not None:
        raise SystemExit(f'expected active remediation attempt to clear on unsafe blocker halt, got: {initiative_state_after}')
    if initiative_state_after.get('phase') != 'closure-merger':
        raise SystemExit(f'expected phase to remain closure-merger while halted, got: {initiative_state_after}')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='initiative-merger-passback-unsafe-halt-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        ambiguous_blocker = {
            'classification': 'terminal',
            'kind': 'ambiguous_readiness',
            'detail': 'Merge readiness is ambiguous because closure expectations changed mid-flight.',
            'stopConditions': [
                'Clarify whether the initiative should still close on this branch.',
                'Resolve the competing closure target before another merge attempt.',
            ],
        }
        run_case(
            repo_path,
            state_dir=temp_root / 'state-ambiguous',
            initiative_id='agentrunner-merger-passback-ambiguous-halt',
            blocker=ambiguous_blocker,
            expected_detail_snippet='Closure remediation stopped',
        )

    print('ok: unsafe or ambiguous closure blockers halt remediation instead of looping another developer passback')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
