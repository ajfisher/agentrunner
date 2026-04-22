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
    with tempfile.TemporaryDirectory(prefix='invoker-closure-handoff-adoption-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        initiative_id = 'closure-handoff-adoption'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        decision_path = state_dir / 'initiatives' / initiative_id / 'decision.json'

        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'review-manager',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
            'managerDecisionPath': str(decision_path),
            'currentSubtaskId': None,
            'completedSubtasks': ['watcher-handoff-adoption'],
            'pendingSubtasks': [],
            'branch': 'feature/agentrunner/closure-handoff-state-semantics',
            'base': 'main',
            'writtenAt': '2026-04-21T01:58:00+00:00',
        })
        write_json(decision_path, {
            'initiativeId': initiative_id,
            'decision': 'complete',
            'summary': 'Closure review says this should proceed to merger.',
            'writtenAt': '2026-04-21T01:59:00+00:00',
        })
        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': initiative_id,
                'phase': 'review-manager',
                'statePath': str(initiative_state_path),
            },
            'lastCompleted': {
                'queueItemId': f'{initiative_id}-manager-review',
                'role': 'manager',
                'queueItem': {
                    'id': f'{initiative_id}-manager-review',
                    'project': 'agentrunner',
                    'role': 'manager',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/closure-handoff-state-semantics',
                    'base': 'main',
                    'initiative': {
                        'initiativeId': initiative_id,
                        'phase': 'review-manager',
                        'branch': 'feature/agentrunner/closure-handoff-state-semantics',
                        'base': 'main',
                    },
                },
                'resultPath': str(state_dir / 'results' / f'{initiative_id}-manager-review.json'),
                'summary': 'Manager closure review completed.',
                'status': 'ok',
            },
            'updatedAt': '2026-04-21T02:00:00+00:00',
        })
        write_json(state_dir / 'results' / f'{initiative_id}-manager-review.json', {
            'status': 'ok',
            'role': 'manager',
            'summary': 'Manager closure review completed.',
            'writtenAt': '2026-04-21T01:59:00+00:00',
            'checks': [],
        })
        write_json(queue_path, [])

        proc = subprocess.run([
            sys.executable,
            str(repo_path / 'agentrunner/scripts/invoker.py'),
            '--project', 'agentrunner',
            '--state-dir', str(state_dir),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f'invoker failed: {proc.stdout}{proc.stderr}')

        queue_after = load_json(queue_path)
        state_after = load_json(state_path)
        current_after = state_after.get('current') if isinstance(state_after.get('current'), dict) else None
        merger_item = queue_after[0] if queue_after else current_after.get('queueItem') if current_after and isinstance(current_after.get('queueItem'), dict) else None
        if not isinstance(merger_item, dict) or merger_item.get('role') != 'merger':
            raise SystemExit(
                'invoker should have adopted closure-unsafe review-manager into a merger handoff, '
                f'got queue={queue_after} current={current_after}'
            )
        if merger_item.get('initiative', {}).get('phase') != 'closure-merger':
            raise SystemExit(f'expected closure-merger follow-up item, got: {merger_item}')

        if state_after.get('initiative', {}).get('phase') != 'closure-merger':
            raise SystemExit(f'initiative pointer should move into closure-merger after coordinator adoption, got: {state_after.get("initiative")}')

    print('ok: invoker keeps watching closure-unsafe quiet states and adopts the next closure handoff')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
