#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, subprocess, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('/home/openclaw/projects/agentrunner')
CONFIG_PATH = Path('/home/openclaw/.openclaw/openclaw.json')
VALID_STATUSES = {'ok', 'blocked', 'error', 'completed'}
VALID_ROLES = {'developer', 'reviewer', 'manager', 'merger', 'architect'}


from status_artifact import build_status_artifact, write_status_artifact
from operator_mqtt import maybe_publish_operator_snapshot
from initiative_status import build_status_message_event, ensure_status_message_state, resolve_status_message_operation
from initiative_status_discord import apply_discord_status_message


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


def operator_mqtt_config() -> dict:
    if os.environ.get('AGENTRUNNER_OPERATOR_MQTT_CONFIG_JSON'):
        try:
            raw = json.loads(os.environ['AGENTRUNNER_OPERATOR_MQTT_CONFIG_JSON'])
            return raw if isinstance(raw, dict) else {}
        except Exception:
            debug_log('[invoker] invalid AGENTRUNNER_OPERATOR_MQTT_CONFIG_JSON; ignoring')
            return {}
    cfg = load_json(CONFIG_PATH, {})
    raw = cfg.get('operatorMqtt') if isinstance(cfg, dict) else {}
    return raw if isinstance(raw, dict) else {}


def refresh_operator_status(state_dir: str | Path) -> None:
    state_path = Path(state_dir)
    artifact = build_status_artifact(state_path)
    write_status_artifact(state_path, artifact)
    try:
        publish_result = maybe_publish_operator_snapshot(state_dir=state_path, config=operator_mqtt_config())
        debug_log(f"[invoker] {publish_result.note}")
    except Exception as e:
        debug_log(f'[invoker] operator MQTT seam failed unexpectedly: {e}')


def debug_log(msg: str) -> None:
    try:
        with open('/tmp/agentrunner-picv.log', 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass


def gateway_token() -> str | None:
    if os.environ.get('OPENCLAW_GATEWAY_TOKEN'):
        return os.environ['OPENCLAW_GATEWAY_TOKEN']
    cfg = load_json(CONFIG_PATH, {})
    return (((cfg.get('gateway') or {}).get('auth') or {}).get('token'))


def gateway_http_invoke(tool: str, args: dict, *, action: str | None = None) -> dict:
    url = os.environ.get('OPENCLAW_GATEWAY_HTTP', 'http://127.0.0.1:18789/tools/invoke')
    token = gateway_token()
    body = {'tool': tool, 'args': args}
    if action:
        body['action'] = action
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def status_message_target_from_env() -> dict | None:
    raw = os.environ.get('AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON')
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def emit_initiative_status_update(state_dir: str | Path, *, queue_item: dict | None, result: dict) -> bool:
    if not isinstance(queue_item, dict):
        return False
    initiative = queue_item.get('initiative') if isinstance(queue_item.get('initiative'), dict) else None
    if not initiative:
        return False
    initiative_id = initiative.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return False
    initiative_state_path = Path(state_dir) / 'initiatives' / initiative_id / 'state.json'
    if not initiative_state_path.exists():
        return False
    initiative_state = load_json(initiative_state_path, {})
    current = ensure_status_message_state(initiative_state)
    effective_target = ((current.get('target') if isinstance(current, dict) else None) or status_message_target_from_env())
    if not effective_target and not current.get('handle'):
        return False

    role = str(queue_item.get('role') or '')
    lifecycle_event = None
    summary = str(result.get('summary') or '').strip() or None
    blocked_reason = None
    if role == 'reviewer' and result.get('approved') is True:
        lifecycle_event = 'review_approved'
        summary = summary or f"Reviewer approved initiative subtask {initiative.get('subtaskId') or initiative_state.get('currentSubtaskId') or '-'}"
    elif role == 'reviewer' and result.get('status') == 'blocked':
        lifecycle_event = 'review_blocked'
        blocked_reason = summary
    elif role == 'merger' and result.get('status') == 'blocked':
        lifecycle_event = 'merge_blocked'
        blocker = result.get('mergeBlocker') if isinstance(result.get('mergeBlocker'), dict) else {}
        blocked_reason = str(blocker.get('detail') or summary or 'Merge blocked').strip() or None
    elif role == 'merger' and result.get('status') == 'ok' and result.get('merged') is True:
        lifecycle_event = 'merge_completed'
        summary = summary or f"Merged {initiative_state.get('branch') or queue_item.get('branch')} into {initiative_state.get('base') or queue_item.get('base')}"
    if not lifecycle_event:
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
        invoke_gateway=lambda tool, args: gateway_http_invoke(tool, args, action=args.get('action')),
        target=effective_target,
    )
    save_json(initiative_state_path, initiative_state)
    return True


