#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agentrunner/scripts'))

import initiative_coordinator as coordinator  # noqa: E402
import invoker  # noqa: E402
from initiative_status import ensure_status_message_state  # noqa: E402


TARGET = {'channel': 'discord', 'target': 'channel:1477159463143084217', 'threadId': 'thread-1'}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def base_initiative_state() -> dict:
    state = {
        'initiativeId': 'agentrunner-status-message-adapters',
        'phase': 'design-manager',
        'currentSubtaskId': None,
        'completedSubtasks': [],
        'pendingSubtasks': [],
        'branch': 'feature/agentrunner/status-message-adapters',
        'base': 'master',
    }
    ensure_status_message_state(state)
    return state


def test_coordinator_lifecycle_create_then_update_reuses_single_message() -> None:
    initiative_state = base_initiative_state()
    calls: list[dict] = []

    def fake_gateway(_tool: str, args: dict) -> dict:
        calls.append(dict(args))
        if args['action'] == 'send':
            return {'ok': True, 'message': {'id': 'msg-1', 'channelId': '1477159463143084217', 'threadId': 'thread-1'}}
        return {'ok': True, 'messageId': args['messageId'], 'channelId': '1477159463143084217', 'threadId': 'thread-1'}

    original_env = os.environ.get('AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON')
    original_gateway = coordinator._gateway_message_invoke
    os.environ['AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON'] = json.dumps(TARGET)
    coordinator._gateway_message_invoke = fake_gateway
    try:
        coordinator.enqueue_architect_item(
            '/tmp/unused-state',
            project='agentrunner',
            queue_item={'repo_path': str(ROOT), 'branch': initiative_state['branch'], 'base': initiative_state['base'], 'initiative': {'initiativeId': initiative_state['initiativeId']}},
            initiative_state=initiative_state,
        )
        plan = {
            'initiativeId': initiative_state['initiativeId'],
            'subtasks': [
                {'subtaskId': 'lifecycle-wiring', 'goal': 'Wire lifecycle events', 'role': 'developer', 'checks': []},
            ],
        }
        coordinator.enqueue_first_subtask(
            '/tmp/unused-state',
            project='agentrunner',
            queue_item={'repo_path': str(ROOT), 'branch': initiative_state['branch'], 'base': initiative_state['base']},
            initiative_state=initiative_state,
            plan=plan,
        )
    finally:
        coordinator._gateway_message_invoke = original_gateway
        if original_env is None:
            os.environ.pop('AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON', None)
        else:
            os.environ['AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON'] = original_env

    assert calls[0]['action'] == 'send'
    assert calls[1]['action'] == 'edit'
    assert calls[1]['messageId'] == 'msg-1'
    status_message = initiative_state['statusMessage']
    assert status_message['handle']['id'] == 'msg-1'
    assert status_message['delivery']['lastOperation'] == 'update'
    assert status_message['lastEvent']['lifecycleEvent'] == 'subtask_started'


def test_invoker_blocked_and_terminal_updates_edit_existing_message() -> None:
    with tempfile.TemporaryDirectory(prefix='status-lifecycle-invoker-') as tmp:
        state_dir = Path(tmp)
        initiative_id = 'agentrunner-status-message-adapters'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'completedSubtasks': ['lifecycle-wiring'],
            'pendingSubtasks': [],
            'branch': 'feature/agentrunner/status-message-adapters',
            'base': 'master',
            'writtenAt': '2026-04-21T00:00:00+00:00',
            'statusMessage': {
                'target': dict(TARGET),
                'handle': {'id': 'msg-1', 'channelId': '1477159463143084217', 'threadId': 'thread-1', 'provider': 'discord'},
                'delivery': {'status': 'active', 'lastOperation': 'update', 'metadata': {}},
                'history': [],
            },
        })
        calls: list[dict] = []

        def fake_gateway(_tool: str, args: dict, *, action: str | None = None) -> dict:
            calls.append(dict(args))
            return {'ok': True, 'messageId': args['messageId'], 'channelId': '1477159463143084217', 'threadId': 'thread-1'}

        original_gateway = invoker.gateway_http_invoke
        invoker.gateway_http_invoke = fake_gateway
        try:
            blocked = invoker.emit_initiative_status_update(
                state_dir,
                queue_item={
                    'id': f'{initiative_id}-merger',
                    'role': 'merger',
                    'branch': 'feature/agentrunner/status-message-adapters',
                    'base': 'master',
                    'initiative': {'initiativeId': initiative_id},
                },
                result={
                    'status': 'blocked',
                    'role': 'merger',
                    'merged': False,
                    'summary': 'Merge blocked by ff-only policy.',
                    'mergeBlocker': {'detail': 'Branch is no longer fast-forward mergeable.'},
                },
            )
            completed = invoker.emit_initiative_status_update(
                state_dir,
                queue_item={
                    'id': f'{initiative_id}-merger',
                    'role': 'merger',
                    'branch': 'feature/agentrunner/status-message-adapters',
                    'base': 'master',
                    'initiative': {'initiativeId': initiative_id},
                },
                result={
                    'status': 'ok',
                    'role': 'merger',
                    'merged': True,
                    'commit': 'abcdef1234567890',
                    'summary': 'Merged cleanly after remediation.',
                },
            )
        finally:
            invoker.gateway_http_invoke = original_gateway

        assert blocked is True
        assert completed is True
        assert len(calls) == 2
        assert calls[0]['action'] == 'edit'
        assert calls[0]['messageId'] == 'msg-1'
        assert calls[1]['action'] == 'edit'
        assert calls[1]['messageId'] == 'msg-1'

        saved = json.loads(initiative_state_path.read_text(encoding='utf-8'))
        assert saved['statusMessage']['delivery']['status'] == 'finalized'
        assert saved['statusMessage']['delivery']['lastOperation'] == 'finalize'
        assert saved['statusMessage']['lastEvent']['lifecycleEvent'] == 'merge_completed'


