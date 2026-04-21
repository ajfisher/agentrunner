#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agentrunner/scripts'))

from status_artifact import STALE_RUN_AFTER, build_status_artifact  # noqa: E402


FIXED_NOW = datetime(2026, 4, 18, 23, 0, 0, tzinfo=timezone.utc)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def warning_codes(artifact: dict) -> set[str]:
    return {
        str(item.get('code'))
        for item in artifact.get('warnings', [])
        if isinstance(item, dict) and item.get('code')
    }


def make_queue_item(item_id: str, *, role: str, branch: str, goal: str, initiative: dict | None = None) -> dict:
    item = {
        'id': item_id,
        'project': 'agentrunner',
        'role': role,
        'branch': branch,
        'goal': goal,
    }
    if initiative is not None:
        item['initiative'] = initiative
    return item


def init_status_repo(repo: Path, *, branch: str) -> None:
    import subprocess

    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-b', branch], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'config', 'user.name', 'AgentRunner Tests'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'tests@example.invalid'], cwd=repo, check=True)
    (repo / 'README.md').write_text('ok\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-m', 'initial'], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'branch', 'master'], cwd=repo, check=True, capture_output=True, text=True)


def test_active_queue_and_initiative_summary(state_dir: Path) -> None:
    initiative_state = state_dir / 'initiatives' / 'operator-status-artifact' / 'state.json'
    write_json(initiative_state, {
        'initiativeId': 'operator-status-artifact',
        'phase': 'implementation',
        'currentSubtaskId': 'status-proof-tests',
        'branch': 'feature/agentrunner/operator-status-artifact',
        'base': 'master',
    })

    active_item = make_queue_item(
        'manager-active',
        role='manager',
        branch='feature/agentrunner/operator-status-artifact',
        goal='Coordinate status artifact work.',
        initiative={
            'initiativeId': 'operator-status-artifact',
            'phase': 'design-manager',
            'subtaskId': 'kickoff',
            'statePath': str(initiative_state),
            'branch': 'feature/agentrunner/operator-status-artifact',
            'base': 'master',
        },
    )
    next_item = make_queue_item(
        'developer-next',
        role='developer',
        branch='feature/agentrunner/operator-status-artifact',
        goal='Add focused proof fixtures for the canonical operator artifact.',
        initiative={
            'initiativeId': 'operator-status-artifact',
            'phase': 'implementation',
            'subtaskId': 'status-proof-tests',
        },
    )
    later_item = make_queue_item(
        'reviewer-later',
        role='reviewer',
        branch='feature/agentrunner/operator-status-artifact',
        goal='Review the proof coverage for operator_status.json.',
    )

    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': True,
        'updatedAt': (FIXED_NOW - timedelta(minutes=2)).isoformat(),
        'current': {
            'queueItemId': 'manager-active',
            'role': 'manager',
            'runId': 'run-active',
            'sessionKey': 'sess-active',
            'resultPath': str(state_dir / 'results' / 'manager-active.json'),
            'startedAt': (FIXED_NOW - timedelta(minutes=4)).isoformat(),
            'queueItem': active_item,
        },
        'initiative': {
            'initiativeId': 'operator-status-artifact',
            'phase': 'design-manager',
            'statePath': str(initiative_state),
        },
    })
    write_json(state_dir / 'queue.json', [next_item, later_item])
    write_text(
        state_dir / 'ticks.ndjson',
        json.dumps({
            'queueItemId': 'architect-plan',
            'role': 'architect',
            'status': 'ok',
            'ts': (FIXED_NOW - timedelta(hours=1)).isoformat(),
            'result': {
                'summary': 'Architect plan locked.',
                'checks': [{'name': 'plan-json', 'status': 'ok'}],
            },
        }) + '\n',
    )

    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)

    assert artifact['status'] == 'active', artifact
    assert artifact['current']['queueItemId'] == 'manager-active', artifact
    assert artifact['current']['branch'] == 'feature/agentrunner/operator-status-artifact', artifact
    assert artifact['current']['ageSeconds'] == 240, artifact
    assert artifact['queue']['depth'] == 2, artifact
    assert artifact['queue']['nextIds'] == ['developer-next', 'reviewer-later'], artifact
    assert artifact['queue']['preview'][0]['goal'].startswith('Add focused proof fixtures'), artifact
    assert artifact['initiative'] == {
        'initiativeId': 'operator-status-artifact',
        'phase': 'implementation',
        'currentSubtaskId': 'status-proof-tests',
        'branch': 'feature/agentrunner/operator-status-artifact',
        'base': 'master',
        'statePath': str(initiative_state),
        'statusMessage': None,
        'closureRemediation': None,
    }, artifact
    assert artifact['closure']['state'] == 'execution-active', artifact
    assert artifact['closure']['handoffSafe'] is False, artifact
    assert artifact['closure']['quiet'] is False, artifact
    assert artifact['lastCompleted']['queueItemId'] == 'architect-plan', artifact
    assert artifact['lastCompleted']['summary'] == 'Architect plan locked.', artifact
    assert artifact['resultHint'] == 'Architect plan locked.', artifact
    assert warning_codes(artifact) == set(), artifact
    live_repo = next((src for src in artifact['reconciliation']['sources'] if src.get('name') == 'live_repo'), None)
    assert live_repo is not None, artifact
    assert live_repo['present'] is False, artifact


