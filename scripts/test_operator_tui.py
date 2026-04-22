#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def sample_artifact(*, status: str = 'blocked', warnings: list[dict] | None = None) -> dict:
    return {
        'project': 'demo',
        'status': status,
        'updatedAt': '2026-04-20T00:45:00Z',
        'current': {
            'queueItemId': 'developer-proof',
            'role': 'developer',
            'branch': 'feature/agentrunner/operator-tui',
            'startedAt': '2026-04-20T00:40:00Z',
            'ageSeconds': 300,
            'runId': 'run-proof',
            'sessionKey': 'session-proof',
            'resultPath': '/tmp/developer-proof.json',
        },
        'queue': {
            'depth': 2,
            'nextIds': ['reviewer-proof', 'manager-wrap'],
            'preview': [
                {
                    'queueItemId': 'reviewer-proof',
                    'role': 'reviewer',
                    'branch': 'feature/agentrunner/operator-tui',
                    'goal': 'Review the TUI proof and docs.',
                },
                {
                    'queueItemId': 'manager-wrap',
                    'role': 'manager',
                    'branch': 'feature/agentrunner/operator-tui',
                    'goal': 'Close the initiative loop.',
                },
            ],
        },
        'initiative': {
            'initiativeId': 'agentrunner-operator-tui',
            'phase': 'implementation',
            'currentSubtaskId': 'operator-tui-proof-and-docs',
            'branch': 'feature/agentrunner/operator-tui',
            'base': 'main',
            'statePath': '/tmp/initiative-state.json',
        },
        'lastCompleted': {
            'queueItemId': 'architect-plan',
            'role': 'architect',
            'status': 'ok',
            'summary': 'Documented the read-only operator adapter stack.',
            'endedAt': '2026-04-20T00:35:00Z',
        },
        'warnings': warnings if warnings is not None else [
            {
                'code': 'stale_run',
                'severity': 'warning',
                'summary': 'Current run is older than the stale threshold.',
                'details': 'Operators should refresh or inspect recent mechanics runs.',
            }
        ],
        'reconciliation': {
            'decision': status,
            'summary': 'A blocking warning is still visible to operators.',
            'reasons': [
                {
                    'code': 'stale_run',
                    'severity': 'warning',
                    'summary': 'Current run is older than the stale threshold.',
                    'source': 'live_runtime',
                    'precedence': 2,
                }
            ],
        },
        'resultHint': 'The TUI should stay a read-only adapter over canonical operator data.',
        'runtime': {
            'extraDevTurnsUsed': 1,
            'lastBranch': 'feature/agentrunner/operator-tui',
        },
    }


def run_tui(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['python3', '-m', 'agentrunner.scripts.operator_tui', *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_router(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['python3', '-m', 'agentrunner', *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_in(text: str, needle: str) -> None:
    assert needle in text, f'missing {needle!r} in output:\n{text}'


def test_once_snapshot_render_includes_operator_sections(snapshot_file: Path) -> None:
    write_json(snapshot_file, sample_artifact())

    result = run_tui('--once', '--snapshot-file', str(snapshot_file))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert_in(result.stdout, 'AgentRunner operator TUI · project=demo')
    assert_in(result.stdout, 'mode: local read-only operator surface over the canonical snapshot')
    assert_in(result.stdout, 'status: BLOCKED')
    assert_in(result.stdout, 'Project status:')
    assert_in(result.stdout, 'Current item:')
    assert_in(result.stdout, 'Queue preview:')
    assert_in(result.stdout, 'Initiative context:')
    assert_in(result.stdout, 'Warnings:')
    assert_in(result.stdout, 'Result hints:')
    assert_in(result.stdout, 'Snapshot notes:')
    assert_in(result.stdout, '- [warning] stale_run')
    assert_in(result.stdout, '- hint: The TUI should stay a read-only adapter over canonical operator data.')
    assert_in(result.stdout, 'controls: tab/←/→/↑/↓ move · pgup/pgdn scroll · r refresh · q quit · readonly surface')


def test_once_snapshot_render_handles_empty_warning_and_missing_result_hint(snapshot_file: Path) -> None:
    artifact = sample_artifact(status='idle-clean', warnings=[])
    artifact['current'] = None
    artifact['lastCompleted'] = None
    artifact['resultHint'] = None
    artifact['runtime'] = None
    write_json(snapshot_file, artifact)

    result = run_tui('--once', '--snapshot-file', str(snapshot_file))

    assert result.returncode == 0, result.stderr
    assert_in(result.stdout, 'status: IDLE-CLEAN')
    assert_in(result.stdout, '- No warnings.')
    assert_in(result.stdout, '- hint: No result hint available.')
    assert_in(result.stdout, '- queue item: -')
    assert_in(result.stdout, '- last item: -')


def test_snapshot_file_mode_reports_malformed_fixture_clearly(snapshot_file: Path) -> None:
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text('{not json}\n', encoding='utf-8')

    result = run_tui('--once', '--snapshot-file', str(snapshot_file))

    assert result.returncode == 2
    assert_in(result.stderr, 'snapshot fixture is malformed:')


def test_tui_launch_wiring_works_via_top_level_router(snapshot_file: Path) -> None:
    write_json(snapshot_file, sample_artifact(status='active'))

    result = run_router('tui', '--once', '--snapshot-file', str(snapshot_file))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert_in(result.stdout, 'AgentRunner operator TUI · project=demo')
    assert_in(result.stdout, 'status: ACTIVE')


def disposable_snapshot_file(root: Path, name: str) -> Path:
    return root / name / 'operator_status.json'


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='operator-tui-') as tmp:
        root = Path(tmp)
        test_once_snapshot_render_includes_operator_sections(disposable_snapshot_file(root, 'render'))
        test_once_snapshot_render_handles_empty_warning_and_missing_result_hint(disposable_snapshot_file(root, 'empty-states'))
        test_snapshot_file_mode_reports_malformed_fixture_clearly(disposable_snapshot_file(root, 'malformed'))
        test_tui_launch_wiring_works_via_top_level_router(disposable_snapshot_file(root, 'router'))
    print('ok: operator TUI proof covers fixture-driven render formatting, empty/error states, and top-level launch wiring')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