def parse_iso(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def maybe_send_watchdog(state: dict, cur: dict, *, channel: str | None, to: str | None) -> None:
    if not channel or not to:
        return
    started = parse_iso(cur.get('startedAt'))
    if started is None:
        return
    now = datetime.now(timezone.utc).astimezone()
    age = now - started
    if age < timedelta(minutes=2):
        return
    sent_at = parse_iso(cur.get('watchdogSentAt'))
    if sent_at is not None:
        return
    role = cur.get('role') or 'unknown'
    qid = cur.get('queueItemId') or 'unknown'
    msg = f"{str(role).title()} ›\n- Status: waiting for result artifact\n- Queue item: {qid}\n- Run has been active for >2 minutes without RESULT_PATH appearing\n- Likely worker contract failure; keeping queue locked for now"
    try:
        gateway_http_invoke('message', {'action': 'send', 'channel': channel, 'target': to, 'message': msg}, action='send')
        cur['watchdogSentAt'] = iso_now()
    except Exception as e:
        debug_log(f'[invoker] watchdog send failed: {e}')


def stale_run_should_unlock(cur: dict) -> bool:
    started = parse_iso(cur.get('startedAt'))
    if started is None:
        return False
    now = datetime.now(timezone.utc).astimezone()
    return (now - started) >= timedelta(minutes=12)


def hooks_token() -> str | None:
    if os.environ.get('OPENCLAW_HOOKS_TOKEN'):
        return os.environ['OPENCLAW_HOOKS_TOKEN']
    cfg = load_json(CONFIG_PATH, {})
    return ((cfg.get('hooks') or {}).get('token'))


def hooks_agent(payload: dict) -> dict:
    url = os.environ.get('OPENCLAW_HOOKS_AGENT_URL', 'http://127.0.0.1:18789/hooks/agent')
    token = hooks_token()
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    debug_log(f"[invoker] POST {url} sessionKey={payload.get('sessionKey')}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def materialize_queue(state_dir: str) -> None:
    events = Path(state_dir) / 'queue_events.ndjson'
    out = Path(state_dir) / 'queue.json'
    if not events.exists():
        return
    subprocess.run(['python3', str(ROOT / 'agentrunner/scripts/queue_ledger.py'), '--events', str(events), '--out', str(out)], check=True)


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


def append_tick(state_dir: str, record: dict) -> None:
    ticks = Path(state_dir) / 'ticks.ndjson'
    subprocess.run(['python3', str(ROOT / 'agentrunner/scripts/log_append.py'), '--path', str(ticks), '--record', json.dumps(record, ensure_ascii=False)], check=True)


def load_role_prompt(role: str) -> str:
    return (ROOT / f'agentrunner/prompts/{role}.txt').read_text().strip() + '\n'


def run_initiative_coordinator(state_dir: str) -> bool:
    proc = subprocess.run(
        ['python3', str(ROOT / 'agentrunner/scripts/initiative_coordinator.py'), '--state-dir', state_dir],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        debug_log(f'[invoker] initiative coordinator rc={proc.returncode}: {(proc.stderr or proc.stdout).strip()}')
        return False
    try:
        payload = json.loads((proc.stdout or '').strip() or '{}')
    except Exception:
        debug_log(f'[invoker] initiative coordinator returned non-JSON stdout: {(proc.stdout or '').strip()}')
        return False
    return bool(payload.get('changed'))


def current_closure_snapshot(state_dir: str | Path) -> dict:
    try:
        artifact = build_status_artifact(Path(state_dir))
    except Exception as e:
        debug_log(f'[invoker] failed to build closure snapshot: {e}')
        return {}
    closure = artifact.get('closure') if isinstance(artifact, dict) else None
    return closure if isinstance(closure, dict) else {}


def ensure_initiative_paths(state_dir: str, initiative: dict | None) -> dict:
    if not isinstance(initiative, dict):
        return {}
    initiative_id = initiative.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return {}
    base = Path(state_dir) / 'initiatives' / initiative_id
    base.mkdir(parents=True, exist_ok=True)
    state_path = base / 'state.json'
    paths = {
        'INITIATIVE_DIR': str(base),
        'INITIATIVE_STATE_PATH': str(state_path),
        'INITIATIVE_BRIEF_PATH': str(base / 'brief.json'),
        'INITIATIVE_PLAN_PATH': str(base / 'plan.json'),
        'INITIATIVE_DECISION_PATH': str(base / 'decision.json'),
    }
    if not state_path.exists():
        seeded = {
            'initiativeId': initiative_id,
            'phase': initiative.get('phase') or 'design-manager',
            'managerBriefPath': paths['INITIATIVE_BRIEF_PATH'],
            'architectPlanPath': paths['INITIATIVE_PLAN_PATH'],
            'managerDecisionPath': paths['INITIATIVE_DECISION_PATH'],
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


def is_terminal_success_phase(phase: object) -> bool:
    return phase in ('completed', 'closed')


def terminal_success_initiative_id(state_dir: str, queue_item: dict | None) -> str | None:
    if not isinstance(queue_item, dict):
        return None
    initiative = queue_item.get('initiative') if isinstance(queue_item.get('initiative'), dict) else None
    if not initiative:
        return None
    initiative_id = initiative.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return None
    state_path = Path(state_dir) / 'initiatives' / initiative_id / 'state.json'
    if not state_path.exists():
        return None
    initiative_state = load_json(state_path, {})
    if is_terminal_success_phase(initiative_state.get('phase')):
        return initiative_id
    return None


def drop_terminal_success_followups(state_dir: str, *, initiative_id: str, keep_ids: set[str] | None = None) -> list[str]:
    keep = {str(x) for x in (keep_ids or set())}
    queue_path = Path(state_dir) / 'queue.json'
    queue = load_json(queue_path, [])
    if not isinstance(queue, list) or not queue:
        return []

    dropped_ids: list[str] = []
    for item in queue:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get('id') or '')
        if item_id in keep:
            continue
        item_initiative = item.get('initiative') if isinstance(item.get('initiative'), dict) else None
        if item_initiative and item_initiative.get('initiativeId') == initiative_id:
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
                and str(item.get('id') or '') not in keep
                and isinstance(item.get('initiative'), dict)
                and item.get('initiative', {}).get('initiativeId') == initiative_id
            )
        ]
        save_json(queue_path, queue)
    return dropped_ids


def build_message(queue_item: dict, result_path: str, handoff_path: str | None = None, *, state_dir: str | None = None) -> str:
    role_prompt = load_role_prompt(str(queue_item.get('role')))
    origin = queue_item.get('origin') if isinstance(queue_item.get('origin'), dict) else {}
    handoff_bits = ''
    if handoff_path:
        handoff_bits = f'HANDOFF_PATH: {handoff_path}\nHANDOFF_HELPER: {ROOT / "agentrunner/scripts/emit_handoff.py"}\n\nIf follow-up developer work is needed, write a structured handoff artifact to HANDOFF_PATH using HANDOFF_HELPER.\n\n'

    reviewer_bits = ''
    if str(queue_item.get('role')) == 'developer':
        source_result_path = origin.get('sourceResultPath')
        source_handoff_path = origin.get('handoffPath')
        review_findings_path = origin.get('reviewFindingsPath')
        lines = []
        if source_result_path:
            lines.append(f'SOURCE_RESULT_PATH: {source_result_path}')
        if source_handoff_path:
            lines.append(f'SOURCE_HANDOFF_PATH: {source_handoff_path}')
        if review_findings_path:
            lines.append(f'REVIEW_FINDINGS_PATH: {review_findings_path}')
        if lines:
            reviewer_bits = '\n'.join(lines) + '\n\n'
            reviewer_bits += (
                'If REVIEW_FINDINGS_PATH or SOURCE_HANDOFF_PATH is present, read those structured reviewer artifacts first before acting.\n'
                'Treat those files as the primary source of reviewer intent; use prose/history only as backup context.\n\n'
            )

    initiative_bits = ''
    if state_dir:
        initiative_paths = ensure_initiative_paths(state_dir, queue_item.get('initiative') if isinstance(queue_item.get('initiative'), dict) else None)
        if initiative_paths and str(queue_item.get('role')) in ('manager', 'architect'):
            lines = [f'{k}: {v}' for k, v in initiative_paths.items()]
            initiative_bits = '\n'.join(lines) + '\n\n'
            if str(queue_item.get('role')) == 'manager':
                initiative_bits += 'If INITIATIVE_BRIEF_PATH or INITIATIVE_DECISION_PATH is relevant to this turn, write the initiative artifact first, then write the normal completion result to RESULT_PATH.\n\n'
            elif str(queue_item.get('role')) == 'architect':
                initiative_bits += 'Read INITIATIVE_BRIEF_PATH first when present, then write the Architect plan artifact to INITIATIVE_PLAN_PATH before writing the normal completion result to RESULT_PATH.\n\n'

    header = (
        'You are running under agentrunner (mechanics-driven).\n'
        'The mechanics layer owns state/queue/logs; you MUST NOT modify them.\n\n'
        f'RESULT_PATH: {result_path}\n'
        f'RESULT_HELPER: {ROOT / "agentrunner/scripts/emit_result.py"}\n\n'
        'When you finish, write the same JSON object from AGENTRUNNER_RESULT_JSON to RESULT_PATH using RESULT_HELPER.\n\n'
        + handoff_bits
        + reviewer_bits
        + initiative_bits
    )
    return header + role_prompt + '\nQUEUE_ITEM_JSON:\n' + json.dumps(queue_item, indent=2, ensure_ascii=False)


def validate_result_artifact(result: object, *, expected_role: str) -> tuple[dict | None, list[str]]:
    if not isinstance(result, dict):
        return None, ['result artifact must be a JSON object']
    normalized = dict(result)
    errors: list[str] = []

    role = normalized.get('role')
    if role is None:
        normalized['role'] = expected_role
        role = expected_role
    if not isinstance(role, str) or role not in VALID_ROLES:
        errors.append(f'invalid role: {role!r}')
    elif role != expected_role:
        errors.append(f'role mismatch: expected {expected_role}, got {role}')

    status = normalized.get('status')
    if not isinstance(status, str) or status not in VALID_STATUSES:
        errors.append(f'invalid status: {status!r}')

    written_at = normalized.get('writtenAt')
    if not isinstance(written_at, str) or parse_iso(written_at) is None:
        errors.append('writtenAt must be a valid ISO timestamp string')

    summary = normalized.get('summary')
    if not isinstance(summary, str) or not summary.strip():
        errors.append('summary must be a non-empty string')

    checks = normalized.get('checks')
    if not isinstance(checks, list):
        errors.append('checks must be a list')
    else:
        for i, check in enumerate(checks):
            if not isinstance(check, dict):
                errors.append(f'checks[{i}] must be an object')
                continue
            if not isinstance(check.get('name'), str) or not check.get('name').strip():
                errors.append(f'checks[{i}].name must be a non-empty string')
            cstatus = check.get('status')
            if not isinstance(cstatus, str) or not cstatus.strip():
                errors.append(f'checks[{i}].status must be a non-empty string')

    if role == 'developer':
        if 'commit' not in normalized:
            errors.append('developer result must include commit (nullable is allowed)')
        elif normalized.get('commit') is not None and not isinstance(normalized.get('commit'), str):
            errors.append('developer commit must be a string or null')
    elif role == 'reviewer':
        if not isinstance(normalized.get('approved'), bool):
            errors.append('reviewer result must include approved as boolean')
        findings = normalized.get('findings')
        if not isinstance(findings, list):
            errors.append('reviewer result must include findings as a list')
        else:
            for i, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    errors.append(f'findings[{i}] must be an object')
    elif role == 'merger':
        if not isinstance(normalized.get('merged'), bool):
            errors.append('merger result must include merged as boolean')
        if 'commit' not in normalized:
            errors.append('merger result must include commit (nullable is allowed)')
        elif normalized.get('commit') is not None and not isinstance(normalized.get('commit'), str):
            errors.append('merger commit must be a string or null')
        if normalized.get('status') == 'blocked' and normalized.get('merged') is False:
            blocker = normalized.get('mergeBlocker')
            if not isinstance(blocker, dict):
                errors.append('blocked merger result must include mergeBlocker object')
            else:
                classification = blocker.get('classification')
                kind = blocker.get('kind')
                if classification not in ('repairable', 'terminal'):
                    errors.append('mergeBlocker.classification must be repairable or terminal')
                if not isinstance(kind, str) or not kind.strip():
                    errors.append('mergeBlocker.kind must be a non-empty string')
                if classification == 'repairable':
                    if kind != 'non_fast_forward':
                        errors.append('repairable merger blockers are limited to non_fast_forward in MVP')
                    passback = blocker.get('passback')
                    if not isinstance(passback, dict):
                        errors.append('repairable merger blocker must include passback object')
                    else:
                        if not isinstance(passback.get('targetRole'), str) or not passback.get('targetRole').strip():
                            errors.append('mergeBlocker.passback.targetRole must be a non-empty string')
                        if not isinstance(passback.get('action'), str) or not passback.get('action').strip():
                            errors.append('mergeBlocker.passback.action must be a non-empty string')
                        if not isinstance(passback.get('reason'), str) or not passback.get('reason').strip():
                            errors.append('mergeBlocker.passback.reason must be a non-empty string')
                        if not isinstance(passback.get('requiresReReview'), bool):
                            errors.append('mergeBlocker.passback.requiresReReview must be boolean')
                        if not isinstance(passback.get('requiresMergeRetry'), bool):
                            errors.append('mergeBlocker.passback.requiresMergeRetry must be boolean')
                if classification == 'terminal' and kind == 'ambiguous_readiness':
                    stop_conditions = blocker.get('stopConditions')
                    if not isinstance(stop_conditions, list) or not [x for x in stop_conditions if isinstance(x, str) and x.strip()]:
                        errors.append('ambiguous_readiness merger blocker must include non-empty stopConditions list')

    request_extra = normalized.get('requestExtraDevTurn', normalized.get('request_extra_dev_turn'))
    if request_extra is not None and not isinstance(request_extra, bool):
        errors.append('requestExtraDevTurn must be a boolean when present')

    return normalized, errors


def validate_handoff_artifact(handoff: object) -> tuple[dict | None, list[str]]:
    if not isinstance(handoff, dict):
        return None, ['handoff artifact must be a JSON object']
    normalized = dict(handoff)
    errors: list[str] = []

    required_string_fields = ['sourceQueueItemId', 'sourceRole', 'targetRole', 'project', 'goal', 'writtenAt']
    for field in required_string_fields:
        value = normalized.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f'{field} must be a non-empty string')
    if isinstance(normalized.get('writtenAt'), str) and parse_iso(normalized.get('writtenAt')) is None:
        errors.append('handoff writtenAt must be a valid ISO timestamp string')
    for field in ['checks', 'findings', 'contextFiles']:
        value = normalized.get(field)
        if not isinstance(value, list):
            errors.append(f'{field} must be a list')
    constraints = normalized.get('constraints')
    if constraints is not None and not isinstance(constraints, dict):
        errors.append('constraints must be an object when present')
    return normalized, errors