def test_missing_and_malformed_optional_files_warn_not_crash(state_dir: Path) -> None:
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': False,
        'updatedAt': (FIXED_NOW - (STALE_RUN_AFTER + timedelta(minutes=5))).isoformat(),
        'current': None,
        'lastCompleted': {
            'queueItemId': 'dev-last',
            'role': 'developer',
            'status': 'ok',
            'endedAt': (FIXED_NOW - timedelta(hours=2)).isoformat(),
        },
        'initiative': {
            'initiativeId': 'missing-initiative-state',
            'phase': 'implementation',
            'statePath': str(state_dir / 'initiatives' / 'missing-initiative-state' / 'state.json'),
        },
    })
    write_text(state_dir / 'ticks.ndjson', '{not json}\n')
    write_text(state_dir / 'results' / 'dev-last.json', '{also not json}\n')

    artifact = build_status_artifact(state_dir, queue_preview=3, tick_count=3, now=FIXED_NOW)

    codes = warning_codes(artifact)
    assert artifact['status'] == 'idle-clean', artifact
    assert artifact['queue']['depth'] == 0, artifact
    assert artifact['lastCompleted']['queueItemId'] == 'dev-last', artifact
    assert artifact['resultHint'] is None, artifact
    assert 'missing_queue' in codes, artifact
    assert 'malformed_ticks' in codes, artifact
    assert 'malformed_result' in codes, artifact
    assert artifact['initiative']['initiativeId'] == 'missing-initiative-state', artifact
    assert artifact['initiative']['phase'] == 'implementation', artifact
    assert artifact['closure']['state'] == 'execution-active', artifact
    assert artifact['closure']['handoffSafe'] is False, artifact
    assert artifact['closure']['quiet'] is True, artifact


def test_closure_active_requires_more_than_merely_being_quiet(state_dir: Path) -> None:
    initiative_state = state_dir / 'initiatives' / 'closure-semantics' / 'state.json'
    write_json(initiative_state, {
        'initiativeId': 'closure-semantics',
        'phase': 'review-manager',
        'branch': 'feature/agentrunner/closure-handoff-state-semantics',
        'base': 'master',
    })
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': False,
        'updatedAt': (FIXED_NOW - timedelta(minutes=1)).isoformat(),
        'current': None,
        'initiative': {
            'initiativeId': 'closure-semantics',
            'phase': 'review-manager',
            'statePath': str(initiative_state),
        },
    })
    write_json(state_dir / 'queue.json', [])

    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)

    assert artifact['status'] == 'idle-clean', artifact
    assert artifact['closure']['state'] == 'closure-active', artifact
    assert artifact['closure']['quiet'] is True, artifact
    assert artifact['closure']['handoffSafe'] is False, artifact
    assert artifact['closure']['initiativePhase'] == 'review-manager', artifact
    assert artifact['closure']['reason'] == 'initiative is in a closure-phase or closure remediation/passback follow-up', artifact


