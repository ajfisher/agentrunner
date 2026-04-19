#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agentrunner/scripts'))

from operator_data import (  # noqa: E402
    OPERATOR_SNAPSHOT_CONTRACT,
    build_status_artifact,
    load_operator_snapshot,
    operator_snapshot_path,
    snapshot_contract,
    snapshot_current,
    snapshot_initiative,
    snapshot_last_completed,
    snapshot_project,
    snapshot_queue,
    snapshot_queue_preview,
    snapshot_reconciliation,
    snapshot_result_hint,
    snapshot_runtime,
    snapshot_status,
    snapshot_updated_at,
    snapshot_warnings,
    resolve_operator_snapshot,
    write_status_artifact,
)


FIXED_NOW = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def fixed_now_builder(state_dir: Path, *, queue_preview: int, tick_count: int):
    return build_status_artifact(state_dir, queue_preview=queue_preview, tick_count=tick_count, now=FIXED_NOW)


def seed_runtime_truth(state_dir: Path) -> None:
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': True,
        'updatedAt': '2026-04-19T11:59:30+00:00',
        'current': {
            'queueItemId': 'developer-proof',
            'role': 'developer',
            'runId': 'run-proof',
            'sessionKey': 'sess-proof',
            'resultPath': str(state_dir / 'results' / 'developer-proof.json'),
            'startedAt': '2026-04-19T11:58:00+00:00',
            'queueItem': {
                'id': 'developer-proof',
                'project': 'agentrunner',
                'role': 'developer',
                'branch': 'feature/agentrunner/operator-data-layer',
                'base': 'master',
                'goal': 'Prove the operator data layer contract.',
                'initiative': {
                    'initiativeId': 'agentrunner-operator-data-layer',
                    'phase': 'implementation',
                    'subtaskId': 'operator-data-layer-proof-and-docs',
                    'branch': 'feature/agentrunner/operator-data-layer',
                    'base': 'master',
                },
            },
        },
        'runtime': {
            'extraDevTurnsUsed': 1,
            'lastBranch': 'feature/agentrunner/operator-data-layer',
        },
        'initiative': {
            'initiativeId': 'agentrunner-operator-data-layer',
            'phase': 'implementation',
            'currentSubtaskId': 'operator-data-layer-proof-and-docs',
            'branch': 'feature/agentrunner/operator-data-layer',
            'base': 'master',
        },
    })
    write_json(state_dir / 'queue.json', [
        {
            'id': 'reviewer-proof',
            'project': 'agentrunner',
            'role': 'reviewer',
            'branch': 'feature/agentrunner/operator-data-layer',
            'goal': 'Review the shared operator data layer docs and proof coverage.',
        }
    ])
    write_text(
        state_dir / 'ticks.ndjson',
        json.dumps({
            'queueItemId': 'architect-plan',
            'role': 'architect',
            'status': 'ok',
            'ts': '2026-04-19T11:40:00+00:00',
            'result': {
                'summary': 'Locked the operator data layer plan.',
            },
        }) + '\n',
    )


def test_load_operator_snapshot_prefers_canonical_artifact_without_rebuild(state_dir: Path) -> None:
    artifact = {
        'contract': dict(OPERATOR_SNAPSHOT_CONTRACT),
        'project': 'agentrunner',
        'status': 'idle-pending',
        'current': None,
        'queue': {
            'depth': 1,
            'nextIds': ['reviewer-proof'],
            'preview': [
                {
                    'queueItemId': 'reviewer-proof',
                    'role': 'reviewer',
                    'branch': 'feature/agentrunner/operator-data-layer',
                    'goal': 'Review the shared operator data layer docs and proof coverage.',
                }
            ],
        },
        'initiative': {
            'initiativeId': 'agentrunner-operator-data-layer',
            'phase': 'implementation',
            'currentSubtaskId': 'operator-data-layer-proof-and-docs',
        },
        'lastCompleted': {
            'queueItemId': 'architect-plan',
            'role': 'architect',
            'status': 'ok',
            'summary': 'Locked the operator data layer plan.',
            'endedAt': '2026-04-19T11:40:00+00:00',
        },
        'warnings': [],
        'reconciliation': {
            'decision': 'idle-pending',
            'summary': 'queued work remains',
            'reasons': [],
        },
        'updatedAt': '2026-04-19T12:00:00+00:00',
        'resultHint': 'Locked the operator data layer plan.',
    }
    write_json(operator_snapshot_path(state_dir), artifact)

    loaded, notes = load_operator_snapshot(
        state_dir,
        queue_preview=3,
        tick_count=3,
        rebuild_missing=False,
        rebuild_malformed=False,
        write_rebuild=False,
    )

    assert loaded == artifact
    assert notes == []


def test_load_operator_snapshot_rebuilds_missing_only_when_explicit(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)

    without_rebuild, without_notes = load_operator_snapshot(
        state_dir,
        queue_preview=2,
        tick_count=3,
        rebuild_missing=False,
        rebuild_malformed=False,
        write_rebuild=False,
    )
    assert without_rebuild is None
    assert any('operator status artifact missing' in note for note in without_notes)
    assert any('--rebuild-missing' in note for note in without_notes)
    assert not operator_snapshot_path(state_dir).exists()

    rebuilt, rebuilt_notes = load_operator_snapshot(
        state_dir,
        queue_preview=2,
        tick_count=3,
        rebuild_missing=True,
        rebuild_malformed=False,
        write_rebuild=True,
        build_status_artifact=fixed_now_builder,
    )

    assert rebuilt is not None
    assert rebuilt['project'] == 'agentrunner'
    assert rebuilt['status'] == 'active'
    assert rebuilt['current']['queueItemId'] == 'developer-proof'
    assert rebuilt['queue']['nextIds'] == ['reviewer-proof']
    assert rebuilt['initiative']['initiativeId'] == 'agentrunner-operator-data-layer'
    assert rebuilt['lastCompleted']['queueItemId'] == 'architect-plan'
    assert rebuilt['updatedAt']
    assert any('rebuilt operator status from mechanics files because --rebuild-missing was set' in note for note in rebuilt_notes)
    assert any('wrote' in note for note in rebuilt_notes)
    assert operator_snapshot_path(state_dir).exists()


