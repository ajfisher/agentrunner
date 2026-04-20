#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agentrunner/scripts'))

from initiative_status import build_status_message_event, ensure_status_message_state  # noqa: E402
from initiative_status_discord import (  # noqa: E402
    DISCORD_ADAPTER,
    apply_discord_status_message,
    load_discord_status_target,
    merge_status_target,
    normalize_discord_message_handle,
    render_discord_status_message,
)


def base_initiative_state() -> dict:
    state = {
        'initiativeId': 'agentrunner-status-message-adapters',
        'phase': 'execution',
        'currentSubtaskId': 'discord-adapter',
        'branch': 'feature/agentrunner/status-message-adapters',
        'base': 'master',
    }
    ensure_status_message_state(state)
    return state


def activation_event(initiative_state: dict) -> dict:
    return build_status_message_event(
        operation='create',
        lifecycle_event='initiative_activated',
        initiative_state=initiative_state,
        summary='Initiative is active and the first Discord status message should be created.',
        queue_item={
            'id': 'agentrunner-status-message-adapters-discord-adapter',
            'role': 'developer',
            'goal': 'Implement the first Discord status message adapter.',
        },
    )


def update_event(initiative_state: dict) -> dict:
    return build_status_message_event(
        operation='update',
        lifecycle_event='review_approved',
        initiative_state=initiative_state,
        summary='Reviewer approved the adapter shape; keep editing the same message.',
        queue_item={
            'id': 'agentrunner-status-message-adapters-discord-adapter-review',
            'role': 'reviewer',
            'goal': 'Review the Discord adapter slice.',
        },
        result={
            'status': 'ok',
            'approved': True,
            'summary': 'Adapter shape is approved.',
        },
    )


def finalize_event(initiative_state: dict) -> dict:
    return build_status_message_event(
        operation='finalize',
        lifecycle_event='initiative_completed',
        initiative_state=initiative_state,
        summary='Initiative completed and the status message should be finalized with the commit id.',
        queue_item={
            'id': 'agentrunner-status-message-adapters-discord-adapter',
            'role': 'developer',
            'goal': 'Ship the Discord adapter implementation.',
        },
        result={
            'status': 'ok',
            'commit': 'abcdef1234567890fedcba',
            'summary': 'Shipped Discord adapter create/update/finalize support.',
        },
    )


def test_target_loading_and_merge_keep_routing_compact() -> None:
    loaded = load_discord_status_target({
        'target': 'channel:1477159463143084217',
        'thread_id': '1477999999999999999',
        'metadata': {'initiative': 'agentrunner-status-message-adapters'},
    })
    assert loaded == {
        'channel': 'discord',
        'target': 'channel:1477159463143084217',
        'threadId': '1477999999999999999',
        'title': 'AgentRunner Initiative Status',
        'metadata': {'initiative': 'agentrunner-status-message-adapters'},
    }

    merged = merge_status_target(
        {'target': 'channel:old', 'metadata': {'persisted': True}},
        {'target': 'channel:new', 'metadata': {'override': True}},
    )
    assert merged['target'] == 'channel:new'
    assert merged['metadata'] == {'persisted': True, 'override': True}


def test_normalize_message_handle_accepts_common_gateway_shapes() -> None:
    nested = normalize_discord_message_handle(
        {
            'ok': True,
            'result': {
                'message_id': '12345',
                'channel_id': '67890',
                'thread_id': 'abcde',
                'url': 'https://discord.com/channels/guild/67890/12345',
            },
        },
        fallback_target={'target': 'channel:67890'},
    )
    assert nested == {
        'id': '12345',
        'channelId': '67890',
        'threadId': 'abcde',
        'provider': DISCORD_ADAPTER,
        'url': 'https://discord.com/channels/guild/67890/12345',
    }

    minimal = normalize_discord_message_handle('22222', fallback_target={'target': 'channel:99999'})
    assert minimal == {
        'id': '22222',
        'channelId': '99999',
        'provider': DISCORD_ADAPTER,
    }