def test_closure_active_reason_covers_proof_hardening_even_when_runtime_is_idle_clean(state_dir: Path) -> None:
    initiative_state = state_dir / 'initiatives' / 'closure-proof-hardening' / 'state.json'
    write_json(initiative_state, {
        'initiativeId': 'closure-proof-hardening',
        'phase': 'implementation',
        'branch': 'feature/agentrunner/closure-handoff-state-semantics',
        'base': 'master',
        'remediation': {
            'activeAttempt': {
                'attempt': 2,
                'reason': 'Proof hardening is still required before closure review can safely resume.',
            },
        },
    })
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': False,
        'updatedAt': (FIXED_NOW - timedelta(minutes=1)).isoformat(),
        'current': None,
        'initiative': {
            'initiativeId': 'closure-proof-hardening',
            'phase': 'implementation',
            'statePath': str(initiative_state),
        },
    })
    write_json(state_dir / 'queue.json', [])

    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)

    assert artifact['status'] == 'idle-clean', artifact
    assert artifact['closure']['state'] == 'closure-active', artifact
    assert artifact['closure']['quiet'] is True, artifact
    assert artifact['closure']['handoffSafe'] is False, artifact
    assert artifact['closure']['initiativePhase'] == 'implementation', artifact
    assert artifact['closure']['reason'] == 'initiative is in a closure-phase or closure remediation/passback follow-up', artifact


def test_stale_and_partial_runtime_cases(state_dir: Path) -> None:
    stale_item = make_queue_item(
        'developer-stale',
        role='developer',
        branch='feature/agentrunner/operator-status-artifact',
        goal='Status artifact run went stale.',
    )
    queued_after = make_queue_item(
        'reviewer-after-stale',
        role='reviewer',
        branch='feature/agentrunner/operator-status-artifact',
        goal='Review after stale developer turn.',
    )
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': True,
        'updatedAt': (FIXED_NOW - timedelta(minutes=1)).isoformat(),
        'current': {
            'queueItemId': 'developer-stale',
            'role': 'developer',
            'runId': 'run-stale',
            'sessionKey': 'sess-stale',
            'resultPath': str(state_dir / 'results' / 'developer-stale.json'),
            'startedAt': (FIXED_NOW - (STALE_RUN_AFTER + timedelta(minutes=1))).isoformat(),
            'queueItem': stale_item,
        },
        'runtime': {
            'extraDevTurnsUsed': 1,
            'lastBranch': 'feature/agentrunner/operator-status-artifact',
        },
    })
    write_json(state_dir / 'queue.json', [queued_after])
    write_text(
        state_dir / 'ticks.ndjson',
        '\n'.join([
            json.dumps({
                'queueItemId': 'dev-ok',
                'role': 'developer',
                'status': 'ok',
                'ts': (FIXED_NOW - timedelta(hours=3)).isoformat(),
                'result': {'summary': 'Earlier dev work shipped cleanly.'},
            }),
            json.dumps({
                'queueItemId': 'review-blocked',
                'role': 'reviewer',
                'status': 'blocked',
                'ts': (FIXED_NOW - timedelta(minutes=20)).isoformat(),
                'result': {
                    'operatorSummary': '\n'.join([
                        'Reviewer ›',
                        '- Status: blocked',
                        '- Top finding: Missing stale-run proof coverage',
                    ]),
                },
            }),
        ]) + '\n',
    )

    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=5, now=FIXED_NOW)

    codes = warning_codes(artifact)
    assert artifact['status'] == 'blocked', artifact
    assert artifact['current']['ageSeconds'] == int((STALE_RUN_AFTER + timedelta(minutes=1)).total_seconds()), artifact
    assert artifact['queue']['nextIds'] == ['reviewer-after-stale'], artifact
    assert artifact['lastCompleted']['queueItemId'] == 'review-blocked', artifact
    assert artifact['lastCompleted']['status'] == 'blocked', artifact
    assert artifact['lastCompleted']['summary'] == 'Top finding: Missing stale-run proof coverage', artifact
    assert artifact['resultHint'] == 'Top finding: Missing stale-run proof coverage', artifact
    assert 'stale_run' in codes, artifact
    assert 'last_completed_blocked' not in codes, artifact
    assert artifact['runtime'] == {
        'extraDevTurnsUsed': 1,
        'lastBranch': 'feature/agentrunner/operator-status-artifact',
    }, artifact
    assert artifact['closure']['state'] == 'blocked', artifact
    assert artifact['closure']['handoffSafe'] is False, artifact


