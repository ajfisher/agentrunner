#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'agentrunner/scripts/enqueue_initiative.py'


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='enqueue-guardrail-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        brief_path = temp_root / 'brief.json'

        initial_state = {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': 'existing-initiative',
                'phase': 'execution',
                'statePath': str(state_dir / 'initiatives/existing-initiative/state.json'),
            },
            'updatedAt': '2026-04-18T00:00:00+00:00',
        }
        write_json(state_path, initial_state)
        write_json(queue_path, [])
        write_json(brief_path, {
            'title': 'Test initiative',
            'objective': 'Prove guardrails.',
            'desiredOutcomes': ['guard conflict'],
            'definitionOfDone': ['reject conflicting enqueue'],
        })

        before_state = state_path.read_text()
        cmd = [
            sys.executable,
            str(repo_path / 'agentrunner/scripts/enqueue_initiative.py'),
            '--project', 'agentrunner',
            '--initiative-id', 'new-initiative',
            '--branch', 'feature/agentrunner/enqueue-cli',
            '--base', 'master',
            '--repo-path', str(repo_path),
            '--state-dir', str(state_dir),
            '--manager-brief-path', str(brief_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            raise SystemExit('expected conflicting enqueue to fail, but it succeeded')
        combined = proc.stdout + proc.stderr
        expected = 'state.json already points at active initiative existing-initiative; refusing to enqueue new-initiative'
        if expected not in combined:
            raise SystemExit(f'missing expected conflict message: {combined}')
        after_state = state_path.read_text()
        if after_state != before_state:
            raise SystemExit('state.json changed despite preflight failure')
        if (state_dir / 'initiatives/new-initiative').exists():
            raise SystemExit('initiative scaffolding was created despite preflight failure')
        if queue_path.read_text() != '[]\n':
            raise SystemExit('queue.json changed despite preflight failure')

    print('ok: conflicting active initiative blocks enqueue without mutating state.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
