#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'agentrunner/scripts/operator_cli.py'


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['python3', str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_in(text: str, needle: str) -> None:
    assert needle in text, f'missing {needle!r} in output:\n{text}'


def test_status_prefers_artifact_when_present(state_dir: Path) -> None:
    write_json(state_dir / 'operator_status.json', {
        'project': 'demo',
        'status': 'active',
        'updatedAt': '2026-04-19T00:00:00Z',
        'current': {
            'queueItemId': 'developer-docs',
            'role': 'developer',
            'branch': 'feature/agentrunner/queue-status-cli',
            'startedAt': '2026-04-19T00:00:00Z',
            'ageSeconds': 42,
        },
        'queue': {
            'depth': 2,
            'nextIds': ['reviewer-docs', 'manager-wrap'],
            'preview': [
                {
                    'queueItemId': 'reviewer-docs',
                    'role': 'reviewer',
                    'branch': 'feature/agentrunner/queue-status-cli',
                    'goal': 'Review the CLI docs changes.',
                },
                {
                    'queueItemId': 'manager-wrap',
                    'role': 'manager',
                    'branch': 'feature/agentrunner/queue-status-cli',
                    'goal': 'Close the initiative loop cleanly.',
                },
            ],
        },
        'initiative': {
            'initiativeId': 'agentrunner-queue-status-cli',
            'phase': 'implementation',
            'currentSubtaskId': 'docs-and-proof-coverage',
        },
        'lastCompleted': {
            'queueItemId': 'architect-plan',
            'role': 'architect',
            'status': 'ok',
            'summary': 'Clarified the operator surface split.',
            'endedAt': '2026-04-18T23:55:00Z',
        },
        'resultHint': 'Clarified the operator surface split.',
        'warnings': [],
    })

    result = run_cli('status', '--state-dir', str(state_dir))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert_in(result.stdout, 'project: demo')
    assert_in(result.stdout, 'status: ACTIVE | developer-docs | developer | feature/agentrunner/queue-status-cli | age=42s')
    assert_in(result.stdout, 'queue: 2 item(s) | next=reviewer-docs, manager-wrap')
    assert_in(result.stdout, 'initiative: agentrunner-queue-status-cli | phase=implementation | subtask=docs-and-proof-coverage')
    assert_in(result.stdout, 'last completed: architect-plan | architect | ok | 2026-04-18T23:55:00Z | Clarified the operator surface split.')
    assert_in(result.stdout, 'warnings: -')
    assert 'rebuild' not in result.stdout.lower(), result.stdout


def test_missing_artifact_stays_explicit_without_raw_file_archaeology(state_dir: Path) -> None:
    result = run_cli('status', '--state-dir', str(state_dir))

    assert result.returncode == 1, result.stdout
    assert result.stderr == ''
    assert_in(result.stdout, f'warning: operator status artifact missing at {state_dir / "operator_status.json"}')
    assert_in(result.stdout, 'hint: rerun with --rebuild-missing for a bounded manual rebuild')
    assert 'traceback' not in result.stdout.lower(), result.stdout
    assert 'queue.json' not in result.stdout, result.stdout
    assert 'ticks.ndjson' not in result.stdout, result.stdout


def test_missing_artifact_can_rebuild_and_write_when_explicit(state_dir: Path) -> None:
    write_json(state_dir / 'state.json', {
        'project': 'demo',
        'running': False,
        'updatedAt': '2026-04-19T00:03:00Z',
        'current': None,
        'lastCompleted': {
            'queueItemId': 'developer-proof',
            'role': 'developer',
            'status': 'ok',
            'endedAt': '2026-04-19T00:02:00Z',
        },
    })
    write_json(state_dir / 'queue.json', [
        {
            'id': 'reviewer-proof',
            'role': 'reviewer',
            'branch': 'feature/agentrunner/queue-status-cli',
            'goal': 'Review proof coverage for artifact-first reads.',
        }
    ])

    result = run_cli(
        'status',
        '--state-dir', str(state_dir),
        '--rebuild-missing',
        '--write-rebuild',
    )

    assert result.returncode == 0, result.stdout
    assert result.stderr == ''
    assert_in(result.stdout, 'project: demo')
    assert_in(result.stdout, 'status: IDLE')
    assert_in(result.stdout, 'queue: 1 item(s) | next=reviewer-proof')
    assert_in(result.stdout, 'notes:')
    assert_in(result.stdout, 'rebuilt operator status from mechanics files because --rebuild-missing was set')
    assert_in(result.stdout, f'info: wrote {state_dir / "operator_status.json"}')
    assert (state_dir / 'operator_status.json').exists()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='operator-cli-') as tmp:
        root = Path(tmp)
        test_status_prefers_artifact_when_present(root / 'artifact-present')
        test_missing_artifact_stays_explicit_without_raw_file_archaeology(root / 'artifact-missing')
        test_missing_artifact_can_rebuild_and_write_when_explicit(root / 'artifact-rebuild')
    print('ok: operator CLI proof covers artifact-present and artifact-missing paths with readable operator output')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
