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


def issue_marker(initiative_id: str) -> str:
    return f'Initiative ID: {initiative_id}'


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

    return '\n'.join(lines).strip() + '\n'


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
        degraded = github_mirror.get('degradedSync') if isinstance(github_mirror.get('degradedSync'), dict) else {}
        first_seen = degraded.get('firstSeenAt') if isinstance(degraded.get('firstSeenAt'), str) and degraded.get('firstSeenAt').strip() else now
        github_mirror['degradedSync'] = {
            'status': 'degraded',
            'reason': 'issue_sync_failed',
            'summary': f'GitHub initiative issue sync failed during manager kickoff: {exc}',
            'firstSeenAt': first_seen,
            'lastSeenAt': now,
            'lastAttemptAt': now,
        }
        initiative_state['githubMirror'] = github_mirror
        state_path.write_text(json.dumps(initiative_state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        return github_mirror

    github_mirror['issue'] = issue
    github_mirror['lastSyncAt'] = now
    github_mirror.pop('degradedSync', None)
    initiative_state['githubMirror'] = github_mirror
    state_path.write_text(json.dumps(initiative_state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return github_mirror