def test_rendered_message_is_compact_and_includes_result_bits() -> None:
    initiative_state = base_initiative_state()
    rendered = render_discord_status_message(finalize_event(initiative_state))
    assert '**AgentRunner Initiative Status**' in rendered
    assert 'Initiative: `agentrunner-status-message-adapters`' in rendered
    assert 'Lifecycle: `initiative_completed`' in rendered
    assert 'commit=abcdef123456' in rendered
    assert 'Summary: Initiative completed and the status message should be finalized with the commit id.' in rendered


def test_create_then_update_then_finalize_reuses_single_handle() -> None:
    initiative_state = base_initiative_state()
    calls: list[tuple[str, dict]] = []

    def fake_gateway(tool: str, args: dict) -> dict:
        calls.append((tool, dict(args)))
        if args['action'] == 'send':
            return {
                'ok': True,
                'message': {
                    'id': 'msg-1',
                    'channelId': '1477159463143084217',
                    'threadId': 'thread-1',
                    'url': 'https://discord.com/channels/guild/1477159463143084217/msg-1',
                },
            }
        return {
            'ok': True,
            'messageId': args['messageId'],
            'channelId': args.get('channelId') or '1477159463143084217',
            'threadId': args.get('threadId') or 'thread-1',
        }

    target = {'target': 'channel:1477159463143084217', 'threadId': 'thread-1'}
    created = apply_discord_status_message(
        initiative_state,
        operation='create',
        lifecycle_event='initiative_activated',
        event=activation_event(initiative_state),
        invoke_gateway=fake_gateway,
        target=target,
    )
    assert created.ok is True
    assert created.handle == {
        'id': 'msg-1',
        'channelId': '1477159463143084217',
        'threadId': 'thread-1',
        'provider': DISCORD_ADAPTER,
        'url': 'https://discord.com/channels/guild/1477159463143084217/msg-1',
    }
    status_message = initiative_state['statusMessage']
    assert status_message['adapter'] == DISCORD_ADAPTER
    assert status_message['handle']['id'] == 'msg-1'
    assert status_message['delivery']['status'] == 'active'
    assert status_message['delivery']['lastOperation'] == 'create'

    updated = apply_discord_status_message(
        initiative_state,
        operation='update',
        lifecycle_event='review_approved',
        event=update_event(initiative_state),
        invoke_gateway=fake_gateway,
    )
    assert updated.ok is True
    assert updated.handle['id'] == 'msg-1'
    assert initiative_state['statusMessage']['delivery']['lastOperation'] == 'update'
    assert initiative_state['statusMessage']['delivery']['status'] == 'active'

    finalized = apply_discord_status_message(
        initiative_state,
        operation='finalize',
        lifecycle_event='initiative_completed',
        event=finalize_event(initiative_state),
        invoke_gateway=fake_gateway,
    )
    assert finalized.ok is True
    assert finalized.handle['id'] == 'msg-1'
    assert initiative_state['statusMessage']['delivery']['status'] == 'finalized'
    assert initiative_state['statusMessage']['delivery']['finalizedAt'] is not None
    assert len(calls) == 3
    assert calls[0][1]['action'] == 'send'
    assert calls[1][1]['action'] == 'edit'
    assert calls[1][1]['messageId'] == 'msg-1'
    assert calls[2][1]['action'] == 'edit'
    assert calls[2][1]['messageId'] == 'msg-1'