def artifact_failure_result(role: str, kind: str, reasons: list[str]) -> dict:
    prefix = {
        'developer': 'Developer ›',
        'reviewer': 'Reviewer ›',
        'manager': 'Manager ›',
        'merger': 'Merger ›',
        'architect': 'Architect ›',
    }.get(role, f'{role.title()} ›')
    top = '; '.join(reasons[:3])
    return {
        'status': 'blocked',
        'role': role,
        'summary': f'{kind} validation failed: {top}',
        'operatorSummary': '\n'.join([
            prefix,
            '- Status: blocked',
            f'- {kind} validation failed',
            f'- {top}',
        ]),
        'writtenAt': iso_now(),
        'checks': [],
        'findings': [],
    }


def materialize_review_findings_artifact(state_dir: str, *, source_queue_item_id: str, result_path: str | None, handoff_path: str | None, findings: list | None, request_reason: str | None) -> str:
    review_dir = Path(state_dir) / 'review_findings'
    review_dir.mkdir(parents=True, exist_ok=True)
    out = review_dir / f'{source_queue_item_id}.json'
    obj = {
        'sourceQueueItemId': source_queue_item_id,
        'sourceResultPath': result_path,
        'sourceHandoffPath': handoff_path,
        'requestReason': request_reason,
        'findings': findings or [],
        'writtenAt': iso_now(),
    }
    save_json(out, obj)
    return str(out)


