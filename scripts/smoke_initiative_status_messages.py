#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agentrunner/scripts'))

from initiative_status import build_status_message_event, ensure_status_message_state  # noqa: E402
from initiative_status_discord import apply_discord_status_message  # noqa: E402


TARGET = {
    'channel': 'discord',
    'target': 'channel:1477159463143084217',
    'threadId': 'thread-1',
}


def base_initiative_state() -> dict:
    state = {
        'initiativeId': 'smoke-initiative-status-message',
        'phase': 'execution',
        'currentSubtaskId': 'docs-and-smoke',
        'branch': 'feature/agentrunner/status-message-adapters',
        'base': 'master',
    }
    ensure_status_message_state(state)
    return state


def fake_gateway(_tool: str, args: dict) -> dict:
    action = args['action']
    if action == 'send':
        return {
            'ok': True,
            'message': {
                'id': 'msg-1',
                'channelId': '1477159463143084217',
                'threadId': 'thread-1',
                'url': 'https://discord.com/channels/guild/1477159463143084217/msg-1',
            },
        }
    if action == 'edit':
        return {
            'ok': True,
            'messageId': args['messageId'],
            'channelId': args.get('channelId') or '1477159463143084217',
            'threadId': args.get('threadId') or 'thread-1',
        }
    raise AssertionError(f'unexpected action: {action}')


def failing_edit_gateway(_tool: str, args: dict) -> dict:
    assert args['action'] == 'edit'
    return {
        'success': False,
        'message': 'discord gateway rejected edit',
        'details': {'reason': 'simulated smoke failure'},
    }


def event(initiative_state: dict, *, operation: str, lifecycle_event: str, summary: str, result: dict | None = None, blocked_reason: str | None = None) -> dict:
    return build_status_message_event(
        operation=operation,
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item={
            'id': 'smoke-initiative-status-message-docs-and-smoke',
            'role': 'developer',
            'goal': 'Exercise create, update, finalize, and failure-tolerant delivery behavior.',
        },
        result=result,
        blocked_reason=blocked_reason,
    )


def main() -> int:
    initiative_state = base_initiative_state()

    created = apply_discord_status_message(
        initiative_state,
        operation='create',
        lifecycle_event='initiative_activated',
        event=event(
            initiative_state,
            operation='create',
            lifecycle_event='initiative_activated',
            summary='Smoke create: first status message should be emitted.',
        ),
        invoke_gateway=fake_gateway,
        target=TARGET,
    )
    assert created.ok is True
    assert initiative_state['statusMessage']['handle']['id'] == 'msg-1'
    assert initiative_state['statusMessage']['delivery']['status'] == 'active'

    updated = apply_discord_status_message(
        initiative_state,
        operation='update',
        lifecycle_event='review_approved',
        event=event(
            initiative_state,
            operation='update',
            lifecycle_event='review_approved',
            summary='Smoke update: edit the same message after review approval.',
            result={'status': 'ok', 'approved': True, 'summary': 'review approved'},
        ),
        invoke_gateway=fake_gateway,
    )
    assert updated.ok is True
    assert updated.handle is not None
    assert updated.handle['id'] == 'msg-1'
    assert initiative_state['statusMessage']['delivery']['lastOperation'] == 'update'

    finalized = apply_discord_status_message(
        initiative_state,
        operation='finalize',
        lifecycle_event='initiative_completed',
        event=event(
            initiative_state,
            operation='finalize',
            lifecycle_event='initiative_completed',
            summary='Smoke finalize: close the lifecycle against the same message handle.',
            result={'status': 'ok', 'commit': 'abcdef1234567890', 'summary': 'initiative completed'},
        ),
        invoke_gateway=fake_gateway,
    )
    assert finalized.ok is True
    assert finalized.handle is not None
    assert finalized.handle['id'] == 'msg-1'
    assert initiative_state['statusMessage']['delivery']['status'] == 'finalized'
    assert initiative_state['statusMessage']['delivery']['finalizedAt'] is not None

    initiative_state['statusMessage']['delivery']['status'] = 'active'
    failed = apply_discord_status_message(
        initiative_state,
        operation='update',
        lifecycle_event='review_blocked',
        event=event(
            initiative_state,
            operation='update',
            lifecycle_event='review_blocked',
            summary='Smoke failure: preserve the handle and mark delivery error.',
            result={'status': 'blocked', 'summary': 'edit rejected'},
            blocked_reason='Simulated Discord edit failure.',
        ),
        invoke_gateway=failing_edit_gateway,
    )
    assert failed.ok is False
    assert initiative_state['statusMessage']['handle']['id'] == 'msg-1'
    assert initiative_state['statusMessage']['delivery']['status'] == 'error'
    assert 'discord gateway rejected edit' in (initiative_state['statusMessage']['delivery']['lastError'] or '')

    print('ok: smoke_initiative_status_messages exercises create, update, finalize, and failure-tolerant edit handling without forking duplicate status messages')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
