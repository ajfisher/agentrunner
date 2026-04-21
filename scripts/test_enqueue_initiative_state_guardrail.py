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


def assert_conflicting_enqueue_blocked(*, repo_path: Path, state_dir: Path, initiative_id: str, expected: str, brief_path: Path) -> None:
    state_path = state_dir / 'state.json'
    queue_path = state_dir / 'queue.json'
    before_state = state_path.read_text()
    before_queue = queue_path.read_text()

    cmd = [
        sys.executable,
        str(repo_path / 'agentrunner/scripts/enqueue_initiative.py'),
        '--project', 'agentrunner',
        '--initiative-id', initiative_id,
        '--branch', 'feature/agentrunner/enqueue-cli',
        '--base', 'master',
        '--repo-path', str(repo_path),
        '--state-dir', str(state_dir),
        '--manager-brief-path', str(brief_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        raise SystemExit(f'expected conflicting enqueue for {initiative_id} to fail, but it succeeded')
    combined = proc.stdout + proc.stderr
    if expected not in combined:
        raise SystemExit(f'missing expected conflict message for {initiative_id}: {combined}')

    after_state = state_path.read_text()
    if after_state != before_state:
        raise SystemExit(f'state.json changed despite preflight failure for {initiative_id}')
    after_queue = queue_path.read_text()
    if after_queue != before_queue:
        raise SystemExit(f'queue.json changed despite preflight failure for {initiative_id}')
    if (state_dir / f'initiatives/{initiative_id}').exists():
        raise SystemExit(f'initiative scaffolding was created for blocked enqueue {initiative_id}')


def assert_clean_tail_enqueue_allowed(*, repo_path: Path, state_dir: Path, brief_path: Path) -> None:
    runtime_repo = state_dir / 'runtime-repo'
    runtime_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-b', 'feature/agentrunner/clear-stale-initiative-pointer'], cwd=runtime_repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'config', 'user.name', 'AgentRunner Tests'], cwd=runtime_repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'tests@example.invalid'], cwd=runtime_repo, check=True)
    (runtime_repo / 'README.md').write_text('ok\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=runtime_repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'initial'], cwd=runtime_repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'branch', 'master'], cwd=runtime_repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'checkout', 'master'], cwd=runtime_repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'merge', '--ff-only', 'feature/agentrunner/clear-stale-initiative-pointer'], cwd=runtime_repo, check=True, capture_output=True, text=True)

    state = json.loads((state_dir / 'state.json').read_text())
    state['initiative']['phase'] = 'completed'
    state['lastCompleted']['queueItem']['repo_path'] = str(runtime_repo)
    (state_dir / 'state.json').write_text(json.dumps(state, indent=2) + '\n')

    initiative_state_path = Path(state['initiative']['statePath'])
    initiative_state = json.loads(initiative_state_path.read_text())
    initiative_state['phase'] = 'completed'
    initiative_state_path.write_text(json.dumps(initiative_state, indent=2) + '\n')

    cmd = [
        sys.executable,
        str(repo_path / 'agentrunner/scripts/enqueue_initiative.py'),
        '--project', 'agentrunner',
        '--initiative-id', 'fresh-initiative',
        '--branch', 'feature/agentrunner/fresh-initiative',
        '--base', 'master',
        '--repo-path', str(repo_path),
        '--state-dir', str(state_dir),
        '--manager-brief-path', str(brief_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f'expected clean tail enqueue to succeed, got rc={proc.returncode}: {proc.stdout}{proc.stderr}')
    result = json.loads(proc.stdout)
    if result.get('status') != 'ok':
        raise SystemExit(f'unexpected clean tail enqueue result: {result}')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='enqueue-guardrail-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        brief_path = temp_root / 'brief.json'

        write_json(queue_path, [])
        write_json(brief_path, {
            'title': 'Test initiative',
            'objective': 'Prove guardrails.',
            'desiredOutcomes': ['guard conflict'],
            'definitionOfDone': ['reject conflicting enqueue'],
        })

        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': 'existing-initiative',
                'phase': 'execution',
                'statePath': str(state_dir / 'initiatives/existing-initiative/state.json'),
            },
            'updatedAt': '2026-04-18T00:00:00+00:00',
        })
        assert_conflicting_enqueue_blocked(
            repo_path=repo_path,
            state_dir=state_dir,
            initiative_id='new-initiative',
            expected='state.json already points at active initiative existing-initiative; refusing to enqueue new-initiative',
            brief_path=brief_path,
        )

        write_json(state_dir / 'initiatives' / 'closed-initiative' / 'state.json', {
            'initiativeId': 'closed-initiative',
            'phase': 'closure-merger',
            'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
            'base': 'master',
        })
        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': 'closed-initiative',
                'phase': 'closure-merger',
                'statePath': str(state_dir / 'initiatives/closed-initiative/state.json'),
            },
            'lastCompleted': {
                'queueItemId': 'closed-initiative-merger',
                'role': 'merger',
                'queueItem': {
                    'id': 'closed-initiative-merger',
                    'project': 'agentrunner',
                    'role': 'merger',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
                    'base': 'master',
                    'initiative': {
                        'initiativeId': 'closed-initiative',
                        'phase': 'closure-merger',
                        'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
                        'base': 'master',
                    },
                },
                'resultPath': str(state_dir / 'results/closed-initiative-merger.json'),
                'summary': 'Merge blocked.',
                'status': 'blocked',
            },
            'updatedAt': '2026-04-19T00:00:00+00:00',
        })
        assert_conflicting_enqueue_blocked(
            repo_path=repo_path,
            state_dir=state_dir,
            initiative_id='fresh-initiative',
            expected='state.json already points at active initiative closed-initiative; refusing to enqueue fresh-initiative',
            brief_path=brief_path,
        )

        write_json(state_dir / 'initiatives' / 'replan-initiative' / 'state.json', {
            'initiativeId': 'replan-initiative',
            'phase': 'replan-architect',
            'branch': 'feature/agentrunner/replan-still-live',
            'base': 'master',
        })
        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': 'replan-initiative',
                'phase': 'replan-architect',
                'statePath': str(state_dir / 'initiatives/replan-initiative/state.json'),
            },
            'updatedAt': '2026-04-19T00:05:00+00:00',
        })
        write_json(queue_path, [])
        assert_conflicting_enqueue_blocked(
            repo_path=repo_path,
            state_dir=state_dir,
            initiative_id='fresh-initiative',
            expected='state.json already points at active initiative replan-initiative; refusing to enqueue fresh-initiative',
            brief_path=brief_path,
        )

        write_json(state_path, {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': 'closed-initiative',
                'phase': 'closure-merger',
                'statePath': str(state_dir / 'initiatives/closed-initiative/state.json'),
            },
            'lastCompleted': {
                'queueItemId': 'closed-initiative-merger',
                'role': 'merger',
                'queueItem': {
                    'id': 'closed-initiative-merger',
                    'project': 'agentrunner',
                    'role': 'merger',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
                    'base': 'master',
                    'initiative': {
                        'initiativeId': 'closed-initiative',
                        'phase': 'closure-merger',
                        'branch': 'feature/agentrunner/clear-stale-initiative-pointer',
                        'base': 'master',
                    },
                },
                'resultPath': str(state_dir / 'results/closed-initiative-merger.json'),
                'summary': 'Merge blocked.',
                'status': 'blocked',
            },
            'updatedAt': '2026-04-19T00:10:00+00:00',
        })

        assert_clean_tail_enqueue_allowed(
            repo_path=repo_path,
            state_dir=state_dir,
            brief_path=brief_path,
        )

    print('ok: active initiative pointers still block real conflicts, while clean merged tails no longer block fresh enqueue attempts')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