def build_dev_followup_item(base_item: dict | None, *, project: str, requested_by: str, reason: str | None, findings: list | None,
                            source_result_path: str | None = None, handoff_path: str | None = None, review_findings_path: str | None = None) -> dict:
    now = iso_now()
    suffix = 'followup'
    item_id = f"{requested_by}-{suffix}"
    clean_goal = reason or 'Address reviewer findings and re-run checks.'
    if findings:
        bullet_lines = []
        for f in findings:
            if isinstance(f, dict):
                title = f.get('title') or 'Finding'
                detail = f.get('detail') or ''
                acceptance = f.get('acceptance') or f.get('acceptanceCriteria') or ''
                bit = f"- {title}"
                if detail:
                    bit += f": {detail}"
                if acceptance:
                    if isinstance(acceptance, list):
                        acceptance = '; '.join(str(x) for x in acceptance)
                    bit += f"\n  Acceptance: {acceptance}"
                bullet_lines.append(bit)
        if bullet_lines:
            clean_goal = clean_goal + "\n\nReviewer findings to address:\n" + "\n".join(bullet_lines)

    origin = {
        'requestedBy': requested_by,
        'reason': reason,
        'findings': findings or [],
        'sourceResultPath': source_result_path,
        'handoffPath': handoff_path,
        'reviewFindingsPath': review_findings_path,
    }

    if isinstance(base_item, dict):
        extra_item = dict(base_item)
        extra_item['id'] = item_id
        extra_item['createdAt'] = now
        extra_item['role'] = 'developer'
        extra_item['goal'] = clean_goal
        extra_item['origin'] = origin
        return extra_item

    return {
        'id': item_id,
        'project': project,
        'role': 'developer',
        'createdAt': now,
        'goal': clean_goal,
        'origin': origin,
    }