def test_coordinator_merger_blocked_out_of_scope_persists_initiative_blocked() -> None:
    with tempfile.TemporaryDirectory(prefix='status-lifecycle-blocked-') as tmp:
        state_dir = Path(tmp)
        initiative_id = 'agentrunner-status-message-adapters'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        result_path = state_dir / 'results' / f'{initiative_id}-merger.json'

        write_json(state_dir / 'state.json', {
            'project': 'agentrunner',
            'running': None,
            'current': None,
            'initiative': {'initiativeId': initiative_id, 'phase': 'closure-merger', 'statePath': str(initiative_state_path)},
            'lastCompleted': {
                'queueItemId': f'{initiative_id}-merger',
                'role': 'merger',
                'resultPath': str(result_path),
                'queueItem': {
                    'id': f'{initiative_id}-merger',
                    'project': 'agentrunner',
                    'role': 'merger',
                    'repo_path': str(ROOT),
                    'branch': 'feature/agentrunner/status-message-adapters',
                    'base': 'master',
                    'initiative': {'initiativeId': initiative_id, 'phase': 'closure-merger'},
                },
            },
        })
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'completedSubtasks': ['lifecycle-wiring'],
            'pendingSubtasks': [],
            'branch': 'feature/agentrunner/status-message-adapters',
            'base': 'master',
            'writtenAt': '2026-04-21T00:00:00+00:00',
            'statusMessage': {
                'target': dict(TARGET),
                'handle': {'id': 'msg-1', 'channelId': '1477159463143084217', 'threadId': 'thread-1', 'provider': 'discord'},
                'delivery': {'status': 'active', 'lastOperation': 'update', 'metadata': {}},
                'history': [],
            },
            'remediation': {
                'attempts': [
                    {'attempt': 1, 'subtaskId': 'merger-remediation-1', 'status': 'completed'}
                ],
                'activeAttempt': 2,
                'maxAttempts': 2,
            },
        })
        write_json(result_path, {
            'status': 'blocked',
            'role': 'merger',
            'merged': False,
            'summary': 'Merge blocked by manual review requirement.',
            'mergeBlocker': {
                'classification': 'non_repairable',
                'kind': 'manual_intervention_required',
                'detail': 'Needs a human to resolve the release branch divergence.',
            },
        })

        calls: list[dict] = []

        def fake_gateway(_tool: str, args: dict) -> dict:
            calls.append(dict(args))
            return {'ok': True, 'messageId': args['messageId'], 'channelId': '1477159463143084217', 'threadId': 'thread-1'}

        original_gateway = coordinator._gateway_message_invoke
        coordinator._gateway_message_invoke = fake_gateway
        try:
            advanced = coordinator.maybe_advance(str(state_dir))
        finally:
            coordinator._gateway_message_invoke = original_gateway

        assert advanced is False
        assert len(calls) == 1
        assert calls[0]['action'] == 'edit'
        assert calls[0]['messageId'] == 'msg-1'

        saved = json.loads(initiative_state_path.read_text(encoding='utf-8'))
        assert saved['phase'] == 'closure-merger'
        assert saved['remediation']['activeAttempt'] is None
        assert saved['remediation']['halted']['reason'] == 'unsafe_blocker_change'
        assert saved['remediation']['halted']['mergeBlocker']['kind'] == 'manual_intervention_required'
        assert saved['statusMessage']['delivery']['status'] == 'finalized'
        assert saved['statusMessage']['delivery']['lastOperation'] == 'finalize'
        assert saved['statusMessage']['lastEvent']['lifecycleEvent'] == 'initiative_blocked'
        assert saved['statusMessage']['lastEvent']['initiative']['initiativeId'] == initiative_id
        assert 'out of the repairable passback scope' in (saved['statusMessage']['lastEvent']['summary'] or '')


def main() -> int:
    test_coordinator_lifecycle_create_then_update_reuses_single_message()
    test_invoker_blocked_and_terminal_updates_edit_existing_message()
    test_coordinator_merger_blocked_out_of_scope_persists_initiative_blocked()
    print('ok: lifecycle wiring emits create/update/finalize around initiative activation, subtask start, merge blocking, out-of-scope blocker halts, and terminal closure without forking duplicate status messages')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
