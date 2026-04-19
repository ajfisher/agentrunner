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
    with tempfile.TemporaryDirectory(prefix='initiative-pointer-cleanup-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        brief_path = temp_root / 'brief.json'
        initiative_id = 'closed-initiative'
        merger_queue_item_id = f'{initiative_id}-merger'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        result_path = state_dir / 'results' / f'{merger_queue_item_id}.json'

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
                'queueItemId': merger_queue_item_id,
                'role': 'merger',
                'queueItem': {
                    'id': merger_queue_item_id,
                    'project': 'agentrunner',
                    'role': 'merger',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
                    'base': 'master',
                    'initiative': {
                        'initiativeId': initiative_id,
                        'phase': 'closure-merger',
                        'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
                        'base': 'master',
                    },
                },
                'resultPath': str(result_path),
                'summary': 'Merged successfully.',
                'status': 'ok',
            },
            'updatedAt': '2026-04-19T00:00:00+00:00',
        })
        write_json(queue_path, [])
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
            'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
            'currentSubtaskId': None,
            'completedSubtasks': ['enqueue-regression-success-path'],
            'pendingSubtasks': [],
            'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
            'base': 'master',
            'writtenAt': '2026-04-19T00:00:00+00:00',
        })
        write_json(result_path, {
            'status': 'ok',
            'role': 'merger',
            'summary': 'Fast-forward merge completed.',
            'merged': True,
            'writtenAt': '2026-04-19T00:00:01+00:00',
        })
        write_json(brief_path, {
            'title': 'Fresh initiative after cleanup',
            'objective': 'Prove stale initiative pointer cleanup unblocks the next enqueue.',
            'desiredOutcomes': ['new kickoff enqueued cleanly'],
            'definitionOfDone': ['state pointer cleared', 'subsequent enqueue succeeds'],
        })

        proc = subprocess.run([
            sys.executable,
            str(repo_path / 'agentrunner/scripts/initiative_coordinator.py'),
            '--state-dir', str(state_dir),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f'initiative coordinator failed: {proc.stdout}{proc.stderr}')
        changed = json.loads(proc.stdout)
        if changed != {'changed': True}:
            raise SystemExit(f'expected coordinator to report change, got: {changed}')

        state_after = load_json(state_path)
        if 'initiative' in state_after:
            raise SystemExit(f'state.json still has stale initiative pointer: {state_after["initiative"]}')

        initiative_state_after = load_json(initiative_state_path)
        if initiative_state_after.get('phase') != 'completed':
            raise SystemExit(f'initiative state was not finalized: {initiative_state_after}')
        if initiative_state_after.get('currentSubtaskId') is not None:
            raise SystemExit(f'initiative currentSubtaskId was not cleared: {initiative_state_after}')

        enqueue_proc = subprocess.run([
            sys.executable,
            str(repo_path / 'agentrunner/scripts/enqueue_initiative.py'),
            '--project', 'agentrunner',
            '--initiative-id', 'fresh-initiative',
            '--branch', 'feature/agentrunner/next-initiative',
            '--base', 'master',
            '--repo-path', str(repo_path),
            '--state-dir', str(state_dir),
            '--manager-brief-path', str(brief_path),
        ], capture_output=True, text=True)
        if enqueue_proc.returncode != 0:
            raise SystemExit(f'expected subsequent enqueue to succeed, got rc={enqueue_proc.returncode}: {enqueue_proc.stdout}{enqueue_proc.stderr}')
        try:
            enqueue_result = json.loads(enqueue_proc.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(f'expected enqueue JSON stdout, got: {enqueue_proc.stdout}') from exc

        if enqueue_result.get('status') != 'ok':
            raise SystemExit(f'unexpected enqueue result: {enqueue_result}')

        queue_after = load_json(queue_path)
        if not isinstance(queue_after, list) or not queue_after:
            raise SystemExit(f'queue missing newly enqueued kickoff item: {queue_after}')
        kickoff = queue_after[0]
        if kickoff.get('id') != 'fresh-initiative-manager':
            raise SystemExit(f'unexpected kickoff item id: {kickoff}')
        if kickoff.get('initiative', {}).get('initiativeId') != 'fresh-initiative':
            raise SystemExit(f'unexpected kickoff initiative metadata: {kickoff}')

    print('ok: successful initiative closure clears stale pointer and allows subsequent enqueue')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