def _needs_merger_passback_hint(result: dict) -> bool:
    if result.get('status') != 'blocked':
        return False
    if result.get('merged') is not False:
        return False

    checks = result.get('checks') or []
    for check in checks:
        if not isinstance(check, dict):
            continue
        name = str(check.get('name') or '').lower()
        status = str(check.get('status') or '').lower()
        if status != 'blocked':
            continue
        if 'git merge-base --is-ancestor' in name or 'merge-policy ff-only' in name:
            return True

    summary = str(result.get('summary') or '').lower()
    return 'ff-only' in summary or 'fast-forward only' in summary or 'non-fast-forward' in summary


def _merge_blocker(result: dict) -> dict:
    blocker = result.get('mergeBlocker')
    if not isinstance(blocker, dict):
        return {}
    return blocker


def _merger_stop_line(result: dict) -> str | None:
    blocker = _merge_blocker(result)
    if not blocker:
        return None

    detail = blocker.get('detail')
    if isinstance(detail, str) and detail.strip():
        return f'- Detail: {detail.strip()}'

    stop_conditions = blocker.get('stopConditions')
    if isinstance(stop_conditions, list):
        cleaned = [str(item).strip() for item in stop_conditions if isinstance(item, str) and item.strip()]
        if cleaned:
            return f'- Stop conditions: {"; ".join(cleaned[:2])}'

    passback = blocker.get('passback')
    if isinstance(passback, dict):
        action = str(passback.get('action') or '').strip()
        reason = str(passback.get('reason') or '').strip()
        target_role = str(passback.get('targetRole') or '').strip()
        bits = []
        if target_role:
            bits.append(target_role)
        if action:
            bits.append(action)
        if reason:
            bits.append(reason)
        if bits:
            return f'- Passback: {" — ".join(bits[:3])}'

    return None


