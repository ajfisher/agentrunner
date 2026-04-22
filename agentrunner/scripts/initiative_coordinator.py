#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from .initiative_status import build_status_message_event, ensure_status_message_state, resolve_status_message_operation
    from .initiative_status_discord import apply_discord_status_message
    from .merger_blockers import merger_result_uses_mvp_repairable_passback
except ImportError:  # pragma: no cover - script-mode fallback
    from initiative_status import build_status_message_event, ensure_status_message_state, resolve_status_message_operation
    from initiative_status_discord import apply_discord_status_message
    from merger_blockers import merger_result_uses_mvp_repairable_passback

ROOT = Path('/home/openclaw/projects/agentrunner')


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_json(path: str | Path, default):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def save_json(path: str | Path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(p)


def status_message_target_from_env() -> dict | None:
    raw = os.environ.get('AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON')
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def gateway_token() -> str | None:
    raw = os.environ.get('OPENCLAW_GATEWAY_TOKEN')
    if raw:
        return raw
    config_path = Path('/home/openclaw/.openclaw/openclaw.json')
    if not config_path.exists():
        return None
    try:
        cfg = json.loads(config_path.read_text())
    except Exception:
        return None
    gateway = cfg.get('gateway') if isinstance(cfg, dict) else {}
    auth = gateway.get('auth') if isinstance(gateway, dict) else {}
    token = auth.get('token') if isinstance(auth, dict) else None
    return token if isinstance(token, str) and token.strip() else None


def _gateway_message_invoke(_tool: str, args: dict) -> dict:
    url = os.environ.get('OPENCLAW_GATEWAY_HTTP', 'http://127.0.0.1:18789/tools/invoke')
    body = {'tool': 'message', 'args': args, 'action': args.get('action')}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    token = gateway_token()
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def emit_status_message(initiative_state: dict, *, lifecycle_event: str, summary: str, queue_item: dict | None = None, result: dict | None = None, blocked_reason: str | None = None, target: dict | None = None, invoke_gateway=None) -> bool:
    effective_target = target or status_message_target_from_env() or ((initiative_state.get('statusMessage') or {}).get('target') if isinstance(initiative_state.get('statusMessage'), dict) else None)
    current = ensure_status_message_state(initiative_state)
    if not effective_target and not current.get('handle'):
        return False
    operation = resolve_status_message_operation(initiative_state, lifecycle_event=lifecycle_event)
    event = build_status_message_event(
        operation=operation,
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item=queue_item,
        result=result,
        blocked_reason=blocked_reason,
    )
    apply_discord_status_message(
        initiative_state,
        operation=operation,
        lifecycle_event=lifecycle_event,
        event=event,
        invoke_gateway=invoke_gateway or _gateway_message_invoke,
        target=effective_target,
    )
    return True


def append_queue_event(state_dir: str, kind: str, *, item: dict | None = None, id: str | None = None, status: str | None = None) -> None:
    events = Path(state_dir) / 'queue_events.ndjson'
    out = Path(state_dir) / 'queue.json'
    cmd = ['python3', str(ROOT / 'agentrunner/scripts/queue_ledger.py'), '--events', str(events), '--out', str(out), '--append', '--kind', kind]
    if id is not None:
        cmd += ['--id', id]
    if status is not None:
        cmd += ['--status', status]
    if item is not None:
        cmd += ['--item', json.dumps(item, ensure_ascii=False)]
    subprocess.run(cmd, check=True)


def ensure_initiative_paths(state_dir: str, initiative: dict) -> dict:
    initiative_id = initiative['initiativeId']
    base = Path(state_dir) / 'initiatives' / initiative_id
    base.mkdir(parents=True, exist_ok=True)
    state_path = base / 'state.json'
    paths = {
        'initiativeDir': str(base),
        'initiativeStatePath': str(state_path),
        'managerBriefPath': str(base / 'brief.json'),
        'architectPlanPath': str(base / 'plan.json'),
        'managerDecisionPath': str(base / 'decision.json'),
    }
    if not state_path.exists():
        seeded = {
            'initiativeId': initiative_id,
            'phase': initiative.get('phase') or 'design-manager',
            'managerBriefPath': paths['managerBriefPath'],
            'architectPlanPath': paths['architectPlanPath'],
            'managerDecisionPath': paths['managerDecisionPath'],
            'currentSubtaskId': initiative.get('subtaskId'),
            'completedSubtasks': [],
            'pendingSubtasks': [],
            'branch': initiative.get('branch'),
            'base': initiative.get('base'),
            'writtenAt': iso_now(),
        }
        ensure_status_message_state(seeded)
        save_json(state_path, seeded)
    return paths


def enqueue_architect_item(state_dir: str, *, project: str, queue_item: dict, initiative_state: dict) -> None:
    initiative = queue_item['initiative']
    initiative_id = initiative['initiativeId']
    item = {
        'id': f'{initiative_id}-architect',
        'project': project,
        'role': 'architect',
        'createdAt': iso_now(),
        'repo_path': queue_item.get('repo_path'),
        'branch': queue_item.get('branch'),
        'base': queue_item.get('base'),
        'goal': f'Create the initial executable plan for initiative {initiative_id}. Read the Manager brief and emit an Architect plan with bounded subtasks.',
        'checks': [],
        'constraints': {'initiativePhase': 'design-architect'},
        'contextFiles': [],
        'initiative': {
            'initiativeId': initiative_id,
            'phase': 'design-architect',
            'branch': queue_item.get('branch'),
            'base': queue_item.get('base'),
        },
    }
    append_queue_event(state_dir, 'INSERT_FRONT', item=item)
    initiative_state['phase'] = 'design-architect'
    emit_status_message(
        initiative_state,
        lifecycle_event='initiative_activated',
        summary=f'Initiative {initiative_id} activated and handed to Architect planning.',
        queue_item=item,
    )


def compile_subtask_queue_item(*, project: str, repo_path: str | None, initiative_state: dict, plan: dict, subtask: dict) -> dict:
    initiative_id = plan['initiativeId']
    branch = initiative_state.get('branch')
    base = initiative_state.get('base')
    return {
        'id': f"{initiative_id}-{subtask['subtaskId']}",
        'project': project,
        'role': subtask.get('role', 'developer'),
        'createdAt': iso_now(),
        'repo_path': repo_path,
        'branch': branch,
        'base': base,
        'goal': subtask['goal'],
        'checks': subtask.get('checks', []),
        'constraints': subtask.get('constraints', {}),
        'contextFiles': subtask.get('contextFiles') or subtask.get('files') or [],
        'initiative': {
            'initiativeId': initiative_id,
            'subtaskId': subtask['subtaskId'],
            'managerBriefPath': initiative_state.get('managerBriefPath'),
            'architectPlanPath': initiative_state.get('architectPlanPath'),
            'branch': branch,
            'base': base,
        },
    }


def enqueue_first_subtask(state_dir: str, *, project: str, queue_item: dict, initiative_state: dict, plan: dict) -> None:
    subtasks = plan.get('subtasks') or []
    if not subtasks:
        return
    subtask = subtasks[0]
    item = compile_subtask_queue_item(project=project, repo_path=queue_item.get('repo_path'), initiative_state=initiative_state, plan=plan, subtask=subtask)
    append_queue_event(state_dir, 'INSERT_FRONT', item=item)
    initiative_state['phase'] = 'execution'
    initiative_state['currentSubtaskId'] = subtask['subtaskId']
    initiative_state['pendingSubtasks'] = [s['subtaskId'] for s in subtasks]
    initiative_state['completedSubtasks'] = []
    emit_status_message(
        initiative_state,
        lifecycle_event='subtask_started',
        summary=f"Started initiative subtask {subtask['subtaskId']}.",
        queue_item=item,
    )


def current_initiative_pointer(state: dict) -> dict | None:
    pointer = state.get('initiative') if isinstance(state.get('initiative'), dict) else None
    if not pointer:
        return None
    initiative_id = pointer.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return None
    return pointer


def is_terminal_success_phase(phase: object) -> bool:
    return phase in ('completed', 'closed')


def drop_same_initiative_tail_items(state_dir: str, *, initiative_id: str) -> list[str]:
    queue_path = Path(state_dir) / 'queue.json'
    queue = load_json(queue_path, [])
    if not isinstance(queue, list) or not queue:
        return []

    dropped_ids: list[str] = []
    for item in queue:
        if not isinstance(item, dict):
            continue
        item_initiative = item.get('initiative') if isinstance(item.get('initiative'), dict) else None
        if item_initiative and item_initiative.get('initiativeId') == initiative_id:
            item_id = item.get('id')
            if isinstance(item_id, str) and item_id:
                dropped_ids.append(item_id)

    if not dropped_ids:
        return []

    events_path = Path(state_dir) / 'queue_events.ndjson'
    if events_path.exists():
        for item_id in dropped_ids:
            append_queue_event(state_dir, 'CANCEL', id=item_id)
    else:
        queue = [
            item for item in queue
            if not (
                isinstance(item, dict)
                and isinstance(item.get('initiative'), dict)
                and item.get('initiative', {}).get('initiativeId') == initiative_id
            )
        ]
        save_json(queue_path, queue)
    return dropped_ids


def maybe_finalize_successful_initiative(state_dir: str, *, state: dict, queue_item: dict, initiative: dict, initiative_state_path: Path, initiative_state: dict, result: dict) -> bool:
    if queue_item.get('role') != 'merger':
        return False
    if result.get('status') != 'ok' or result.get('merged') is not True:
        return False
    if state.get('running') or state.get('current'):
        return False

    initiative_id = initiative.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return False

    drop_same_initiative_tail_items(state_dir, initiative_id=initiative_id)

    queue = load_json(Path(state_dir) / 'queue.json', [])
    if not isinstance(queue, list) or queue:
        return False

    pointer = current_initiative_pointer(state)
    initiative_id = initiative.get('initiativeId')
    if pointer and pointer.get('initiativeId') != initiative_id:
        return False

    initiative_state['phase'] = 'completed'
    initiative_state['currentSubtaskId'] = None
    emit_status_message(
        initiative_state,
        lifecycle_event='initiative_completed',
        summary=f'Initiative {initiative_id} completed and merged successfully.',
        queue_item=queue_item,
        result=result,
    )
    save_json(initiative_state_path, initiative_state)

    if pointer:
        state.pop('initiative', None)
        state['updatedAt'] = iso_now()
        save_json(Path(state_dir) / 'state.json', state)
    return True


def merger_result_blocker(result: dict) -> dict | None:
    if result.get('status') != 'blocked' or result.get('merged') is not False:
        return None
    blocker = result.get('mergeBlocker')
    if not isinstance(blocker, dict):
        return None
    return blocker


def merger_result_passback(result: dict) -> tuple[dict, dict] | tuple[None, None]:
    blocker = merger_result_blocker(result)
    if blocker is None:
        return None, None
    if not merger_result_uses_mvp_repairable_passback(result, target_role='developer'):
        return None, blocker
    passback = blocker.get('passback')
    if not isinstance(passback, dict):
        return None, blocker
    return passback, blocker


def enqueue_merger_remediation_item(state_dir: str, *, state: dict, last: dict, queue_item: dict, initiative: dict, initiative_state_path: Path, initiative_state: dict, result: dict) -> bool:
    if queue_item.get('role') != 'merger':
        return False
    if initiative_state.get('phase') != 'closure-merger':
        return False

    passback, blocker = merger_result_passback(result)
    if passback is None:
        return False

    initiative_id = initiative.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return False

    remediation = initiative_state.get('remediation') if isinstance(initiative_state.get('remediation'), dict) else {}
    attempts = remediation.get('attempts') if isinstance(remediation.get('attempts'), list) else []
    max_attempts = remediation.get('maxAttempts', 2)
    if not isinstance(max_attempts, int) or max_attempts < 1:
        max_attempts = 2
    if len(attempts) >= max_attempts:
        remediation['halted'] = {
            'at': iso_now(),
            'reason': 'budget_exhausted',
            'detail': f'Closure remediation budget exhausted after {len(attempts)} attempts.',
            'mergeBlocker': blocker,
        }
        remediation['activeAttempt'] = None
        initiative_state['remediation'] = remediation
        emit_status_message(
            initiative_state,
            lifecycle_event='initiative_blocked',
            summary=f'Initiative {initiative_id} is blocked after exhausting closure remediation budget.',
            queue_item=queue_item,
            result=result,
            blocked_reason=remediation['halted']['detail'],
        )
        save_json(initiative_state_path, initiative_state)
        return False

    attempt_number = len(attempts) + 1
    remediation_subtask_id = f'merger-remediation-{attempt_number}'
    remediation_item_id = f'{initiative_id}-{remediation_subtask_id}'

    reason = str(passback.get('reason') or '').strip() or 'Restore branch readiness so the initiative can return to closure review.'
    action = str(passback.get('action') or '').strip() or 'repair'
    branch = initiative_state.get('branch') or queue_item.get('branch')
    base = initiative_state.get('base') or queue_item.get('base')
    repo_path = queue_item.get('repo_path')
    result_path = last.get('resultPath')

    followup_item = {
        'id': remediation_item_id,
        'project': state.get('project'),
        'role': 'developer',
        'createdAt': iso_now(),
        'repo_path': repo_path,
        'branch': branch,
        'base': base,
        'goal': (
            f'Closure remediation attempt {attempt_number} for initiative {initiative_id}. '
            f'Perform the requested {action} work so {branch} is ready to merge into {base} again. '
            f'{reason}'
        ),
        'checks': queue_item.get('checks', []),
        'constraints': {
            'initiativePhase': 'execution',
            'closureRemediation': True,
            'closureRemediationAttempt': attempt_number,
            'closureSourceQueueItemId': queue_item.get('id'),
            'requiresReReview': bool(passback.get('requiresReReview')),
            'requiresMergeRetry': bool(passback.get('requiresMergeRetry')),
        },
        'contextFiles': queue_item.get('contextFiles', []),
        'initiative': {
            'initiativeId': initiative_id,
            'subtaskId': remediation_subtask_id,
            'managerBriefPath': initiative_state.get('managerBriefPath'),
            'architectPlanPath': initiative_state.get('architectPlanPath'),
            'branch': branch,
            'base': base,
        },
        'origin': {
            'requestedBy': queue_item.get('id'),
            'sourceResultPath': result_path,
            'mergeBlocker': result.get('mergeBlocker'),
            'closureRemediationAttempt': attempt_number,
            'closureMergerQueueItemId': queue_item.get('id'),
            'closureMergerResultPath': result_path,
            'closureTargetPhase': 'closure-merger',
        },
    }
    append_queue_event(state_dir, 'INSERT_FRONT', item=followup_item)

    attempts.append({
        'attempt': attempt_number,
        'subtaskId': remediation_subtask_id,
        'queueItemId': remediation_item_id,
        'sourceQueueItemId': queue_item.get('id'),
        'sourceResultPath': result_path,
        'requestedAt': iso_now(),
        'action': action,
        'reason': reason,
        'requiresReReview': bool(passback.get('requiresReReview')),
        'requiresMergeRetry': bool(passback.get('requiresMergeRetry')),
        'mergeBlocker': result.get('mergeBlocker'),
        'closurePhase': 'closure-merger',
        'closureSourceQueueItemId': queue_item.get('id'),
        'closureResultPath': result_path,
        'status': 'queued',
    })
    remediation['attempts'] = attempts
    remediation['lastAttempt'] = attempt_number
    remediation['activeAttempt'] = attempt_number
    remediation['maxAttempts'] = max_attempts
    remediation.pop('halted', None)
    initiative_state['remediation'] = remediation
    initiative_state['phase'] = 'execution'
    initiative_state['currentSubtaskId'] = remediation_subtask_id
    completed = list(initiative_state.get('completedSubtasks') or [])
    pending = [sid for sid in list(initiative_state.get('pendingSubtasks') or []) if sid != remediation_subtask_id]
    pending.insert(0, remediation_subtask_id)
    initiative_state['completedSubtasks'] = completed
    initiative_state['pendingSubtasks'] = pending
    emit_status_message(
        initiative_state,
        lifecycle_event='remediation_queued',
        summary=f'Queued closure remediation attempt {attempt_number} for initiative {initiative_id}.',
        queue_item=followup_item,
        result=result,
        blocked_reason=reason,
    )
    save_json(initiative_state_path, initiative_state)

    state['initiative'] = {'initiativeId': initiative_id, 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
    state['updatedAt'] = iso_now()
    save_json(Path(state_dir) / 'state.json', state)
    return True


def active_remediation_attempt(initiative_state: dict) -> dict | None:
    remediation = initiative_state.get('remediation') if isinstance(initiative_state.get('remediation'), dict) else None
    if not remediation:
        return None
    active_attempt = remediation.get('activeAttempt')
    if not isinstance(active_attempt, int):
        return None
    attempts = remediation.get('attempts') if isinstance(remediation.get('attempts'), list) else []
    for attempt in attempts:
        if isinstance(attempt, dict) and attempt.get('attempt') == active_attempt:
            return attempt
    return None


def enqueue_closure_merger_retry(state_dir: str, *, state: dict, queue_item: dict, initiative: dict, initiative_state_path: Path, initiative_state: dict, remediation_attempt: dict) -> bool:
    initiative_id = initiative.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return False

    branch = initiative_state.get('branch') or queue_item.get('branch')
    base = initiative_state.get('base') or queue_item.get('base')
    repo_path = queue_item.get('repo_path')
    attempt_number = remediation_attempt.get('attempt')
    if not isinstance(attempt_number, int) or attempt_number < 1:
        return False

    merger_item = {
        'id': f'{initiative_id}-merger-retry-{attempt_number}',
        'project': state.get('project'),
        'role': 'merger',
        'createdAt': iso_now(),
        'repo_path': repo_path,
        'branch': branch,
        'base': base,
        'goal': f'Closure merge retry {attempt_number} for initiative {initiative_id}. If the branch is again ready and fast-forward mergeable, merge {branch} into {base} using ff-only. Otherwise emit a blocked result and leave git state unchanged.',
        'checks': [
            f'git diff --stat {base}...{branch}',
            'git status --short',
            f'git merge-base --is-ancestor {base} {branch}',
        ],
        'constraints': {
            'mergePolicy': 'ff-only',
            'blockOnNonFF': True,
            'approvedByReviewer': True,
            'approvalQueueItemId': f"{queue_item.get('id')}-review",
            'initiativePhase': 'closure-merger',
            'closureRemediation': True,
            'closureRemediationAttempt': attempt_number,
            'closureSourceQueueItemId': remediation_attempt.get('closureSourceQueueItemId') or remediation_attempt.get('sourceQueueItemId'),
            'closureSourceResultPath': remediation_attempt.get('closureResultPath') or remediation_attempt.get('sourceResultPath'),
            'remediationReviewerQueueItemId': f"{queue_item.get('id')}-review",
        },
        'contextFiles': queue_item.get('contextFiles', []),
        'initiative': {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'branch': branch,
            'base': base,
        },
        'origin': {
            'requestedBy': queue_item.get('id'),
            'closureRemediationAttempt': attempt_number,
            'closureSourceQueueItemId': remediation_attempt.get('closureSourceQueueItemId') or remediation_attempt.get('sourceQueueItemId'),
            'closureSourceResultPath': remediation_attempt.get('closureResultPath') or remediation_attempt.get('sourceResultPath'),
            'remediationQueueItemId': queue_item.get('id'),
        },
    }
    append_queue_event(state_dir, 'INSERT_FRONT', item=merger_item)

    remediation_attempt['status'] = 'merge-retry-queued'
    remediation_attempt['mergeRetryQueueItemId'] = merger_item['id']
    remediation_attempt['reviewApprovedAt'] = iso_now()
    remediation = initiative_state.get('remediation') if isinstance(initiative_state.get('remediation'), dict) else {}
    remediation['activeAttempt'] = None
    remediation['lastResolvedAttempt'] = attempt_number
    remediation.pop('halted', None)
    initiative_state['remediation'] = remediation
    initiative_state['phase'] = 'closure-merger'
    initiative_state['currentSubtaskId'] = None
    save_json(initiative_state_path, initiative_state)

    state['initiative'] = {'initiativeId': initiative_id, 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
    state['updatedAt'] = iso_now()
    save_json(Path(state_dir) / 'state.json', state)
    return True


def maybe_advance(state_dir: str) -> bool:
    state_path = Path(state_dir) / 'state.json'
    state = load_json(state_path, {})
    last = state.get('lastCompleted') or {}
    current = state.get('current')
    if state.get('running') or current:
        return False
    qid = last.get('queueItemId')
    role = last.get('role')
    queue_item = last.get('queueItem') or {}
    if not qid or role not in ('manager', 'architect', 'developer', 'reviewer', 'merger'):
        return False
    if not isinstance(queue_item, dict):
        return False

    result_path = last.get('resultPath') or (Path(state_dir) / 'results' / f'{qid}.json')
    result = load_json(result_path, {})

    initiative = queue_item.get('initiative') if isinstance(queue_item.get('initiative'), dict) else None
    if not initiative or not initiative.get('initiativeId'):
        return False
    paths = ensure_initiative_paths(state_dir, initiative)
    initiative_state_path = Path(paths['initiativeStatePath'])
    initiative_state = load_json(initiative_state_path, {})

    if maybe_finalize_successful_initiative(
        state_dir,
        state=state,
        queue_item=queue_item,
        initiative=initiative,
        initiative_state_path=initiative_state_path,
        initiative_state=initiative_state,
        result=result,
    ):
        return True

    if enqueue_merger_remediation_item(
        state_dir,
        state=state,
        last=last,
        queue_item=queue_item,
        initiative=initiative,
        initiative_state_path=initiative_state_path,
        initiative_state=initiative_state,
        result=result,
    ):
        return True

    if queue_item.get('role') == 'merger' and initiative_state.get('phase') == 'closure-merger' and result.get('status') == 'blocked':
        blocker = merger_result_blocker(result)
        if blocker is not None:
            initiative_id = initiative.get('initiativeId')
            if not isinstance(initiative_id, str) or not initiative_id.strip():
                return False
            remediation = initiative_state.get('remediation') if isinstance(initiative_state.get('remediation'), dict) else {}
            remediation['halted'] = {
                'at': iso_now(),
                'reason': 'unsafe_blocker_change',
                'detail': 'Closure remediation stopped because the merger blocker is no longer in the supported repairable taxonomy (non_fast_forward, target_branch_missing).',
                'mergeBlocker': blocker,
            }
            remediation['activeAttempt'] = None
            initiative_state['remediation'] = remediation
            emit_status_message(
                initiative_state,
                lifecycle_event='initiative_blocked',
                summary=f'Initiative {initiative_id} blocked because the merger blocker changed out of the repairable passback scope.',
                queue_item=queue_item,
                result=result,
                blocked_reason=remediation['halted']['detail'],
            )
            save_json(initiative_state_path, initiative_state)
            return False

    if result.get('status') != 'ok':
        return False

    if is_terminal_success_phase(initiative_state.get('phase')):
        pointer = current_initiative_pointer(state)
        if pointer and pointer.get('initiativeId') == initiative.get('initiativeId'):
            state.pop('initiative', None)
            state['updatedAt'] = iso_now()
            save_json(state_path, state)
            return True
        return False

    if role == 'manager':
        phase = initiative_state.get('phase')
        if phase in ('design-manager', None, ''):
            brief_path = Path(paths['managerBriefPath'])
            if not brief_path.exists():
                return False
            enqueue_architect_item(state_dir, project=state.get('project'), queue_item=queue_item, initiative_state=initiative_state)
            save_json(initiative_state_path, initiative_state)
            state['initiative'] = {'initiativeId': initiative['initiativeId'], 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
            save_json(state_path, state)
            return True

        if phase == 'review-manager':
            decision_path = Path(paths['managerDecisionPath'])
            if not decision_path.exists():
                return False
            decision = load_json(decision_path, {})
            choice = decision.get('decision')
            initiative_id = initiative['initiativeId']
            branch = initiative_state.get('branch') or queue_item.get('branch')
            base = initiative_state.get('base') or queue_item.get('base')
            repo_path = queue_item.get('repo_path')

            if choice == 'complete':
                merger_item = {
                    'id': f'{initiative_id}-merger',
                    'project': state.get('project'),
                    'role': 'merger',
                    'createdAt': iso_now(),
                    'repo_path': repo_path,
                    'branch': branch,
                    'base': base,
                    'goal': f'If initiative {initiative_id} is still ready and fast-forward mergeable, merge {branch} into {base} using ff-only. Otherwise emit a blocked result and leave git state unchanged.',
                    'checks': [
                        f'git diff --stat {base}...{branch}',
                        'git status --short',
                        f'git merge-base --is-ancestor {base} {branch}',
                    ],
                    'constraints': {
                        'mergePolicy': 'ff-only',
                        'blockOnNonFF': True,
                        'approvedByReviewer': True,
                        'approvalQueueItemId': qid,
                        'initiativePhase': 'closure-merger',
                    },
                    'contextFiles': [],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'phase': 'closure-merger',
                        'branch': branch,
                        'base': base,
                    },
                }
                append_queue_event(state_dir, 'INSERT_FRONT', item=merger_item)
                initiative_state['phase'] = 'closure-merger'
            elif choice == 'architect':
                architect_item = {
                    'id': f'{initiative_id}-architect-replan',
                    'project': state.get('project'),
                    'role': 'architect',
                    'createdAt': iso_now(),
                    'repo_path': repo_path,
                    'branch': branch,
                    'base': base,
                    'goal': f'Replan initiative {initiative_id}. Read the Manager closure decision and update the Architect plan with a revised bounded subtask sequence.',
                    'checks': [],
                    'constraints': {'initiativePhase': 'replan-architect'},
                    'contextFiles': [],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'phase': 'replan-architect',
                        'branch': branch,
                        'base': base,
                    },
                }
                append_queue_event(state_dir, 'INSERT_FRONT', item=architect_item)
                initiative_state['phase'] = 'replan-architect'
            else:
                return False

            save_json(initiative_state_path, initiative_state)
            state['initiative'] = {'initiativeId': initiative['initiativeId'], 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
            save_json(state_path, state)
            return True

        return False

    if role == 'architect':
        plan_path = Path(paths['architectPlanPath'])
        if not plan_path.exists() or initiative_state.get('phase') not in ('design-architect', 'replan-architect'):
            return False
        plan = load_json(plan_path, {})
        enqueue_first_subtask(state_dir, project=state.get('project'), queue_item=queue_item, initiative_state=initiative_state, plan=plan)
        save_json(initiative_state_path, initiative_state)
        state['initiative'] = {'initiativeId': initiative['initiativeId'], 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
        save_json(state_path, state)
        return True

    if role == 'developer':
        if initiative_state.get('phase') != 'execution':
            return False
        current_subtask_id = initiative.get('subtaskId') or initiative_state.get('currentSubtaskId')
        if not current_subtask_id:
            return False
        reviewer_item = {
            'id': f"{qid}-review",
            'project': state.get('project'),
            'role': 'reviewer',
            'createdAt': iso_now(),
            'repo_path': queue_item.get('repo_path'),
            'branch': queue_item.get('branch'),
            'base': queue_item.get('base'),
            'goal': f"Review completed initiative subtask {current_subtask_id} for initiative {initiative['initiativeId']}. Approve if the subtask intent is satisfied, or emit a clean handoff if follow-up Developer work is needed.",
            'checks': queue_item.get('checks', []),
            'constraints': {'initiativePhase': 'execution-review'},
            'contextFiles': queue_item.get('contextFiles', []),
            'initiative': {
                'initiativeId': initiative['initiativeId'],
                'subtaskId': current_subtask_id,
                'managerBriefPath': initiative.get('managerBriefPath'),
                'architectPlanPath': initiative.get('architectPlanPath'),
                'branch': queue_item.get('branch'),
                'base': queue_item.get('base'),
            },
            'origin': {
                'sourceResultPath': last.get('resultPath'),
                'requestedBy': qid,
            },
        }
        append_queue_event(state_dir, 'INSERT_FRONT', item=reviewer_item)
        save_json(initiative_state_path, initiative_state)
        state['initiative'] = {'initiativeId': initiative['initiativeId'], 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
        save_json(state_path, state)
        return True

    if role == 'reviewer':
        if initiative_state.get('phase') != 'execution':
            return False
        if result.get('approved') is not True:
            return False
        plan_path = Path(paths['architectPlanPath'])
        if not plan_path.exists():
            return False
        plan = load_json(plan_path, {})
        subtasks = plan.get('subtasks') or []
        current_subtask_id = initiative.get('subtaskId') or initiative_state.get('currentSubtaskId')
        if not current_subtask_id:
            return False
        completed = list(initiative_state.get('completedSubtasks') or [])
        pending = list(initiative_state.get('pendingSubtasks') or [s.get('subtaskId') for s in subtasks])
        if current_subtask_id not in completed:
            completed.append(current_subtask_id)
        pending = [sid for sid in pending if sid != current_subtask_id]
        initiative_state['completedSubtasks'] = completed
        initiative_state['pendingSubtasks'] = pending

        remediation_attempt = active_remediation_attempt(initiative_state)
        if remediation_attempt and remediation_attempt.get('subtaskId') == current_subtask_id:
            remediation_attempt['status'] = 'review-approved'
            remediation_attempt['reviewApprovedAt'] = iso_now()
            if remediation_attempt.get('requiresMergeRetry'):
                if enqueue_closure_merger_retry(
                    state_dir,
                    state=state,
                    queue_item=queue_item,
                    initiative=initiative,
                    initiative_state_path=initiative_state_path,
                    initiative_state=initiative_state,
                    remediation_attempt=remediation_attempt,
                ):
                    return True
            remediation = initiative_state.get('remediation') if isinstance(initiative_state.get('remediation'), dict) else {}
            remediation['activeAttempt'] = None
            initiative_state['remediation'] = remediation

        if pending:
            next_id = pending[0]
            next_subtask = next((s for s in subtasks if s.get('subtaskId') == next_id), None)
            if next_subtask is None:
                return False
            item = compile_subtask_queue_item(project=state.get('project'), repo_path=queue_item.get('repo_path'), initiative_state=initiative_state, plan=plan, subtask=next_subtask)
            append_queue_event(state_dir, 'INSERT_FRONT', item=item)
            initiative_state['currentSubtaskId'] = next_id
            initiative_state['phase'] = 'execution'
        else:
            initiative_id = initiative['initiativeId']
            manager_item = {
                'id': f'{initiative_id}-manager-review',
                'project': state.get('project'),
                'role': 'manager',
                'createdAt': iso_now(),
                'repo_path': queue_item.get('repo_path'),
                'branch': initiative_state.get('branch') or queue_item.get('branch'),
                'base': initiative_state.get('base') or queue_item.get('base'),
                'goal': f'Perform bundle-level closure review for initiative {initiative_id}. Decide only whether the initiative is complete enough to close (`complete`) or needs another Architect pass (`architect`).',
                'checks': [],
                'constraints': {'initiativePhase': 'review-manager'},
                'contextFiles': [],
                'initiative': {
                    'initiativeId': initiative_id,
                    'phase': 'review-manager',
                    'branch': initiative_state.get('branch') or queue_item.get('branch'),
                    'base': initiative_state.get('base') or queue_item.get('base'),
                },
            }
            append_queue_event(state_dir, 'INSERT_FRONT', item=manager_item)
            initiative_state['phase'] = 'review-manager'
            initiative_state['currentSubtaskId'] = None

        save_json(initiative_state_path, initiative_state)
        state['initiative'] = {'initiativeId': initiative['initiativeId'], 'phase': initiative_state.get('phase'), 'statePath': str(initiative_state_path)}
        save_json(state_path, state)
        return True

    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--state-dir', required=True)
    ap.add_argument('--ensure-initiative-id')
    ap.add_argument('--project')
    ap.add_argument('--branch')
    ap.add_argument('--base')
    args = ap.parse_args()

    if args.ensure_initiative_id:
        initiative = {'initiativeId': args.ensure_initiative_id, 'branch': args.branch, 'base': args.base}
        paths = ensure_initiative_paths(args.state_dir, initiative)
        state_path = Path(args.state_dir) / 'state.json'
        state = load_json(state_path, {})
        state['initiative'] = {'initiativeId': args.ensure_initiative_id, 'phase': 'design-manager', 'statePath': paths['initiativeStatePath']}
        save_json(state_path, state)
        print(json.dumps(paths, indent=2))
        return 0

    changed = maybe_advance(args.state_dir)
    print(json.dumps({'changed': changed}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
