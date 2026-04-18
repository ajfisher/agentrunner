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


def run_case(*, state_dir: Path, repo_path: Path, brief_path: Path, initiative_id: str) -> dict:
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
    if proc.returncode != 0:
        raise SystemExit(f'expected noop success, got rc={proc.returncode}: {proc.stdout}{proc.stderr}')
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'expected JSON stdout, got: {proc.stdout}') from exc


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='enqueue-noop-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'title': 'Test initiative',
            'objective': 'Prove noop behaviour.',
            'desiredOutcomes': ['safe noop'],
            'definitionOfDone': ['clear operator output'],
        })

        existing_state_dir = temp_root / 'state-existing'
        write_json(existing_state_dir / 'state.json', {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'updatedAt': '2026-04-18T00:00:00+00:00',
        })
        write_json(existing_state_dir / 'queue.json', [])
        existing_initiative_dir = existing_state_dir / 'initiatives' / 'repeat-initiative'
        write_json(existing_initiative_dir / 'state.json', {
            'initiativeId': 'repeat-initiative',
            'phase': 'design-manager',
        })
        before_existing = (existing_initiative_dir / 'state.json').read_text()
        result_existing = run_case(
            state_dir=existing_state_dir,
            repo_path=repo_path,
            brief_path=brief_path,
            initiative_id='repeat-initiative',
        )
        if result_existing.get('status') != 'noop':
            raise SystemExit(f'unexpected existing-initiative status: {result_existing}')
        if 'initiative already exists' not in result_existing.get('message', ''):
            raise SystemExit(f'missing existing-initiative noop message: {result_existing}')
        if (existing_initiative_dir / 'state.json').read_text() != before_existing:
            raise SystemExit('existing initiative state mutated during noop case')

        pending_state_dir = temp_root / 'state-pending'
        write_json(pending_state_dir / 'state.json', {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'updatedAt': '2026-04-18T00:00:00+00:00',
        })
        pending_item = {
            'id': 'queued-initiative-manager',
            'project': 'agentrunner',
            'role': 'manager',
            'initiative': {
                'initiativeId': 'queued-initiative',
                'phase': 'design-manager',
                'branch': 'feature/agentrunner/enqueue-cli',
                'base': 'master',
            },
        }
        write_json(pending_state_dir / 'queue.json', [pending_item])
        before_queue = (pending_state_dir / 'queue.json').read_text()
        result_pending = run_case(
            state_dir=pending_state_dir,
            repo_path=repo_path,
            brief_path=brief_path,
            initiative_id='queued-initiative',
        )
        if result_pending.get('status') != 'noop':
            raise SystemExit(f'unexpected pending-kickoff status: {result_pending}')
        if 'kickoff already pending' not in result_pending.get('message', ''):
            raise SystemExit(f'missing pending-kickoff noop message: {result_pending}')
        if (pending_state_dir / 'queue.json').read_text() != before_queue:
            raise SystemExit('queue mutated during pending kickoff noop case')

    print('ok: existing initiative and pending kickoff return safe noop output without mutation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