def format_operator_summary(role: str, result: dict) -> str:
    explicit = result.get('operatorSummary')
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    prefix = {
        'developer': 'Developer ›',
        'reviewer': 'Reviewer ›',
        'manager': 'Manager ›',
        'merger': 'Merger ›',
        'architect': 'Architect ›',
    }.get(role, f'{role.title()} ›')
    lines = [prefix]
    status = result.get('status')
    if status:
        lines.append(f'- Status: {status}')
    summary = result.get('summary')
    if summary:
        lines.append(f'- {summary}')
    if role == 'developer':
        commit = result.get('commit')
        if commit:
            lines.append(f'- Commit: {commit}')
        checks = result.get('checks') or []
        ok = [c.get('name') for c in checks if isinstance(c, dict) and c.get('status') in ('ok', 'passed')]
        if ok:
            lines.append(f'- Checks: {", ".join(ok[:2])} passed')
        if result.get('requestExtraDevTurn') or result.get('request_extra_dev_turn'):
            rr = result.get('requestReason') or result.get('request_reason')
            lines.append(f'- Requested another Dev turn: {rr or "yes"}')
    elif role == 'reviewer':
        approved = result.get('approved')
        if approved is not None:
            lines.append(f'- Approved: {approved}')
        findings = result.get('findings') or []
        if findings:
            top = findings[0]
            if isinstance(top, dict):
                title = top.get('title') or 'Finding'
                lines.append(f'- Top finding: {title}')
                acc = top.get('acceptance') or top.get('acceptanceCriteria')
                if acc:
                    if isinstance(acc, list):
                        acc = '; '.join(str(x) for x in acc)
                    lines.append(f'- Acceptance: {acc}')
        if result.get('requestExtraDevTurn') or result.get('request_extra_dev_turn'):
            rr = result.get('requestReason') or result.get('request_reason')
            lines.append(f'- Follow-up developer work requested{": " + rr if rr else ""}')
    elif role == 'merger':
        merged = result.get('merged')
        if merged is not None:
            lines.append(f'- Merged: {merged}')
        commit = result.get('commit')
        if commit:
            lines.append(f'- Commit: {commit}')
        blocker = _merge_blocker(result)
        if blocker.get('classification') and blocker.get('kind'):
            lines.append(f"- Blocker: {blocker.get('classification')} / {blocker.get('kind')}")
        stop_line = _merger_stop_line(result)
        if stop_line:
            lines.append(stop_line)
        if _needs_merger_passback_hint(result):
            lines.append('- Next step: hand this back to Developer for a rebase/passback fix, then re-review and retry merge')
    return '\n'.join(lines[:6])


def send_operator_summary(channel: str, to: str, role: str, result: dict) -> None:
    msg = format_operator_summary(role, result)
    try:
        gateway_http_invoke('message', {'action': 'send', 'channel': channel, 'target': to, 'message': msg}, action='send')
    except Exception as e:
        debug_log(f'[invoker] failed to send operator summary: {e}')


def finish_current_run(state_dir: str, state: dict, *, cur: dict, status: str, result: dict, role: str, qid: str) -> None:
    if Path(state_dir, 'queue_events.ndjson').exists() and qid:
        append_queue_event(state_dir, 'DONE', id=str(qid), status=str(status))
    append_tick(state_dir, {
        'project': state.get('project'),
        'queueItemId': qid,
        'role': role,
        'status': status,
        'runId': cur.get('runId'),
        'sessionKey': cur.get('sessionKey'),
        'result': result,
        'summary': result.get('summary'),
    })
    if cur.get('announce') and cur.get('channel') and cur.get('to'):
        send_operator_summary(cur.get('channel'), cur.get('to'), str(role), result)
    state['running'] = False
    state['updatedAt'] = iso_now()
    state['lastCompleted'] = {
        'queueItemId': qid,
        'role': role,
        'runId': cur.get('runId'),
        'sessionKey': cur.get('sessionKey'),
        'endedAt': iso_now(),
        'status': status,
        'queueItem': cur.get('queueItem'),
        'resultPath': cur.get('resultPath'),
        'handoffPath': cur.get('handoffPath'),
    }
    state['current'] = None
    save_json(Path(state_dir) / 'state.json', state)
    refresh_operator_status(state_dir)


