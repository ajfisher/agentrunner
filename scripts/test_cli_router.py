#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def run_module(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-m', 'agentrunner', *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_module_router_delegates_status_from_checkout() -> None:
    with tempfile.TemporaryDirectory(prefix='agentrunner-cli-router-') as tmp:
        state_dir = Path(tmp)
        write_json(state_dir / 'operator_status.json', {
            'project': 'demo',
            'status': 'active',
            'updatedAt': '2026-04-19T00:00:00Z',
            'current': {
                'queueItemId': 'developer-router',
                'role': 'developer',
                'branch': 'feature/agentrunner/real-cli-surface',
                'startedAt': '2026-04-19T00:00:00Z',
                'ageSeconds': 11,
            },
            'queue': {'depth': 0, 'nextIds': [], 'preview': []},
            'initiative': {
                'initiativeId': 'agentrunner-real-cli-surface',
                'phase': 'implementation',
                'currentSubtaskId': 'entrypoint-and-router',
            },
            'lastCompleted': None,
            'resultHint': None,
            'warnings': [],
        })

        result = run_module('status', '--state-dir', str(state_dir))

        assert result.returncode == 0, result.stderr
        assert result.stderr == ''
        assert 'project: demo' in result.stdout
        assert 'developer-router' in result.stdout
        assert 'feature/agentrunner/real-cli-surface' in result.stdout


def test_module_router_strips_optional_passthrough_separator() -> None:
    with tempfile.TemporaryDirectory(prefix='agentrunner-cli-router-sep-') as tmp:
        state_dir = Path(tmp)
        write_json(state_dir / 'operator_status.json', {
            'project': 'demo',
            'status': 'idle',
            'updatedAt': '2026-04-19T00:00:00Z',
            'current': None,
            'queue': {'depth': 0, 'nextIds': [], 'preview': []},
            'initiative': None,
            'lastCompleted': None,
            'resultHint': None,
            'warnings': [],
        })

        result = run_module('status', '--', '--state-dir', str(state_dir))

        assert result.returncode == 0, result.stderr
        assert result.stderr == ''
        assert 'status: IDLE' in result.stdout


def test_console_script_works_after_install_from_checkout() -> None:
    with tempfile.TemporaryDirectory(prefix='agentrunner-console-venv-') as tmp:
        venv_dir = Path(tmp) / 'venv'
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(venv_dir)
        python_bin = venv_dir / 'bin' / 'python'
        agentrunner_bin = venv_dir / 'bin' / 'agentrunner'

        install = subprocess.run(
            [str(python_bin), '-m', 'pip', 'install', '--quiet', '.'],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert install.returncode == 0, install.stderr

        state_dir = Path(tmp) / 'installed-state'
        write_json(state_dir / 'operator_status.json', {
            'project': 'demo',
            'status': 'idle',
            'updatedAt': '2026-04-19T00:00:00Z',
            'current': None,
            'queue': {'depth': 0, 'nextIds': [], 'preview': []},
            'initiative': None,
            'lastCompleted': None,
            'resultHint': None,
            'warnings': [],
        })

        result = subprocess.run(
            [str(agentrunner_bin), 'status', '--state-dir', str(state_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert result.stderr == ''
        assert 'project: demo' in result.stdout
        assert 'status: IDLE' in result.stdout


def main() -> int:
    test_module_router_delegates_status_from_checkout()
    test_module_router_strips_optional_passthrough_separator()
    test_console_script_works_after_install_from_checkout()
    print('ok: top-level router works from checkout and installed console entrypoint')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