def test_load_operator_snapshot_rebuilds_malformed_artifact_with_bounded_fallback(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    write_text(operator_snapshot_path(state_dir), '{not json}\n')

    rebuilt, notes = load_operator_snapshot(
        state_dir,
        queue_preview=2,
        tick_count=3,
        rebuild_missing=False,
        rebuild_malformed=True,
        write_rebuild=False,
        build_status_artifact=fixed_now_builder,
    )

    assert rebuilt is not None
    assert rebuilt['status'] == 'active'
    assert rebuilt['queue']['depth'] == 1
    assert any('operator_status.json is malformed' in note for note in notes)
    assert any('--rebuild-malformed was set' in note for note in notes)


def test_snapshot_accessors_cover_minimum_adapter_fields(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)
    write_status_artifact(state_dir, artifact)

    loaded, notes = load_operator_snapshot(
        state_dir,
        queue_preview=2,
        tick_count=3,
        rebuild_missing=False,
        rebuild_malformed=False,
        write_rebuild=False,
    )

    assert loaded is not None
    assert notes == []
    assert snapshot_contract(loaded) == OPERATOR_SNAPSHOT_CONTRACT
    assert snapshot_project(loaded) == 'agentrunner'
    assert snapshot_status(loaded) == 'active'

    current = snapshot_current(loaded)
    assert current is not None
    assert current['queueItemId'] == 'developer-proof'
    assert current['role'] == 'developer'
    assert current['branch'] == 'feature/agentrunner/operator-data-layer'
    assert isinstance(current['ageSeconds'], int)

    queue = snapshot_queue(loaded)
    assert queue['depth'] == 1
    assert queue['nextIds'] == ['reviewer-proof']
    preview = snapshot_queue_preview(loaded, queue_preview=1)
    assert preview == [
        {
            'queueItemId': 'reviewer-proof',
            'role': 'reviewer',
            'branch': 'feature/agentrunner/operator-data-layer',
            'goal': 'Review the shared operator data layer docs and proof coverage.',
        }
    ]

    initiative = snapshot_initiative(loaded)
    assert initiative is not None
    assert initiative['initiativeId'] == 'agentrunner-operator-data-layer'
    assert initiative['phase'] == 'implementation'
    assert initiative['currentSubtaskId'] == 'operator-data-layer-proof-and-docs'

    last_completed = snapshot_last_completed(loaded)
    assert last_completed is not None
    assert last_completed['queueItemId'] == 'architect-plan'
    assert last_completed['role'] == 'architect'
    assert last_completed['status'] == 'ok'

    warnings = snapshot_warnings(loaded)
    assert warnings == []
    reconciliation = snapshot_reconciliation(loaded)
    assert reconciliation is not None
    assert reconciliation['decision'] == 'active'
    assert snapshot_result_hint(loaded) == 'Locked the operator data layer plan.'
    assert snapshot_runtime(loaded) == {
        'extraDevTurnsUsed': 1,
        'lastBranch': 'feature/agentrunner/operator-data-layer',
    }
    assert snapshot_updated_at(loaded) == artifact['updatedAt']


def test_resolve_operator_snapshot_returns_structured_read_model_from_project(state_dir: Path, monkeypatch) -> None:
    seed_runtime_truth(state_dir)
    monkeypatch.setattr('operator_data.DEFAULT_PROJECTS_ROOT', state_dir.parent)

    snapshot = resolve_operator_snapshot(
        project=state_dir.name,
        queue_preview=2,
        tick_count=3,
        rebuild_missing=True,
        write_rebuild=False,
        build_status_artifact=fixed_now_builder,
    )

    assert snapshot.state_dir == state_dir.resolve()
    assert snapshot.artifact_path == operator_snapshot_path(state_dir.resolve())
    assert snapshot.artifact is not None
    assert snapshot.artifact['project'] == 'agentrunner'
    assert snapshot.notes == (
        'warning: operator status artifact missing at ' + str(operator_snapshot_path(state_dir.resolve())),
        'info: rebuilt operator status from mechanics files because --rebuild-missing was set',
    )


def test_resolve_operator_snapshot_accepts_path_input_without_cli_formatting(state_dir: Path) -> None:
    artifact = {
        'contract': dict(OPERATOR_SNAPSHOT_CONTRACT),
        'project': 'agentrunner',
        'status': 'idle',
        'current': None,
        'queue': {'depth': 0, 'nextIds': [], 'preview': []},
        'initiative': None,
        'lastCompleted': None,
        'warnings': [],
        'reconciliation': {'decision': 'idle', 'summary': 'nothing running', 'reasons': []},
        'updatedAt': '2026-04-19T12:00:00+00:00',
        'resultHint': None,
    }
    write_json(operator_snapshot_path(state_dir), artifact)

    snapshot = resolve_operator_snapshot(state_dir=state_dir)

    assert snapshot.state_dir == state_dir.resolve()
    assert snapshot.artifact_path == operator_snapshot_path(state_dir.resolve())
    assert snapshot.artifact == artifact
    assert snapshot.notes == ()
