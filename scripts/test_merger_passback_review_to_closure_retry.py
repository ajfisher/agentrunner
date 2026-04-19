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
    with tempfile.TemporaryDirectory(prefix='initiative-merger-passback-review-retry-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        initiative_id = 'agentrunner-merger-passback-remediation'
        reviewer_qid = f'{initiative_id}-merger-remediation-1-review'
        reviewer_result_path = state_dir / 'results' / f'{reviewer_qid}.json'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        plan_path = state_dir / 'initiatives' / initiative_id / 'plan.json'

        write_json(queue_path, [])
        write_json(plan_path, {'subtasks': []})
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'execution',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'architectPlanPath': str(plan_path),
            'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
            'currentSubtaskId': 'merger-remediation-1',
            'completedSubtasks': [],
            'pendingSubtasks': ['merger-remediation-1'],
            'branch': 'feature/agentrunner/merger-passback-remediation',
            'base': 'master',
            'remediation': {
                'attempts': [
                    {
                        'attempt': 1,
                        'subtaskId': 'merger-remediation-1',
                        'queueItemId': f'{initiative_id}-merger-remediation-1',
                        'sourceQueueItemId': f'{initiative_id}-merger',
                        'sourceResultPath': str(state_dir / 'results' / f'{initiative_id}-merger.json'),
                        'requestedAt': '2026-04-20T07:05:00+10:00',
                        'action': 'rebase',
                        'reason': 'Rebase the branch onto master, rerun checks, then return through review and merge retry.',
                        'requiresReReview': True,
                        'requiresMergeRetry': True,
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
                        'closurePhase': 'closure-merger',
                        'closureSourceQueueItemId': f'{initiative_id}-merger',
                        'closureResultPath': str(state_dir / 'results' / f'{initiative_id}-merger.json'),
                        'status': 'queued',
                    }
                ],
                'activeAttempt': 1,
                'lastAttempt': 1,
                'maxAttempts': 2,
            },
            'writtenAt': '2026-04-20T07:10:00+10:00',
        })
        write_json(reviewer_result_path, {
            'status': 'ok',
            'role': 'reviewer',
            'summary': 'Remediation fixes are approved and ready to re-enter closure merge.',
            'approved': True,
            'findings': [],
            'writtenAt': '2026-04-20T07:12:00+10:00',
            'checks': [
                {'name': 'python3 -m py_compile agentrunner/scripts/invoker.py agentrunner/scripts/initiative_coordinator.py', 'status': 'ok'},
            ],
        })
        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': initiative_id,
                'phase': 'execution',
                'statePath': str(initiative_state_path),
            },
            'lastCompleted': {
                'queueItemId': reviewer_qid,
                'role': 'reviewer',
                'queueItem': {
                    'id': reviewer_qid,
                    'project': 'agentrunner',
                    'role': 'reviewer',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/merger-passback-remediation',
                    'base': 'master',
                    'goal': 'Review merger remediation subtask and approve if ready.',
                    'checks': [
                        'python3 -m py_compile agentrunner/scripts/invoker.py agentrunner/scripts/initiative_coordinator.py',
                    ],
                    'contextFiles': ['agentrunner/scripts/invoker.py', 'agentrunner/scripts/initiative_coordinator.py'],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'subtaskId': 'merger-remediation-1',
                        'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
                        'architectPlanPath': str(plan_path),
                        'branch': 'feature/agentrunner/merger-passback-remediation',
                        'base': 'master',
                    },
                },
                'resultPath': str(reviewer_result_path),
                'summary': 'Remediation review approved.',
                'status': 'ok',
            },
            'updatedAt': '2026-04-20T07:12:30+10:00',
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
            raise SystemExit(f'expected remediation approval to queue closure merger retry, got: {changed}')

        queue_after = load_json(queue_path)
        if len(queue_after) != 1:
            raise SystemExit(f'expected one queued merger retry item, got: {queue_after}')
        item = queue_after[0]
        if item.get('role') != 'merger' or item.get('id') != f'{initiative_id}-merger-retry-1':
            raise SystemExit(f'expected merger retry queue item, got: {item}')
        constraints = item.get('constraints') or {}
        if constraints.get('initiativePhase') != 'closure-merger' or constraints.get('closureRemediationAttempt') != 1:
            raise SystemExit(f'expected closure-merger retry constraints, got: {item}')
        if constraints.get('closureSourceQueueItemId') != f'{initiative_id}-merger':
            raise SystemExit(f'expected retry to preserve original closure source queue item, got: {item}')

        initiative_state_after = load_json(initiative_state_path)
        if initiative_state_after.get('phase') != 'closure-merger':
            raise SystemExit(f'expected initiative to return to closure-merger, got: {initiative_state_after}')
        if initiative_state_after.get('currentSubtaskId') is not None:
            raise SystemExit(f'expected remediation currentSubtaskId to clear before merge retry, got: {initiative_state_after}')
        remediation = initiative_state_after.get('remediation') or {}
        if remediation.get('activeAttempt') is not None or remediation.get('lastResolvedAttempt') != 1:
            raise SystemExit(f'expected remediation tracker to resolve active attempt, got: {initiative_state_after}')
        attempts = remediation.get('attempts') or []
        if len(attempts) != 1 or attempts[0].get('status') != 'merge-retry-queued':
            raise SystemExit(f'expected attempt status to advance to merge-retry-queued, got: {initiative_state_after}')

        state_after = load_json(state_path)
        pointer = state_after.get('initiative') or {}
        if pointer.get('initiativeId') != initiative_id or pointer.get('phase') != 'closure-merger':
            raise SystemExit(f'expected state initiative pointer to return to closure-merger, got: {state_after}')

    print('ok: approved merger remediation returns through the normal review lane and re-queues closure merger retry')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
