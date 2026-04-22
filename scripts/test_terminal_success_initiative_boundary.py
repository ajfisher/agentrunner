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


def run_coordinator(repo_path: Path, state_dir: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_path / 'agentrunner/scripts/initiative_coordinator.py'),
            '--state-dir',
            str(state_dir),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f'initiative coordinator failed: {proc.stdout}{proc.stderr}')
    return json.loads(proc.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='terminal-success-boundary-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        initiative_id = 'tail-case-terminal-success'
        stray_queue_item_id = f'{initiative_id}-merger-followup-1'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        result_path = state_dir / 'results' / f'{stray_queue_item_id}.json'

        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'lastCompleted': {
                'queueItemId': stray_queue_item_id,
                'role': 'developer',
                'queueItem': {
                    'id': stray_queue_item_id,
                    'project': 'agentrunner',
                    'role': 'developer',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                    'base': 'main',
                    'goal': 'Stray follow-up after merger success.',
                    'checks': ['python3 -m py_compile agentrunner/scripts/initiative_coordinator.py agentrunner/scripts/invoker.py'],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'subtaskId': 'audit-terminal-success-transition',
                        'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                        'base': 'main',
                    },
                },
                'resultPath': str(result_path),
                'summary': 'Follow-up item finished after merge.',
                'status': 'ok',
            },
            'updatedAt': '2026-04-19T00:00:00+00:00',
        })
        write_json(queue_path, [])
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'completed',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
            'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
            'currentSubtaskId': None,
            'completedSubtasks': ['audit-terminal-success-transition'],
            'pendingSubtasks': [],
            'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
            'base': 'main',
            'writtenAt': '2026-04-19T00:00:00+00:00',
        })
        write_json(result_path, {
            'status': 'ok',
            'role': 'developer',
            'summary': 'Stray follow-up item should not reopen initiative state.',
            'commit': 'deadbeef',
            'checks': [
                {
                    'name': 'python3 -m py_compile agentrunner/scripts/initiative_coordinator.py agentrunner/scripts/invoker.py',
                    'status': 'ok',
                }
            ],
            'writtenAt': '2026-04-19T00:00:01+00:00',
        })

        changed = run_coordinator(repo_path, state_dir)
        if changed != {'changed': False}:
            raise SystemExit(f'expected no phase advancement for completed initiative, got: {changed}')

        state_after = load_json(state_path)
        if 'initiative' in state_after:
            raise SystemExit(f'completed initiative was incorrectly re-pointed into state.json: {state_after["initiative"]}')

        initiative_state_after = load_json(initiative_state_path)
        if initiative_state_after.get('phase') != 'completed':
            raise SystemExit(f'completed initiative was mutated unexpectedly: {initiative_state_after}')

    print('ok: completed initiatives stay terminal even if a stray follow-up item lands later')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
