#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tomllib


PROJECT_CONFIG_PATH = 'pyproject.toml'


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
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def clip(value: object, limit: int = 160) -> str | None:
    if value is None:
        return None
    text = ' '.join(str(value).strip().split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + '…'


def normalize_github_config(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    enabled = raw.get('enabled')
    if enabled is not True:
        return None
    owner = raw.get('owner')
    repo = raw.get('repo')
    if not isinstance(owner, str) or not owner.strip():
        return None
    if not isinstance(repo, str) or not repo.strip():
        return None
    cfg: dict[str, Any] = {
        'enabled': True,
        'owner': owner.strip(),
        'repo': repo.strip(),
    }
    base_url = raw.get('baseUrl')
    if isinstance(base_url, str) and base_url.strip():
        cfg['baseUrl'] = base_url.strip()
    return cfg


def load_project_github_config(repo_path: str | Path) -> dict[str, Any] | None:
    repo_root = Path(repo_path)
    pyproject = repo_root / PROJECT_CONFIG_PATH
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    tool = data.get('tool') if isinstance(data, dict) else None
    agentrunner = tool.get('agentrunner') if isinstance(tool, dict) else None
    github = agentrunner.get('github') if isinstance(agentrunner, dict) else None
    return normalize_github_config(github)


def _gh_hostname(config: dict[str, Any]) -> str | None:
    base_url = config.get('baseUrl')
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    parsed = urlparse(base_url)
    if parsed.hostname:
        return parsed.hostname
    if '://' not in base_url and '/' not in base_url:
        return base_url.strip()
    return None


def _gh_env(config: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    host = _gh_hostname(config)
    if host:
        env.setdefault('GH_HOST', host)
    return env


def _run_gh(repo_path: str | Path, config: dict[str, Any], args: list[str]) -> Any:
    repo_spec = f"{config['owner']}/{config['repo']}"
    cmd = ['gh'] + args + ['--repo', repo_spec]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_path),
        env=_gh_env(config),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip()
        stdout = (proc.stdout or '').strip()
        detail = stderr or stdout or f'gh exited {proc.returncode}'
        raise RuntimeError(detail)
    raw = (proc.stdout or '').strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'gh returned non-JSON output: {raw}') from exc


def build_issue_handle(config: dict[str, Any], number: object) -> str | None:
    if isinstance(number, int):
        return f"{config['owner']}/{config['repo']}#{number}"
    return None


def build_pull_request_handle(config: dict[str, Any], number: object) -> str | None:
    if isinstance(number, int):
        return f"{config['owner']}/{config['repo']}#PR{number}"
    return None


def _normalize_number(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def issue_marker(initiative_id: str) -> str:
    return f'Initiative ID: {initiative_id}'


def _status_line(label: str, value: object) -> str | None:
    text = clip(value, 160)
    if not text:
        return None
    return f'- **{label}:** {text}'


def build_issue_body(*, initiative_id: str, brief: dict[str, Any], initiative_state: dict[str, Any]) -> str:
    lines: list[str] = [
        f'# {brief.get("title") or initiative_id}',
        '',
        f'Initiative ID: {initiative_id}',
        '',
        '## Objective',
        str(brief.get('objective') or '').strip(),
    ]

    desired = brief.get('desiredOutcomes') if isinstance(brief.get('desiredOutcomes'), list) else []
    if desired:
        lines += ['', '## Desired outcomes']
        lines.extend(f'- {str(item).strip()}' for item in desired if str(item).strip())

    done = brief.get('definitionOfDone') if isinstance(brief.get('definitionOfDone'), list) else []
    if done:
        lines += ['', '## Definition of done']
        lines.extend(f'- {str(item).strip()}' for item in done if str(item).strip())

    branch = initiative_state.get('branch')
    base = initiative_state.get('base')
    if isinstance(branch, str) and branch.strip():
        lines += ['', f'Branch: `{branch}`']
    if isinstance(base, str) and base.strip():
        lines.append(f'Base: `{base}`')

    github_mirror = initiative_state.get('githubMirror') if isinstance(initiative_state.get('githubMirror'), dict) else {}
    lifecycle = github_mirror.get('lifecycle') if isinstance(github_mirror.get('lifecycle'), dict) else {}
    degraded = github_mirror.get('degradedSync') if isinstance(github_mirror.get('degradedSync'), dict) else {}

    pull_request = github_mirror.get('pullRequest') if isinstance(github_mirror.get('pullRequest'), dict) else {}

    status_lines = [
        _status_line('Lifecycle', lifecycle.get('event')),
        _status_line('Phase', initiative_state.get('phase')),
        _status_line('Current subtask', initiative_state.get('currentSubtaskId') or '-'),
        _status_line('Summary', lifecycle.get('summary')),
        _status_line('Queue item', lifecycle.get('queueItemId')),
        _status_line('Role', lifecycle.get('role')),
        _status_line('Result', lifecycle.get('resultStatus')),
        _status_line('Commit', lifecycle.get('commit')),
        _status_line('Pull request', pull_request.get('handle') or pull_request.get('url')),
        _status_line('Blocked reason', lifecycle.get('blockedReason')),
        _status_line('Updated', lifecycle.get('writtenAt') or github_mirror.get('lastSyncAt')),
    ]
    status_lines = [line for line in status_lines if line]
    if status_lines:
        lines += ['', '## Current status']
        lines.extend(status_lines)

    if degraded:
        degraded_lines = [
            _status_line('State', degraded.get('status')),
            _status_line('Reason', degraded.get('reason')),
            _status_line('Summary', degraded.get('summary')),
            _status_line('First seen', degraded.get('firstSeenAt')),
            _status_line('Last seen', degraded.get('lastSeenAt')),
            _status_line('Last attempt', degraded.get('lastAttemptAt')),
        ]
        degraded_lines = [line for line in degraded_lines if line]
        if degraded_lines:
            lines += ['', '## Sync health']
            lines.extend(degraded_lines)

    return '\n'.join(lines).strip() + '\n'


def normalize_pull_request_record(config: dict[str, Any], payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    number = payload.get('number')
    if isinstance(number, str) and number.isdigit():
        number = int(number)
    if not isinstance(number, int):
        return None
    pull_request: dict[str, Any] = {
        'number': number,
        'handle': build_pull_request_handle(config, number),
    }
    for field in ('id', 'url', 'state', 'title'):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            pull_request[field] = value.strip()
    head_ref = payload.get('headRefName')
    if isinstance(head_ref, str) and head_ref.strip():
        pull_request['headRef'] = head_ref.strip()
    base_ref = payload.get('baseRefName')
    if isinstance(base_ref, str) and base_ref.strip():
        pull_request['baseRef'] = base_ref.strip()
    return pull_request


def _should_sync_pull_request(*, lifecycle_event: str, initiative_state: dict[str, Any], queue_item: dict[str, Any] | None = None, result: dict[str, Any] | None = None) -> bool:
    queue_item = queue_item if isinstance(queue_item, dict) else {}
    result = result if isinstance(result, dict) else {}
    phase = str(initiative_state.get('phase') or '').strip()
    role = str(queue_item.get('role') or '').strip()

    if lifecycle_event == 'merge_completed' and role == 'merger' and result.get('merged') is True:
        return True
    if lifecycle_event == 'merge_blocked' and role == 'merger' and result.get('status') == 'blocked' and result.get('merged') is False:
        return True
    if lifecycle_event == 'initiative_phase_changed' and phase == 'closure-merger':
        return True
    return False


LIFECYCLE_PR_COMMENT_EVENTS = {
    'review_approved',
    'review_blocked',
    'remediation_queued',
    'merge_blocked',
    'merge_completed',
}


def resolve_lifecycle_comment_target(*, lifecycle_event: str, github_mirror: dict[str, Any]) -> dict[str, Any] | None:
    issue = github_mirror.get('issue') if isinstance(github_mirror.get('issue'), dict) else None
    pull_request = github_mirror.get('pullRequest') if isinstance(github_mirror.get('pullRequest'), dict) else None
    has_pull_request = isinstance(pull_request, dict) and _normalize_number(pull_request.get('number')) is not None

    if has_pull_request and lifecycle_event in LIFECYCLE_PR_COMMENT_EVENTS:
        return {
            'kind': 'pull_request',
            'number': _normalize_number(pull_request.get('number')),
            'handle': pull_request.get('handle') or pull_request.get('url'),
        }

    if isinstance(issue, dict):
        issue_number = _normalize_number(issue.get('number'))
        if issue_number is not None:
            return {
                'kind': 'issue',
                'number': issue_number,
                'handle': issue.get('handle') or issue.get('url'),
            }

    if has_pull_request:
        return {
            'kind': 'pull_request',
            'number': _normalize_number(pull_request.get('number')),
            'handle': pull_request.get('handle') or pull_request.get('url'),
        }

    return None


def _build_lifecycle_comment_projection(*, lifecycle_event: str, initiative_state: dict[str, Any], summary: str | None = None, queue_item: dict[str, Any] | None = None, result: dict[str, Any] | None = None, blocked_reason: str | None = None) -> dict[str, Any]:
    queue_item = queue_item if isinstance(queue_item, dict) else {}
    result = result if isinstance(result, dict) else {}
    return {
        'event': lifecycle_event,
        'phase': clip(initiative_state.get('phase'), 64),
        'currentSubtaskId': clip(initiative_state.get('currentSubtaskId') or '-', 96),
        'summary': clip(summary, 240),
        'queueItemId': clip(queue_item.get('id') or queue_item.get('queueItemId'), 96),
        'role': clip(queue_item.get('role'), 48),
        'resultStatus': clip(result.get('status'), 32),
        'commit': clip(result.get('commit'), 16),
        'blockedReason': clip(blocked_reason, 240),
    }


def _build_lifecycle_comment_body(payload: dict[str, Any]) -> str:
    lines = [f"Lifecycle update: {payload.get('event') or 'status_update'}"]
    summary = payload.get('summary')
    if summary:
        lines += ['', str(summary)]

    facts = [
        _status_line('Phase', payload.get('phase')),
        _status_line('Current subtask', payload.get('currentSubtaskId')),
        _status_line('Queue item', payload.get('queueItemId')),
        _status_line('Role', payload.get('role')),
        _status_line('Result', payload.get('resultStatus')),
        _status_line('Commit', payload.get('commit')),
        _status_line('Blocked reason', payload.get('blockedReason')),
    ]
    facts = [line for line in facts if line]
    if facts:
        lines += ['', 'Details:']
        lines.extend(facts)
    return '\n'.join(lines).strip() + '\n'


def _comment_sync_digest(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _lifecycle_comment_retry_pending(*, github_mirror: dict[str, Any], lifecycle_event: str, initiative_state: dict[str, Any], summary: str | None = None, queue_item: dict[str, Any] | None = None, result: dict[str, Any] | None = None, blocked_reason: str | None = None) -> bool:
    target = resolve_lifecycle_comment_target(lifecycle_event=lifecycle_event, github_mirror=github_mirror)
    if not target:
        return False

    comment_payload = _build_lifecycle_comment_projection(
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item=queue_item,
        result=result,
        blocked_reason=blocked_reason,
    )
    digest = _comment_sync_digest(comment_payload)
    comment_sync = github_mirror.get('commentSync') if isinstance(github_mirror.get('commentSync'), dict) else {}
    return not (
        comment_sync.get('lastDigest') == digest
        and comment_sync.get('lastTargetKind') == target.get('kind')
        and comment_sync.get('lastTargetNumber') == target.get('number')
    )


def _sync_lifecycle_comment(*, repo_path: str | Path, config: dict[str, Any], github_mirror: dict[str, Any], lifecycle_event: str, initiative_state: dict[str, Any], summary: str | None = None, queue_item: dict[str, Any] | None = None, result: dict[str, Any] | None = None, blocked_reason: str | None = None) -> dict[str, Any] | None:
    target = resolve_lifecycle_comment_target(lifecycle_event=lifecycle_event, github_mirror=github_mirror)
    if not target:
        return None

    comment_payload = _build_lifecycle_comment_projection(
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item=queue_item,
        result=result,
        blocked_reason=blocked_reason,
    )
    digest = _comment_sync_digest(comment_payload)
    comment_sync = github_mirror.get('commentSync') if isinstance(github_mirror.get('commentSync'), dict) else {}
    if not _lifecycle_comment_retry_pending(
        github_mirror=github_mirror,
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item=queue_item,
        result=result,
        blocked_reason=blocked_reason,
    ):
        return comment_sync

    now = iso_now()
    body = _build_lifecycle_comment_body(comment_payload)
    comment: dict[str, Any] = dict(comment_sync)
    comment.update(
        {
            'lastAttemptAt': now,
            'lastEvent': lifecycle_event,
            'lastAttemptDigest': digest,
            'lastAttemptTargetKind': target.get('kind'),
            'lastAttemptTargetNumber': target.get('number'),
            'lastAttemptTargetHandle': target.get('handle'),
        }
    )
    github_mirror['commentSync'] = comment

    created = _run_gh(
        repo_path,
        config,
        [
            'api',
            f"repos/{config['owner']}/{config['repo']}/issues/{target['number']}/comments",
            '--method',
            'POST',
            '-f',
            f'body={body}',
        ],
    )

    comment['lastSuccessAt'] = now
    comment['lastDigest'] = digest
    comment['lastTargetKind'] = target.get('kind')
    comment['lastTargetNumber'] = target.get('number')
    comment['lastTargetHandle'] = target.get('handle')
    if isinstance(created, dict):
        comment_id = created.get('id')
        if isinstance(comment_id, int):
            comment['lastCommentId'] = str(comment_id)
        elif isinstance(comment_id, str) and comment_id.strip():
            comment['lastCommentId'] = comment_id.strip()
        comment_url = created.get('url')
        if isinstance(comment_url, str) and comment_url.strip():
            comment['lastCommentUrl'] = comment_url.strip()
    github_mirror['commentSync'] = comment
    return comment


def reconcile_remote_pull_request(*, repo_path: str | Path, config: dict[str, Any], initiative_id: str, brief: dict[str, Any], initiative_state: dict[str, Any]) -> dict[str, Any]:
    mirror = initiative_state.get('githubMirror') if isinstance(initiative_state.get('githubMirror'), dict) else {}
    existing_pull_request = mirror.get('pullRequest') if isinstance(mirror.get('pullRequest'), dict) else {}

    pr_number = existing_pull_request.get('number')
    if isinstance(pr_number, str) and pr_number.isdigit():
        pr_number = int(pr_number)
    if isinstance(pr_number, int):
        viewed = _run_gh(repo_path, config, ['pr', 'view', str(pr_number), '--json', 'id,number,url,state,title,headRefName,baseRefName'])
        pull_request = normalize_pull_request_record(config, viewed)
        if pull_request is not None:
            return pull_request

    branch = initiative_state.get('branch')
    base = initiative_state.get('base')
    if not isinstance(branch, str) or not branch.strip() or not isinstance(base, str) or not base.strip():
        raise RuntimeError('cannot mirror pull request without initiative branch/base refs')

    matches = _run_gh(
        repo_path,
        config,
        ['pr', 'list', '--state', 'all', '--head', branch, '--base', base, '--json', 'id,number,url,state,title,headRefName,baseRefName'],
    )
    if isinstance(matches, list) and matches:
        normalized = [normalize_pull_request_record(config, item) for item in matches]
        candidates = [item for item in normalized if item is not None]
        if candidates:
            candidates.sort(key=lambda item: int(item['number']))
            return candidates[0]

    title = str(brief.get('title') or initiative_id)
    created = _run_gh(
        repo_path,
        config,
        [
            'api',
            f"repos/{config['owner']}/{config['repo']}/pulls",
            '--method',
            'POST',
            '-f',
            f'title={title}',
            '-f',
            f'body={build_issue_body(initiative_id=initiative_id, brief=brief, initiative_state=initiative_state)}',
            '-f',
            f'head={branch}',
            '-f',
            f'base={base}',
        ],
    )
    pull_request = normalize_pull_request_record(config, created)
    if pull_request is None:
        raise RuntimeError('GitHub pull request create did not return a usable pull request payload')
    return pull_request


def normalize_issue_record(config: dict[str, Any], payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    number = payload.get('number')
    if isinstance(number, str) and number.isdigit():
        number = int(number)
    if not isinstance(number, int):
        return None
    issue: dict[str, Any] = {
        'number': number,
        'handle': build_issue_handle(config, number),
    }
    for field in ('id', 'url', 'state', 'title'):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            issue[field] = value.strip()
    return issue


def reconcile_remote_issue(*, repo_path: str | Path, config: dict[str, Any], initiative_id: str, brief: dict[str, Any], initiative_state: dict[str, Any]) -> dict[str, Any]:
    mirror = initiative_state.get('githubMirror') if isinstance(initiative_state.get('githubMirror'), dict) else {}
    existing_issue = mirror.get('issue') if isinstance(mirror.get('issue'), dict) else {}

    issue_number = existing_issue.get('number')
    if isinstance(issue_number, str) and issue_number.isdigit():
        issue_number = int(issue_number)
    if isinstance(issue_number, int):
        viewed = _run_gh(repo_path, config, ['issue', 'view', str(issue_number), '--json', 'id,number,url,state,title'])
        issue = normalize_issue_record(config, viewed)
        if issue is not None:
            return issue

    matches = _run_gh(
        repo_path,
        config,
        ['issue', 'list', '--state', 'all', '--search', issue_marker(initiative_id), '--json', 'id,number,url,state,title'],
    )
    if isinstance(matches, list) and matches:
        normalized = [normalize_issue_record(config, item) for item in matches]
        candidates = [item for item in normalized if item is not None]
        if candidates:
            candidates.sort(key=lambda item: int(item['number']))
            return candidates[0]

    created = _run_gh(
        repo_path,
        config,
        [
            'api',
            f"repos/{config['owner']}/{config['repo']}/issues",
            '--method',
            'POST',
            '-f',
            f"title={str(brief.get('title') or initiative_id)}",
            '-f',
            f"body={build_issue_body(initiative_id=initiative_id, brief=brief, initiative_state=initiative_state)}",
        ],
    )
    issue = normalize_issue_record(config, created)
    if issue is None:
        raise RuntimeError('GitHub issue create did not return a usable issue payload')
    return issue


def _record_degraded_sync(github_mirror: dict[str, Any], *, now: str, reason: str, summary: str) -> None:
    degraded = github_mirror.get('degradedSync') if isinstance(github_mirror.get('degradedSync'), dict) else {}
    first_seen = degraded.get('firstSeenAt') if isinstance(degraded.get('firstSeenAt'), str) and degraded.get('firstSeenAt').strip() else now
    github_mirror['degradedSync'] = {
        'status': 'degraded',
        'reason': reason,
        'summary': clip(summary, 240),
        'firstSeenAt': first_seen,
        'lastSeenAt': now,
        'lastAttemptAt': now,
    }


def _clear_degraded_sync(github_mirror: dict[str, Any]) -> None:
    github_mirror.pop('degradedSync', None)


def sync_manager_kickoff_issue(*, repo_path: str | Path, initiative_state_path: str | Path) -> dict[str, Any] | None:
    repo_root = Path(repo_path)
    config = load_project_github_config(repo_root)
    if config is None:
        return None

    state_path = Path(initiative_state_path)
    initiative_state = load_json(state_path, {})
    if not isinstance(initiative_state, dict):
        return None
    initiative_id = initiative_state.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return None

    brief_path = initiative_state.get('managerBriefPath')
    brief = load_json(brief_path, {}) if brief_path else {}
    if not isinstance(brief, dict):
        brief = {}

    now = iso_now()
    github_mirror = initiative_state.get('githubMirror') if isinstance(initiative_state.get('githubMirror'), dict) else {}
    github_mirror['config'] = dict(config)

    try:
        issue = reconcile_remote_issue(
            repo_path=repo_root,
            config=config,
            initiative_id=initiative_id,
            brief=brief,
            initiative_state=initiative_state,
        )
    except Exception as exc:
        _record_degraded_sync(
            github_mirror,
            now=now,
            reason='issue_sync_failed',
            summary=f'GitHub initiative issue sync failed during manager kickoff: {exc}',
        )
        initiative_state['githubMirror'] = github_mirror
        save_json(state_path, initiative_state)
        return github_mirror

    github_mirror['issue'] = issue
    github_mirror['lastSyncAt'] = now
    _clear_degraded_sync(github_mirror)
    initiative_state['githubMirror'] = github_mirror
    save_json(state_path, initiative_state)
    return github_mirror


def _build_lifecycle_projection(*, lifecycle_event: str, initiative_state: dict[str, Any], summary: str | None = None, queue_item: dict[str, Any] | None = None, result: dict[str, Any] | None = None, blocked_reason: str | None = None) -> dict[str, Any]:
    queue_item = queue_item if isinstance(queue_item, dict) else {}
    result = result if isinstance(result, dict) else {}
    return {
        'event': lifecycle_event,
        'phase': clip(initiative_state.get('phase'), 64),
        'currentSubtaskId': clip(initiative_state.get('currentSubtaskId') or '-', 96),
        'summary': clip(summary, 240),
        'queueItemId': clip(queue_item.get('id') or queue_item.get('queueItemId'), 96),
        'role': clip(queue_item.get('role'), 48),
        'resultStatus': clip(result.get('status'), 32),
        'commit': clip(result.get('commit'), 16),
        'blockedReason': clip(blocked_reason, 240),
        'writtenAt': iso_now(),
    }


def _lifecycle_digest(payload: dict[str, Any]) -> str:
    comparable = {k: v for k, v in payload.items() if k != 'writtenAt'}
    return json.dumps(comparable, sort_keys=True, ensure_ascii=False)


def sync_lifecycle_issue_update(*, repo_path: str | Path, initiative_state_path: str | Path, lifecycle_event: str, summary: str | None = None, queue_item: dict[str, Any] | None = None, result: dict[str, Any] | None = None, blocked_reason: str | None = None) -> dict[str, Any] | None:
    repo_root = Path(repo_path)
    config = load_project_github_config(repo_root)
    if config is None:
        return None

    state_path = Path(initiative_state_path)
    initiative_state = load_json(state_path, {})
    if not isinstance(initiative_state, dict):
        return None
    initiative_id = initiative_state.get('initiativeId')
    if not isinstance(initiative_id, str) or not initiative_id.strip():
        return None

    brief_path = initiative_state.get('managerBriefPath')
    brief = load_json(brief_path, {}) if brief_path else {}
    if not isinstance(brief, dict):
        brief = {}

    github_mirror = initiative_state.get('githubMirror') if isinstance(initiative_state.get('githubMirror'), dict) else {}
    issue = github_mirror.get('issue') if isinstance(github_mirror.get('issue'), dict) else None
    if not issue:
        return None

    now = iso_now()
    github_mirror['config'] = dict(config)

    if _should_sync_pull_request(lifecycle_event=lifecycle_event, initiative_state=initiative_state, queue_item=queue_item, result=result):
        try:
            pull_request = reconcile_remote_pull_request(
                repo_path=repo_root,
                config=config,
                initiative_id=initiative_id,
                brief=brief,
                initiative_state=initiative_state,
            )
        except Exception as exc:
            _record_degraded_sync(
                github_mirror,
                now=now,
                reason='pull_request_sync_failed',
                summary=f'GitHub pull request sync failed for {lifecycle_event}: {exc}',
            )
            initiative_state['githubMirror'] = github_mirror
            save_json(state_path, initiative_state)
            return github_mirror
        github_mirror['pullRequest'] = pull_request
        initiative_state['githubMirror'] = github_mirror

    current_pull_request = github_mirror.get('pullRequest') if isinstance(github_mirror.get('pullRequest'), dict) else None
    if current_pull_request:
        initiative_state['githubMirror'] = github_mirror

    lifecycle = _build_lifecycle_projection(
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item=queue_item,
        result=result,
        blocked_reason=blocked_reason,
    )
    digest = _lifecycle_digest(lifecycle)
    current = github_mirror.get('lifecycle') if isinstance(github_mirror.get('lifecycle'), dict) else {}
    lifecycle_changed = current.get('digest') != digest
    comment_retry_pending = _lifecycle_comment_retry_pending(
        github_mirror=github_mirror,
        lifecycle_event=lifecycle_event,
        initiative_state=initiative_state,
        summary=summary,
        queue_item=queue_item,
        result=result,
        blocked_reason=blocked_reason,
    )
    if not lifecycle_changed and not comment_retry_pending:
        return github_mirror

    if lifecycle_changed:
        lifecycle['digest'] = digest
        github_mirror['lifecycle'] = lifecycle
        initiative_state['githubMirror'] = github_mirror

        try:
            _run_gh(
                repo_root,
                config,
                [
                    'issue', 'edit', str(issue['number']),
                    '--body', build_issue_body(initiative_id=initiative_id, brief=brief, initiative_state=initiative_state),
                ],
            )
        except Exception as exc:
            _record_degraded_sync(
                github_mirror,
                now=now,
                reason='lifecycle_sync_failed',
                summary=f'GitHub issue lifecycle refresh failed for {lifecycle_event}: {exc}',
            )
            initiative_state['githubMirror'] = github_mirror
            save_json(state_path, initiative_state)
            return github_mirror

        github_mirror['lastSyncAt'] = now

    try:
        _sync_lifecycle_comment(
            repo_path=repo_root,
            config=config,
            github_mirror=github_mirror,
            lifecycle_event=lifecycle_event,
            initiative_state=initiative_state,
            summary=summary,
            queue_item=queue_item,
            result=result,
            blocked_reason=blocked_reason,
        )
        _clear_degraded_sync(github_mirror)
        github_mirror['lastSyncAt'] = iso_now()
    except Exception as exc:
        _record_degraded_sync(
            github_mirror,
            now=iso_now(),
            reason='comment_sync_failed',
            summary=f'GitHub lifecycle comment sync failed for {lifecycle_event}: {exc}',
        )

    initiative_state['githubMirror'] = github_mirror
    save_json(state_path, initiative_state)
    return github_mirror
