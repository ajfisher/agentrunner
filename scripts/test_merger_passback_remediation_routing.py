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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='initiative-merger-passback-remediation-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        initiative_id = 'agentrunner-merger-passback-remediation'
        merger_qid = f'{initiative_id}-merger'
        result_path = state_dir / 'results' / f'{merger_qid}.json'
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
            'base': 'master',
            'writtenAt': '2026-04-20T06:59:00+10:00',
        })
        write_json(result_path, {
            'status': 'blocked',
            'role': 'merger',
            'summary': 'Merge blocked; branch must be rebased before ff-only merge can proceed.',
            'merged': False,
            'commit': 'abc1234',
            'writtenAt': '2026-04-20T07:04:00+10:00',
            'checks': [
                {'name': 'git diff --stat master...feature/agentrunner/merger-passback-remediation', 'status': 'ok'},
                {'name': 'git merge-base --is-ancestor master feature/agentrunner/merger-passback-remediation', 'status': 'blocked'},
            ],
            'mergeBlocker': {
                'classification': 'repairable',
                'kind': 'non_fast_forward',
                'detail': 'Feature branch diverged from master and needs a developer remediation pass.',
                'passback': {
                    'targetRole': 'developer',
                    'action': 'rebase',
                    'reason': 'Rebase the branch onto master, rerun checks, then return through review and merge retry.',
                    'requiresReReview': True,
                    'requiresMergeRetry': True,
                },
            },
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
                'queueItemId': merger_qid,
                'role': 'merger',
                'queueItem': {
                    'id': merger_qid,
                    'project': 'agentrunner',
                    'role': 'merger',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/merger-passback-remediation',
                    'base': 'master',
                    'goal': 'Attempt ff-only merge for initiative closure.',
                    'checks': [
                        'git diff --stat master...feature/agentrunner/merger-passback-remediation',
                        'git merge-base --is-ancestor master feature/agentrunner/merger-passback-remediation',
                    ],
                    'contextFiles': ['agentrunner/scripts/invoker.py', 'agentrunner/scripts/initiative_coordinator.py'],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'phase': 'closure-merger',
                        'branch': 'feature/agentrunner/merger-passback-remediation',
                        'base': 'master',
                    },
                },
                'resultPath': str(result_path),
                'summary': 'Merge blocked.',
                'status': 'blocked',
            },
            'updatedAt': '2026-04-20T07:04:30+10:00',
        })

        proc = subprocess.run([
            sys.executable,
            str(repo_path / 'agentrunner/scripts/initiative_coordinator.py'),
            '--state-dir', str(state_dir),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f'initiative_coordinator failed: {proc.stdout}{proc.stderr}')

        changed = json.loads(proc.stdout)
        if changed != {'changed': True}:
            raise SystemExit(f'expected merger remediation routing to change queue/state, got: {changed}')

        queue_after = load_json(queue_path)
        if len(queue_after) != 1:
            raise SystemExit(f'expected one queued remediation item, got: {queue_after}')
        item = queue_after[0]
        if item.get('role') != 'developer':
            raise SystemExit(f'expected queued remediation role developer, got: {item}')
        if item.get('initiative', {}).get('subtaskId') != 'merger-remediation-1':
            raise SystemExit(f'expected bounded remediation subtask id, got: {item}')
        constraints = item.get('constraints') or {}
        if constraints.get('closureRemediation') is not True or constraints.get('closureRemediationAttempt') != 1:
            raise SystemExit(f'expected closure remediation constraints, got: {item}')
        origin = item.get('origin') or {}
        if origin.get('requestedBy') != merger_qid or origin.get('closureRemediationAttempt') != 1:
            raise SystemExit(f'expected origin to preserve closure context, got: {item}')

        initiative_state_after = load_json(initiative_state_path)
        if initiative_state_after.get('phase') != 'execution':
            raise SystemExit(f'expected initiative to re-enter execution, got: {initiative_state_after}')
        if initiative_state_after.get('currentSubtaskId') != 'merger-remediation-1':
            raise SystemExit(f'expected remediation subtask to become current, got: {initiative_state_after}')
        if initiative_state_after.get('pendingSubtasks') != ['merger-remediation-1']:
            raise SystemExit(f'expected only remediation subtask pending, got: {initiative_state_after}')

        remediation = initiative_state_after.get('remediation') or {}
        attempts = remediation.get('attempts') or []
        if len(attempts) != 1:
            raise SystemExit(f'expected one remediation attempt record, got: {initiative_state_after}')
        attempt = attempts[0]
        if attempt.get('action') != 'rebase' or attempt.get('status') != 'queued':
            raise SystemExit(f'expected remediation attempt metadata to be recorded, got: {attempt}')
        if attempt.get('sourceQueueItemId') != merger_qid or attempt.get('subtaskId') != 'merger-remediation-1':
            raise SystemExit(f'expected remediation attempt to retain source closure context, got: {attempt}')

        state_after = load_json(state_path)
        pointer = state_after.get('initiative') or {}
        if pointer.get('initiativeId') != initiative_id or pointer.get('phase') != 'execution':
            raise SystemExit(f'expected state initiative pointer to move back into execution, got: {state_after}')

    print('ok: repairable blocked merger routes a bounded developer remediation item back into the normal initiative flow')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