def test_delivery_failures_are_recorded_without_losing_state() -> None:
    initiative_state = base_initiative_state()
    initiative_state['statusMessage']['target'] = {'channel': 'discord', 'target': 'channel:1477159463143084217'}
    initiative_state['statusMessage']['handle'] = {'id': 'msg-existing', 'channelId': '1477159463143084217', 'provider': 'discord'}

    def boom(_tool: str, _args: dict) -> dict:
        raise RuntimeError('simulated discord outage for proof')

    result = apply_discord_status_message(
        initiative_state,
        operation='update',
        lifecycle_event='merge_blocked',
        event=build_status_message_event(
            operation='update',
            lifecycle_event='merge_blocked',
            initiative_state=initiative_state,
            summary='Merge blocked; keep state but mark delivery failure.',
            blocked_reason='Branch is no longer fast-forward mergeable.',
            result={'status': 'blocked', 'merged': False, 'summary': 'ff-only merge blocked'},
        ),
        invoke_gateway=boom,
    )

    assert result.ok is False
    assert 'simulated discord outage for proof' in (result.error or '')
    status_message = initiative_state['statusMessage']
    assert status_message['handle']['id'] == 'msg-existing'
    assert status_message['delivery']['status'] == 'error'
    assert 'simulated discord outage for proof' in (status_message['delivery']['lastError'] or '')
    assert status_message['history'][-1]['status'] == 'error'


def test_structured_create_failure_payload_is_treated_as_error() -> None:
    initiative_state = base_initiative_state()

    def structured_failure(_tool: str, args: dict) -> dict:
        assert args['action'] == 'send'
        return {
            'ok': False,
            'error': 'discord gateway rejected send',
            'code': 'RATE_LIMITED',
        }

    result = apply_discord_status_message(
        initiative_state,
        operation='create',
        lifecycle_event='initiative_activated',
        event=activation_event(initiative_state),
        invoke_gateway=structured_failure,
        target={'target': 'channel:1477159463143084217'},
    )

    assert result.ok is False
    assert 'discord gateway rejected send' in (result.error or '')
    status_message = initiative_state['statusMessage']
    assert status_message['delivery']['status'] == 'error'
    assert status_message['delivery']['metadata']['lastResponseOk'] is False
    assert 'discord gateway rejected send' in (status_message['delivery']['lastError'] or '')


def test_structured_edit_failure_payload_keeps_handle_but_marks_error() -> None:
    initiative_state = base_initiative_state()
    initiative_state['statusMessage']['target'] = {'channel': 'discord', 'target': 'channel:1477159463143084217'}
    initiative_state['statusMessage']['handle'] = {'id': 'msg-existing', 'channelId': '1477159463143084217', 'provider': 'discord'}

    def structured_failure(_tool: str, args: dict) -> dict:
        assert args['action'] == 'edit'
        return {
            'success': False,
            'message': 'discord gateway rejected edit',
            'details': {'reason': 'unknown message'},
        }

    result = apply_discord_status_message(
        initiative_state,
        operation='update',
        lifecycle_event='review_blocked',
        event=build_status_message_event(
            operation='update',
            lifecycle_event='review_blocked',
            initiative_state=initiative_state,
            summary='Structured edit failure should not look healthy.',
            blocked_reason='Discord rejected the edit.',
            result={'status': 'blocked', 'summary': 'edit rejected'},
        ),
        invoke_gateway=structured_failure,
    )

    assert result.ok is False
    assert result.handle is not None
    assert result.handle['id'] == 'msg-existing'
    status_message = initiative_state['statusMessage']
    assert status_message['handle']['id'] == 'msg-existing'
    assert status_message['delivery']['status'] == 'error'
    assert status_message['delivery']['metadata']['lastResponseOk'] is False
    assert 'discord gateway rejected edit' in (status_message['delivery']['lastError'] or '')


def main() -> int:
    test_target_loading_and_merge_keep_routing_compact()
    test_normalize_message_handle_accepts_common_gateway_shapes()
    test_rendered_message_is_compact_and_includes_result_bits()
    test_create_then_update_then_finalize_reuses_single_handle()
    test_delivery_failures_are_recorded_without_losing_state()
    test_structured_create_failure_payload_is_treated_as_error()
    test_structured_edit_failure_payload_keeps_handle_but_marks_error()
    print('ok: initiative status Discord adapter proof covers target normalization, handle parsing, single-message create/update/finalize flow, and exception/structured failure-tolerant state persistence')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