def test_live_repo_can_outrank_stale_blocked_result_when_runtime_is_otherwise_clean(state_dir: Path) -> None:
    repo = state_dir / 'repo'
    init_status_repo(repo, branch='feature/agentrunner/operator-status-artifact')

    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': False,
        'updatedAt': (FIXED_NOW - timedelta(minutes=1)).isoformat(),
        'current': None,
        'lastCompleted': {
            'queueItemId': 'review-blocked',
            'role': 'reviewer',
            'status': 'blocked',
            'endedAt': (FIXED_NOW - timedelta(hours=2)).isoformat(),
            'queueItem': {
                'repo_path': str(repo),
                'branch': 'feature/agentrunner/operator-status-artifact',
                'base': 'master',
            },
        },
    })
    write_json(state_dir / 'queue.json', [])

    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)

    assert artifact['status'] == 'idle-clean', artifact
    assert artifact['closure']['state'] == 'idle-clean', artifact
    assert artifact['closure']['handoffSafe'] is True, artifact
    live_repo = next((src for src in artifact['reconciliation']['sources'] if src.get('name') == 'live_repo'), None)
    assert live_repo is not None and live_repo['present'] is True, artifact
    assert live_repo['details']['cleanWorktree'] is True, artifact
    assert artifact['reconciliation']['reasons'][0]['code'] == 'live_repo_clean_overrides_stale_blocked_artifact', artifact


def test_live_repo_on_base_can_outrank_stale_blocked_merger_tail_when_feature_is_already_merged(state_dir: Path) -> None:
    import subprocess

    repo = state_dir / 'repo-on-base'
    init_status_repo(repo, branch='feature/agentrunner/operator-status-artifact')
    subprocess.run(['git', 'checkout', 'master'], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(['git', 'merge', '--ff-only', 'feature/agentrunner/operator-status-artifact'], cwd=repo, check=True, capture_output=True, text=True)

    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': False,
        'updatedAt': (FIXED_NOW - timedelta(minutes=1)).isoformat(),
        'current': None,
        'lastCompleted': {
            'queueItemId': 'merger-blocked',
            'role': 'merger',
            'status': 'blocked',
            'endedAt': (FIXED_NOW - timedelta(hours=2)).isoformat(),
            'queueItem': {
                'repo_path': str(repo),
                'branch': 'feature/agentrunner/operator-status-artifact',
                'base': 'master',
            },
        },
    })
    write_json(state_dir / 'queue.json', [])

    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)

    assert artifact['status'] == 'idle-clean', artifact
    assert artifact['closure']['state'] == 'idle-clean', artifact
    assert artifact['closure']['handoffSafe'] is True, artifact
    live_repo = next((src for src in artifact['reconciliation']['sources'] if src.get('name') == 'live_repo'), None)
    assert live_repo is not None and live_repo['present'] is True, artifact
    assert live_repo['details']['branch'] == 'master', artifact
    assert live_repo['details']['branchIsBase'] is True, artifact
    assert live_repo['details']['expectedBranchIsAncestorOfBase'] is True, artifact
    assert artifact['reconciliation']['reasons'][0]['code'] == 'live_repo_clean_overrides_stale_blocked_artifact', artifact


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='status-artifact-') as tmp:
        root = Path(tmp)
        test_active_queue_and_initiative_summary(root / 'active')
        test_missing_and_malformed_optional_files_warn_not_crash(root / 'partial')
        test_closure_active_requires_more_than_merely_being_quiet(root / 'closure-active')
        test_closure_active_reason_covers_proof_hardening_even_when_runtime_is_idle_clean(root / 'closure-proof-hardening')
        test_stale_and_partial_runtime_cases(root / 'stale')
        test_live_repo_can_outrank_stale_blocked_result_when_runtime_is_otherwise_clean(root / 'repo-clean')
        test_live_repo_on_base_can_outrank_stale_blocked_merger_tail_when_feature_is_already_merged(root / 'repo-on-base')
    print('ok: status artifact contract is proven across active, idle, stale, partial-runtime, and live-repo fixtures')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
