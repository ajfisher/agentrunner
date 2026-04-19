#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agentrunner/scripts'))

from operator_data import build_status_artifact, write_status_artifact  # noqa: E402
from operator_mqtt import (  # noqa: E402
    MQTT_SNAPSHOT_CONTRACT,
    build_publish_payload,
    maybe_publish_operator_snapshot,
    publish_state_path,
    publish_topic,
    resolve_operator_snapshot,
    snapshot_subset,
)

FIXED_NOW = datetime(2026, 4, 20, 0, 5, 0, tzinfo=timezone.utc)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def seed_runtime_truth(state_dir: Path) -> None:
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': True,
        'updatedAt': '2026-04-20T00:04:40+00:00',
        'current': {
            'queueItemId': 'developer-mqtt',
            'role': 'developer',
            'runId': 'run-mqtt',
            'sessionKey': 'sess-mqtt',
            'resultPath': str(state_dir / 'results' / 'developer-mqtt.json'),
            'startedAt': '2026-04-20T00:00:00+00:00',
            'queueItem': {
                'id': 'developer-mqtt',
                'project': 'agentrunner',
                'role': 'developer',
                'branch': 'feature/agentrunner/operator-mqtt-broadcast',
                'base': 'master',
                'goal': 'Publish canonical operator snapshot updates.',
                'initiative': {
                    'initiativeId': 'agentrunner-operator-mqtt-broadcast',
                    'phase': 'implementation',
                    'subtaskId': 'operator-mqtt-publisher-seam',
                    'branch': 'feature/agentrunner/operator-mqtt-broadcast',
                    'base': 'master',
                },
            },
        },
        'runtime': {
            'extraDevTurnsUsed': 0,
            'lastBranch': 'feature/agentrunner/operator-mqtt-broadcast',
        },
        'initiative': {
            'initiativeId': 'agentrunner-operator-mqtt-broadcast',
            'phase': 'implementation',
            'currentSubtaskId': 'operator-mqtt-publisher-seam',
            'branch': 'feature/agentrunner/operator-mqtt-broadcast',
            'base': 'master',
        },
    })
    write_json(state_dir / 'queue.json', [
        {
            'id': 'reviewer-mqtt',
            'project': 'agentrunner',
            'role': 'reviewer',
            'branch': 'feature/agentrunner/operator-mqtt-broadcast',
            'goal': 'Review the operator MQTT seam.',
        }
    ])
    write_text(
        state_dir / 'ticks.ndjson',
        json.dumps({
            'queueItemId': 'architect-mqtt',
            'role': 'architect',
            'status': 'ok',
            'ts': '2026-04-19T23:55:00+00:00',
            'result': {
                'summary': 'Locked the operator MQTT broadcast plan.',
            },
        }) + '\n',
    )


def test_build_publish_payload_uses_canonical_snapshot_accessors(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)
    write_status_artifact(state_dir, artifact)

    snapshot_read = resolve_operator_snapshot(state_dir=state_dir)
    payload = build_publish_payload(snapshot_read)

    assert payload is not None
    assert payload['contract'] == MQTT_SNAPSHOT_CONTRACT
    assert payload['project'] == 'agentrunner'
    assert payload['source']['kind'] == 'operator_status.json'
    assert payload['source']['path'] == str(state_dir / 'operator_status.json')
    assert payload['snapshot'] == snapshot_subset(snapshot_read.artifact)
    assert payload['snapshot']['status'] == 'active'
    assert payload['snapshot']['current']['queueItemId'] == 'developer-mqtt'
    assert payload['snapshot']['queue']['nextIds'] == ['reviewer-mqtt']
    assert payload['snapshot']['initiative']['initiativeId'] == 'agentrunner-operator-mqtt-broadcast'
    assert payload['snapshot']['lastCompleted']['queueItemId'] == 'architect-mqtt'
    assert payload['snapshot']['reconciliation']['decision'] == 'active'
    assert payload['snapshot']['updatedAt'] == artifact['updatedAt']


def test_maybe_publish_operator_snapshot_is_safe_noop_when_disabled(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)
    write_status_artifact(state_dir, artifact)

    attempts: list[dict] = []
    result = maybe_publish_operator_snapshot(
        state_dir=state_dir,
        config={'enabled': False},
        publish_fn=attempts.append,
    )

    assert result.enabled is False
    assert result.attempted is False
    assert result.published is False
    assert attempts == []
    assert not publish_state_path(state_dir).exists()
    assert 'disabled' in result.note