def poll_completion(state_dir: str, state: dict) -> bool:
    cur = state.get('current') or {}
    result_path = cur.get('resultPath')
    if not result_path or not Path(result_path).exists():
        maybe_send_watchdog(state, cur, channel=cur.get('channel'), to=cur.get('to'))
        if stale_run_should_unlock(cur):
            qid = cur.get('queueItemId')
            role = cur.get('role')
            rec = {
                'project': state.get('project'),
                'queueItemId': qid,
                'role': role,
                'status': 'blocked',
                'runId': cur.get('runId'),
                'sessionKey': cur.get('sessionKey'),
                'result': {'status': 'blocked', 'summary': 'No result artifact produced before stale-run timeout'},
                'summary': 'No result artifact produced before stale-run timeout',
            }
            append_tick(state_dir, rec)
            state['running'] = False
            state['updatedAt'] = iso_now()
            state['lastCompleted'] = {
                'queueItemId': qid,
                'role': role,
                'runId': cur.get('runId'),
                'sessionKey': cur.get('sessionKey'),
                'endedAt': iso_now(),
                'status': 'blocked',
                'queueItem': cur.get('queueItem'),
                'resultPath': cur.get('resultPath'),
                'handoffPath': cur.get('handoffPath'),
            }
            state['current'] = None
            save_json(Path(state_dir) / 'state.json', state)
            refresh_operator_status(state_dir)
            return True
        state['updatedAt'] = iso_now()
        save_json(Path(state_dir) / 'state.json', state)
        refresh_operator_status(state_dir)
        return False

    qid = str(cur.get('queueItemId'))
    role = str(cur.get('role'))

    try:
        raw_result = json.loads(Path(result_path).read_text())
    except Exception as e:
        failure = artifact_failure_result(role, 'result artifact', [f'invalid JSON: {e}'])
        finish_current_run(state_dir, state, cur=cur, status='blocked', result=failure, role=role, qid=qid)
        return True

    result, result_errors = validate_result_artifact(raw_result, expected_role=role)
    if result_errors or result is None:
        failure = artifact_failure_result(role, 'result artifact', result_errors or ['unknown validation failure'])
        finish_current_run(state_dir, state, cur=cur, status='blocked', result=failure, role=role, qid=qid)
        return True

    handoff_path = cur.get('handoffPath')
    handoff_obj = None
    if handoff_path and Path(handoff_path).exists():
        try:
            raw_handoff = json.loads(Path(handoff_path).read_text())
        except Exception as e:
            failure = artifact_failure_result(role, 'handoff artifact', [f'invalid JSON: {e}'])
            finish_current_run(state_dir, state, cur=cur, status='blocked', result=failure, role=role, qid=qid)
            return True
        handoff_obj, handoff_errors = validate_handoff_artifact(raw_handoff)
        if handoff_errors or handoff_obj is None:
            failure = artifact_failure_result(role, 'handoff artifact', handoff_errors or ['unknown validation failure'])
            finish_current_run(state_dir, state, cur=cur, status='blocked', result=failure, role=role, qid=qid)
            return True

    request_extra = result.get('requestExtraDevTurn', result.get('request_extra_dev_turn'))
    request_reason = result.get('requestReason', result.get('request_reason'))
    if role == 'reviewer' and request_extra and handoff_path and handoff_obj is None:
        failure = artifact_failure_result(role, 'handoff artifact', ['reviewer requested follow-up developer work but no valid handoff artifact was produced'])
        finish_current_run(state_dir, state, cur=cur, status='blocked', result=failure, role=role, qid=qid)
        return True

    emit_initiative_status_update(state_dir, queue_item=cur.get('queueItem'), result=result)

    status = str(result.get('status', 'ok'))
    finish_current_run(state_dir, state, cur=cur, status=status, result=result, role=role, qid=qid)

    terminal_initiative_id = terminal_success_initiative_id(state_dir, cur.get('queueItem'))
    if terminal_initiative_id:
        drop_terminal_success_followups(state_dir, initiative_id=terminal_initiative_id)
        return True

    if handoff_obj is not None:
        review_findings_path = materialize_review_findings_artifact(
            state_dir,
            source_queue_item_id=qid,
            result_path=result_path,
            handoff_path=handoff_path,
            findings=handoff_obj.get('findings', []),
            request_reason=request_reason,
        )
        extra_item = {
            'id': f"{qid}-followup-1",
            'project': handoff_obj.get('project', state.get('project')),
            'role': handoff_obj.get('targetRole', 'developer'),
            'createdAt': iso_now(),
            'repo_path': handoff_obj.get('repoPath'),
            'branch': handoff_obj.get('branch'),
            'base': handoff_obj.get('base'),
            'goal': handoff_obj.get('goal'),
            'checks': handoff_obj.get('checks', []),
            'constraints': handoff_obj.get('constraints', {}),
            'contextFiles': handoff_obj.get('contextFiles', []),
            'initiative': dict(cur.get('queueItem', {}).get('initiative') or {}) if isinstance(cur.get('queueItem', {}).get('initiative'), dict) else None,
            'origin': {
                'requestedBy': qid,
                'handoffPath': handoff_path,
                'sourceResultPath': result_path,
                'reviewFindingsPath': review_findings_path,
                'findings': handoff_obj.get('findings', []),
            },
        }
        if Path(state_dir, 'queue_events.ndjson').exists():
            append_queue_event(state_dir, 'INSERT_FRONT', item=extra_item)
        else:
            q = load_json(Path(state_dir) / 'queue.json', [])
            q.insert(0, extra_item)
            save_json(Path(state_dir) / 'queue.json', q)
        state = load_json(Path(state_dir) / 'state.json', state)
        state.setdefault('runtime', {})['extraDevTurnsUsed'] = int((state.get('runtime') or {}).get('extraDevTurnsUsed') or 0) + 1
        save_json(Path(state_dir) / 'state.json', state)
        refresh_operator_status(state_dir)
    elif request_extra:
        used = int((state.get('runtime') or {}).get('extraDevTurnsUsed') or 0)
        max_extra = int((state.get('limits') or {}).get('maxExtraDevTurns') or 1)
        if used < max_extra:
            base_item = cur.get('queueItem')
            findings = result.get('findings') if isinstance(result, dict) else None
            review_findings_path = materialize_review_findings_artifact(
                state_dir,
                source_queue_item_id=qid,
                result_path=result_path,
                handoff_path=handoff_path,
                findings=findings if isinstance(findings, list) else [],
                request_reason=request_reason,
            )
            extra_item = build_dev_followup_item(
                base_item,
                project=state.get('project'),
                requested_by=str(qid),
                reason=request_reason if isinstance(result, dict) else None,
                findings=findings if isinstance(findings, list) else None,
                source_result_path=result_path,
                handoff_path=handoff_path,
                review_findings_path=review_findings_path,
            )
            if Path(state_dir, 'queue_events.ndjson').exists():
                append_queue_event(state_dir, 'INSERT_FRONT', item=extra_item)
            else:
                q = load_json(Path(state_dir) / 'queue.json', [])
                q.insert(0, extra_item)
                save_json(Path(state_dir) / 'queue.json', q)
            state = load_json(Path(state_dir) / 'state.json', state)
            state.setdefault('runtime', {})['extraDevTurnsUsed'] = used + 1
            save_json(Path(state_dir) / 'state.json', state)
            refresh_operator_status(state_dir)

    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True)
    ap.add_argument('--state-dir', required=True)
    ap.add_argument('--announce', action='store_true')
    ap.add_argument('--channel', default='discord')
    ap.add_argument('--to', default='')
    ap.add_argument('--timeout-seconds', type=int, default=540)
    args = ap.parse_args()

    state_dir = args.state_dir
    state_path = Path(state_dir) / 'state.json'
    queue_path = Path(state_dir) / 'queue.json'
    results_dir = Path(state_dir) / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)

    materialize_queue(state_dir)
    state = load_json(state_path, {'project': args.project, 'running': False, 'updatedAt': iso_now(), 'current': None, 'limits': {'maxExtraDevTurns': 1}, 'policy': {'extraDevTurnReset': 'on_branch_change'}, 'runtime': {'extraDevTurnsUsed': 0, 'lastBranch': None}})

    if state.get('running') and state.get('current'):
        poll_completion(state_dir, state)
        run_initiative_coordinator(state_dir)
        refresh_operator_status(state_dir)
        return 0

    queue = load_json(queue_path, [])
    if not queue:
        closure = current_closure_snapshot(state_dir)
        if closure.get('handoffSafe') is False:
            changed = run_initiative_coordinator(state_dir)
            if changed:
                state = load_json(state_path, state)
                queue = load_json(queue_path, [])
        if not queue:
            state['updatedAt'] = iso_now()
            save_json(state_path, state)
            refresh_operator_status(state_dir)
            return 0

    item = queue[0]
    qid = str(item.get('id'))
    state.setdefault('runtime', {})
    state.setdefault('policy', {})
    reset_policy = state['policy'].get('extraDevTurnReset', 'on_branch_change')
    item_role = str(item.get('role'))
    item_branch = item.get('branch')
    last_branch = state['runtime'].get('lastBranch')
    should_reset = (reset_policy == 'on_non_dev' and item_role != 'developer') or (reset_policy == 'on_branch_change' and item_branch != last_branch) or (reset_policy == 'on_review_start' and item_role == 'reviewer')
    if should_reset:
        state['runtime']['extraDevTurnsUsed'] = 0

    session_key = f"hook:agentrunner:{args.project}:{qid}"
    result_path = str(results_dir / f"{qid}.json")
    handoff_path = str(Path(state_dir) / 'handoffs' / f"{qid}.json") if str(item.get('role')) == 'reviewer' else None
    payload = {'message': build_message(item, result_path, handoff_path, state_dir=state_dir), 'name': f"agentrunner:{args.project}:{item.get('role')}:{qid}", 'sessionKey': session_key, 'wakeMode': 'now', 'deliver': False, 'channel': args.channel, 'to': args.to, 'timeoutSeconds': args.timeout_seconds}
    resp = hooks_agent(payload)
    if not resp.get('ok'):
        raise RuntimeError(f"hooks agent failed: {resp}")
    run_id = resp.get('runId')

    queue.pop(0)
    if Path(state_dir, 'queue_events.ndjson').exists():
        append_queue_event(state_dir, 'DEQUEUE', id=qid)
    state['runtime']['lastBranch'] = item_branch
    state['running'] = True
    state['updatedAt'] = iso_now()
    state['current'] = {
        'queueItemId': qid,
        'role': item.get('role'),
        'queueItem': item,
        'runId': run_id,
        'sessionKey': session_key,
        'startedAt': iso_now(),
        'resultPath': result_path,
        'handoffPath': handoff_path,
        'announce': bool(args.announce),
        'channel': args.channel,
        'to': args.to,
    }
    save_json(queue_path, queue)
    save_json(state_path, state)
    refresh_operator_status(state_dir)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
