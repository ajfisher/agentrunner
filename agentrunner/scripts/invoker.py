#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, subprocess, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/openclaw/projects/agentrunner')
CONFIG_PATH = Path('/home/openclaw/.openclaw/openclaw.json')


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


def build_message(queue_item: dict, result_path: str) -> str:
    role_prompt = load_role_prompt(str(queue_item.get('role')))
    header = (
        'You are running under agentrunner (mechanics-driven).\n'
        'The mechanics layer owns state/queue/logs; you MUST NOT modify them.\n\n'
        f'RESULT_PATH: {result_path}\n'
        f'RESULT_HELPER: {ROOT / "agentrunner/scripts/write_result.py"}\n\n'
        'When you finish, write the same JSON object from AGENTRUNNER_RESULT_JSON to RESULT_PATH using RESULT_HELPER.\n\n'
    )
    return header + role_prompt + '\nQUEUE_ITEM_JSON:\n' + json.dumps(queue_item, indent=2, ensure_ascii=False)


def build_dev_followup_item(base_item: dict | None, *, project: str, requested_by: str, reason: str | None, findings: list | None) -> dict:
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
                acceptance = f.get('acceptance') or ''
                bit = f"- {title}"
                if detail:
                    bit += f": {detail}"
                if acceptance:
                    bit += f"\n  Acceptance: {acceptance}"
                bullet_lines.append(bit)
        if bullet_lines:
            clean_goal = clean_goal + "\n\nReviewer findings to address:\n" + "\n".join(bullet_lines)

    if isinstance(base_item, dict):
        extra_item = dict(base_item)
        extra_item['id'] = item_id
        extra_item['createdAt'] = now
        extra_item['role'] = 'developer'
        extra_item['goal'] = clean_goal
        extra_item['origin'] = {'requestedBy': requested_by, 'reason': reason, 'findings': findings or []}
        # Ensure dev follow-up uses dev-friendly checks if present; otherwise preserve existing checks.
        return extra_item

    return {
        'id': item_id,
        'project': project,
        'role': 'developer',
        'createdAt': now,
        'goal': clean_goal,
        'origin': {'requestedBy': requested_by, 'reason': reason, 'findings': findings or []},
    }


def poll_completion(state_dir: str, state: dict) -> bool:
    cur = state.get('current') or {}
    result_path = cur.get('resultPath')
    if not result_path or not Path(result_path).exists():
        state['updatedAt'] = iso_now()
        save_json(Path(state_dir) / 'state.json', state)
        return False
    result = json.loads(Path(result_path).read_text())
    qid = cur.get('queueItemId')
    role = cur.get('role')
    status = result.get('status', 'ok')
    if Path(state_dir, 'queue_events.ndjson').exists() and qid:
        append_queue_event(state_dir, 'DONE', id=str(qid), status=str(status))
    append_tick(state_dir, {
        'project': state.get('project'), 'queueItemId': qid, 'role': role,
        'status': status, 'runId': cur.get('runId'), 'sessionKey': cur.get('sessionKey'),
        'result': result, 'summary': result.get('summary')
    })
    if result.get('request_extra_dev_turn'):
        used = int((state.get('runtime') or {}).get('extraDevTurnsUsed') or 0)
        max_extra = int((state.get('limits') or {}).get('maxExtraDevTurns') or 1)
        if used < max_extra:
            base_item = cur.get('queueItem')
            extra_id = f"{qid}-extra-{used+1}"
            if isinstance(base_item, dict):
                extra_item = dict(base_item)
                extra_item['id'] = extra_id
                extra_item['createdAt'] = iso_now()
                extra_item['origin'] = {'requestedBy': qid, 'reason': result.get('request_reason')}
                orig_goal = extra_item.get('goal')
                extra_item['goal'] = f"(extra dev turn) {result.get('request_reason')}\\n\\nORIGINAL_GOAL: {orig_goal}"
                extra_item['role'] = 'developer'
            else:
                extra_item = {'id': extra_id, 'project': state.get('project'), 'role': 'developer', 'createdAt': iso_now(), 'goal': f"Extra dev turn requested: {result.get('request_reason')}"}
            if Path(state_dir, 'queue_events.ndjson').exists():
                append_queue_event(state_dir, 'INSERT_FRONT', item=extra_item)
            else:
                q = load_json(Path(state_dir) / 'queue.json', [])
                q.insert(0, extra_item)
                save_json(Path(state_dir) / 'queue.json', q)
            state.setdefault('runtime', {})['extraDevTurnsUsed'] = used + 1
    state['running'] = False
    state['updatedAt'] = iso_now()
    state['lastCompleted'] = {'queueItemId': qid, 'role': role, 'runId': cur.get('runId'), 'sessionKey': cur.get('sessionKey'), 'endedAt': iso_now(), 'status': status}
    state['current'] = None
    save_json(Path(state_dir) / 'state.json', state)
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
        return 0

    queue = load_json(queue_path, [])
    if not queue:
        state['updatedAt'] = iso_now()
        save_json(state_path, state)
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
    payload = {'message': build_message(item, result_path), 'name': f"agentrunner:{args.project}:{item.get('role')}:{qid}", 'sessionKey': session_key, 'wakeMode': 'now', 'deliver': bool(args.announce), 'channel': args.channel, 'to': args.to, 'timeoutSeconds': args.timeout_seconds}
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
    state['current'] = {'queueItemId': qid, 'role': item.get('role'), 'queueItem': item, 'runId': run_id, 'sessionKey': session_key, 'startedAt': iso_now(), 'resultPath': result_path}
    save_json(queue_path, queue)
    save_json(state_path, state)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