def test_maybe_publish_operator_snapshot_publishes_once_then_quiets_until_changed(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)
    write_status_artifact(state_dir, artifact)

    attempts: list[dict] = []
    config = {
        'enabled': True,
        'broker': {'host': 'mqtt.example.internal', 'port': 1883},
        'topicPrefix': 'agentrunner/operator',
        'qos': 1,
        'retain': True,
    }

    first = maybe_publish_operator_snapshot(state_dir=state_dir, config=config, publish_fn=attempts.append)
    assert first.published is True
    assert first.topic == publish_topic(topic_prefix='agentrunner/operator', project='agentrunner')
    assert len(attempts) == 1
    assert attempts[0]['payload']['snapshot']['queue']['depth'] == 1
    assert attempts[0]['payload']['snapshot'] == snapshot_subset(json.loads((state_dir / 'operator_status.json').read_text()))
    assert publish_state_path(state_dir).exists()

    second = maybe_publish_operator_snapshot(state_dir=state_dir, config=config, publish_fn=attempts.append)
    assert second.published is False
    assert second.changed is False
    assert len(attempts) == 1
    assert 'unchanged' in second.note

    artifact['queue']['depth'] = 2
    artifact['queue']['nextIds'] = ['reviewer-mqtt', 'manager-mqtt']
    write_status_artifact(state_dir, artifact)
    third = maybe_publish_operator_snapshot(state_dir=state_dir, config=config, publish_fn=attempts.append)
    assert third.published is True
    assert third.changed is True
    assert len(attempts) == 2
    assert attempts[-1]['payload']['snapshot']['queue']['depth'] == 2


def test_maybe_publish_operator_snapshot_uses_stub_publisher_instead_of_real_broker(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)
    write_status_artifact(state_dir, artifact)

    attempts: list[dict] = []

    def stub_publish(request: dict) -> None:
        attempts.append(request)

    result = maybe_publish_operator_snapshot(
        state_dir=state_dir,
        config={
            'enabled': True,
            'broker': {'host': 'definitely-not-a-real-broker.invalid', 'port': 65535},
            'topicPrefix': 'agentrunner/operator',
            'qos': 1,
            'retain': True,
        },
        publish_fn=stub_publish,
    )

    assert result.published is True
    assert len(attempts) == 1
    assert attempts[0]['topic'] == 'agentrunner/operator/agentrunner/snapshot'
    assert attempts[0]['broker']['host'] == 'definitely-not-a-real-broker.invalid'
    assert attempts[0]['payload']['contract'] == MQTT_SNAPSHOT_CONTRACT
    assert attempts[0]['payload']['snapshot']['status'] == 'active'
    assert 'definitely-not-a-real-broker.invalid' not in attempts[0]['payloadText']


def test_maybe_publish_operator_snapshot_degrades_publish_failures_to_notes(state_dir: Path) -> None:
    seed_runtime_truth(state_dir)
    artifact = build_status_artifact(state_dir, queue_preview=2, tick_count=3, now=FIXED_NOW)
    write_status_artifact(state_dir, artifact)

    def boom(_request: dict) -> None:
        raise RuntimeError('broker unavailable for test')

    result = maybe_publish_operator_snapshot(
        state_dir=state_dir,
        config={
            'enabled': True,
            'broker': {'host': 'mqtt.example.internal', 'port': 1883},
        },
        publish_fn=boom,
    )

    assert result.enabled is True
    assert result.attempted is True
    assert result.changed is True
    assert result.published is False
    assert 'publish failed' in result.note
    assert 'broker unavailable for test' in result.note
    assert not publish_state_path(state_dir).exists()


def disposable_state_dir() -> Path:
    state_dir = Path(tempfile.mkdtemp(prefix='operator-mqtt-state-')) / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def main() -> int:
    test_build_publish_payload_uses_canonical_snapshot_accessors(disposable_state_dir())
    test_maybe_publish_operator_snapshot_is_safe_noop_when_disabled(disposable_state_dir())
    test_maybe_publish_operator_snapshot_publishes_once_then_quiets_until_changed(disposable_state_dir())
    test_maybe_publish_operator_snapshot_uses_stub_publisher_instead_of_real_broker(disposable_state_dir())
    test_maybe_publish_operator_snapshot_degrades_publish_failures_to_notes(disposable_state_dir())
    print('ok: operator MQTT proof checks executed via direct runner, including canonical snapshot accessors, stub-publisher hermetic coverage, and disabled/failure degrade paths')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
