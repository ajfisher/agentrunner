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


def run(repo_path: Path, script: str, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(repo_path / script), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f'{script} failed: {proc.stdout}{proc.stderr}')
    return json.loads(proc.stdout)


def run_tail_case_regression(temp_root: Path) -> None:
    repo_path = temp_root / 'repo'
    shutil.copytree(ROOT, repo_path)

    state_dir = temp_root / 'state'
    state_path = state_dir / 'state.json'
    queue_path = state_dir / 'queue.json'
    initiative_id = 'tail-case-terminal-success'
    merger_qid = f'{initiative_id}-merger'
    initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
    result_path = state_dir / 'results' / f'{merger_qid}.json'

    stale_tail_id = f'{initiative_id}-developer-tail'
    unrelated_tail_id = 'other-initiative-manager'

    write_json(queue_path, [
        {
            'id': stale_tail_id,
            'project': 'agentrunner',
            'role': 'developer',
            'createdAt': '2026-04-19T06:20:00+00:00',
            'repo_path': str(repo_path),
            'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
            'base': 'main',
            'goal': 'Stale same-initiative tail item that should be scrubbed after merge success.',
            'checks': [],
            'constraints': {},
            'contextFiles': [],
            'initiative': {
                'initiativeId': initiative_id,
                'subtaskId': 'stale-tail',
                'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                'base': 'main',
            },
        },
        {
            'id': unrelated_tail_id,
            'project': 'agentrunner',
            'role': 'manager',
            'createdAt': '2026-04-19T06:20:30+00:00',
            'repo_path': str(repo_path),
            'branch': 'feature/agentrunner/other-initiative',
            'base': 'main',
            'goal': 'Unrelated queued work must continue to block idle finalization.',
            'checks': [],
            'constraints': {},
            'contextFiles': [],
            'initiative': {
                'initiativeId': 'other-initiative',
                'phase': 'design-manager',
                'branch': 'feature/agentrunner/other-initiative',
                'base': 'main',
            },
        },
    ])
    write_json(initiative_state_path, {
        'initiativeId': initiative_id,
        'phase': 'closure-merger',
        'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
        'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
        'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
        'currentSubtaskId': None,
        'completedSubtasks': ['prove-tail-case-with-regression'],
        'pendingSubtasks': [],
        'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
        'base': 'main',
        'writtenAt': '2026-04-19T06:19:00+00:00',
    })
    write_json(result_path, {
        'status': 'ok',
        'role': 'merger',
        'summary': 'Fast-forward merge completed.',
        'merged': True,
        'commit': 'abc1234',
        'writtenAt': '2026-04-19T06:21:00+00:00',
        'checks': [],
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
                'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                'base': 'main',
                'goal': 'Finalize tail-case initiative with ff-only merge.',
                'checks': [],
                'initiative': {
                    'initiativeId': initiative_id,
                    'phase': 'closure-merger',
                    'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                    'base': 'main',
                },
            },
            'resultPath': str(result_path),
            'summary': 'Merge succeeded.',
            'status': 'ok',
        },
        'updatedAt': '2026-04-19T06:20:30+00:00',
    })

    changed = run(repo_path, 'agentrunner/scripts/initiative_coordinator.py', '--state-dir', str(state_dir))
    if changed != {'changed': False}:
        raise SystemExit(f'expected unrelated queued work to keep state non-idle, got: {changed}')

    queue_after_first_pass = load_json(queue_path)
    if [item.get('id') for item in queue_after_first_pass] != [unrelated_tail_id]:
        raise SystemExit(f'same-initiative tail item was not scrubbed correctly: {queue_after_first_pass}')

    state_after_first_pass = load_json(state_path)
    if state_after_first_pass.get('initiative', {}).get('initiativeId') != initiative_id:
        raise SystemExit(f'initiative pointer should remain active until the queue is otherwise idle: {state_after_first_pass}')

    initiative_state_mid = load_json(initiative_state_path)
    if initiative_state_mid.get('phase') != 'closure-merger':
        raise SystemExit(f'unrelated queued work should keep initiative active until idle: {initiative_state_mid}')

    write_json(queue_path, [])
    changed = run(repo_path, 'agentrunner/scripts/initiative_coordinator.py', '--state-dir', str(state_dir))
    if changed != {'changed': True}:
        raise SystemExit(f'expected successful merger tail cleanup to finalize once idle, got: {changed}')

    state_after = load_json(state_path)
    if state_after.get('running') is not False or state_after.get('current') is not None:
        raise SystemExit(f'expected final project state to be idle, got: {state_after}')
    if 'initiative' in state_after:
        raise SystemExit(f'expected final state to clear initiative pointer, got: {state_after}')

    queue_after = load_json(queue_path)
    if queue_after != []:
        raise SystemExit(f'expected queue to be empty after finalization, got: {queue_after}')

    initiative_state_after = load_json(initiative_state_path)
    if initiative_state_after.get('phase') != 'completed':
        raise SystemExit(f'expected initiative phase completed after finalization, got: {initiative_state_after}')
    if initiative_state_after.get('currentSubtaskId') is not None:
        raise SystemExit(f'expected currentSubtaskId cleared after finalization, got: {initiative_state_after}')


def test_merger_tail_cleanup_scrubs_same_initiative_items_before_idle_finalization(tmp_path: Path) -> None:
    run_tail_case_regression(tmp_path)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='initiative-tail-cleanup-regression-') as tmp:
        run_tail_case_regression(Path(tmp))
    print('ok: merger tail cleanup scrubs same-initiative tails and finalizes only when the remaining queue is truly idle')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
