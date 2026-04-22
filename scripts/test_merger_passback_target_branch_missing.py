#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / 'agentrunner' / 'scripts'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from invoker import validate_result_artifact  # noqa: E402


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')


def load_json(path: Path):
    return json.loads(path.read_text())


def blocked_target_branch_missing_result(branch: str, base: str) -> dict:
    return {
        'status': 'blocked',
        'role': 'merger',
        'summary': f'Merge blocked; local target branch {base} is missing, so branch normalization must run before merge retry.',
        'merged': False,
        'commit': 'abc1234',
        'writtenAt': '2026-04-22T13:05:00+10:00',
        'checks': [
            {'name': f'git diff --stat {base}...{branch}', 'status': 'blocked'},
            {'name': f'git rev-parse --verify {base}', 'status': 'blocked'},
        ],
        'mergeBlocker': {
            'classification': 'repairable',
            'kind': 'target_branch_missing',
            'detail': f"QUEUE_ITEM_JSON.base requested '{base}', but the repo has no local '{base}' ref yet.",
            'passback': {
                'targetRole': 'developer',
                'action': 'normalize-base-branch',
                'reason': f"Create or normalize the local '{base}' branch to the intended target tip, rerun merger checks, and then retry merge.",
                'requiresReReview': False,
                'requiresMergeRetry': True,
            },
        },
    }


def prove_validation_accepts_target_branch_missing() -> None:
    normalized, errors = validate_result_artifact(
        blocked_target_branch_missing_result(
            branch='feature/agentrunner/repairable-merger-blocker-alignment',
            base='main',
        ),
        expected_role='merger',
    )
    if errors:
        raise SystemExit(f'expected target_branch_missing artifact to validate cleanly, got: {errors}')
    if not normalized or normalized.get('mergeBlocker', {}).get('kind') != 'target_branch_missing':
        raise SystemExit(f'expected validated result to preserve target_branch_missing blocker, got: {normalized}')


def prove_closure_remediation_routes_target_branch_missing() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-target-branch-missing-passback-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        initiative_id = 'agentrunner-target-branch-missing-passback'
        merger_qid = f'{initiative_id}-merger'
        result_path = state_dir / 'results' / f'{merger_qid}.json'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        branch = 'feature/agentrunner/repairable-merger-blocker-alignment'
        base = 'main'

        write_json(queue_path, [])
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
            'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
            'currentSubtaskId': None,
            'completedSubtasks': ['main-branch-normalization-proof'],
            'pendingSubtasks': [],
            'branch': branch,
            'base': base,
            'writtenAt': '2026-04-22T13:00:00+10:00',
        })
        write_json(result_path, blocked_target_branch_missing_result(branch, base))
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
                    'branch': branch,
                    'base': base,
                    'goal': 'Attempt ff-only merge for initiative closure after main-branch normalization.',
                    'checks': [
                        f'git diff --stat {base}...{branch}',
                        f'git rev-parse --verify {base}',
                    ],
                    'contextFiles': ['agentrunner/scripts/invoker.py', 'agentrunner/scripts/initiative_coordinator.py'],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'phase': 'closure-merger',
                        'branch': branch,
                        'base': base,
                    },
                },
                'resultPath': str(result_path),
                'summary': 'Merge blocked because the local target branch is missing.',
                'status': 'blocked',
            },
            'updatedAt': '2026-04-22T13:05:30+10:00',
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
            raise SystemExit(f'expected target_branch_missing remediation routing to change queue/state, got: {changed}')

        queue_after = load_json(queue_path)
        if len(queue_after) != 1:
            raise SystemExit(f'expected one queued remediation item, got: {queue_after}')
        item = queue_after[0]
        if item.get('role') != 'developer':
            raise SystemExit(f'expected queued remediation role developer, got: {item}')
        if item.get('branch') != branch or item.get('base') != base:
            raise SystemExit(f'expected queued remediation to preserve branch/base context, got: {item}')
        if 'normalize-base-branch' not in (item.get('goal') or ''):
            raise SystemExit(f'expected queued remediation goal to preserve the normalization action, got: {item}')

        constraints = item.get('constraints') or {}
        if constraints.get('closureRemediation') is not True or constraints.get('requiresReReview') is not False:
            raise SystemExit(f'expected bounded remediation constraints for normalization passback, got: {item}')
        if constraints.get('requiresMergeRetry') is not True:
            raise SystemExit(f'expected merge retry requirement to be preserved, got: {item}')

        origin = item.get('origin') or {}
        blocker = origin.get('mergeBlocker') or {}
        if blocker.get('kind') != 'target_branch_missing':
            raise SystemExit(f'expected queued remediation origin to retain target_branch_missing blocker, got: {item}')
        if blocker.get('passback', {}).get('action') != 'normalize-base-branch':
            raise SystemExit(f'expected queued remediation origin to retain normalization action, got: {item}')

        initiative_state_after = load_json(initiative_state_path)
        remediation = initiative_state_after.get('remediation') or {}
        attempts = remediation.get('attempts') or []
        if len(attempts) != 1:
            raise SystemExit(f'expected one remediation attempt record, got: {initiative_state_after}')
        attempt = attempts[0]
        if attempt.get('action') != 'normalize-base-branch':
            raise SystemExit(f'expected remediation attempt to preserve normalization action, got: {attempt}')
        if attempt.get('requiresReReview') is not False or attempt.get('requiresMergeRetry') is not True:
            raise SystemExit(f'expected remediation attempt retry semantics to be preserved, got: {attempt}')
        if initiative_state_after.get('phase') != 'execution' or initiative_state_after.get('currentSubtaskId') != 'merger-remediation-1':
            raise SystemExit(f'expected initiative to re-enter execution with bounded remediation subtask, got: {initiative_state_after}')


def main() -> int:
    prove_validation_accepts_target_branch_missing()
    prove_closure_remediation_routes_target_branch_missing()
    print('ok: target_branch_missing repairable blockers validate cleanly and route into the bounded developer normalization passback flow')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
