#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = 'agentrunner/scripts/initiative_coordinator.py'


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def make_fake_gh(bin_dir: Path) -> Path:
    script = bin_dir / 'gh'
    script.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json, os, sys\n"
        "state_path = os.environ['FAKE_GH_STATE']\n"
        "args = sys.argv[1:]\n"
        "state = json.loads(open(state_path, 'r', encoding='utf-8').read())\n"
        "state.setdefault('calls', []).append(args)\n"
        "if args[:2] == ['pr', 'view']:\n"
        "    pr_number = int(args[2])\n"
        "    pr = state.get('pull_requests_by_number', {}).get(str(pr_number))\n"
        "    if pr is None:\n"
        "        open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "        print('pr not found', file=sys.stderr)\n"
        "        raise SystemExit(1)\n"
        "    open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "    print(json.dumps(pr))\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['pr', 'list']:\n"
        "    open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "    print(json.dumps(state.get('pull_request_list', [])))\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['issue', 'edit'] and '--body' in args:\n"
        "    body = args[args.index('--body') + 1]\n"
        "    state.setdefault('edited_bodies', []).append(body)\n"
        "    if state.get('fail_issue_edit'):\n"
        "        open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "        print(state.get('fail_issue_edit_message', 'edit failed'), file=sys.stderr)\n"
        "        raise SystemExit(1)\n"
        "    issue_number = int(args[2])\n"
        "    issue = {'number': issue_number, 'id': 'ISSUE_EDITED', 'url': f'https://github.com/acme/agentrunner/issues/{issue_number}', 'state': 'OPEN', 'title': 'GitHub-backed workflow phase 1'}\n"
        "    open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "    print(json.dumps(issue))\n"
        "    raise SystemExit(0)\n"
        "open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "if args[:2] == ['issue', 'list']:\n"
        "    print(json.dumps(state.get('issue_list', [])))\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['issue', 'view']:\n"
        "    issue_number = int(args[2])\n"
        "    issue = state.get('issues_by_number', {}).get(str(issue_number))\n"
        "    if issue is None:\n"
        "        print('issue not found', file=sys.stderr)\n"
        "        raise SystemExit(1)\n"
        "    print(json.dumps(issue))\n"
        "    raise SystemExit(0)\n"
        "if args[:1] == ['api'] and '--method' in args and 'POST' in args:\n"
        "    if args[1].endswith('/pulls'):\n"
        "        pr = state['created_pull_request']\n"
        "        print(json.dumps(pr))\n"
        "        raise SystemExit(0)\n"
        "    if '/comments' in args[1]:\n"
        "        state['comment_post_attempts'] = int(state.get('comment_post_attempts', 0)) + 1\n"
        "        body = None\n"
        "        if '-f' in args:\n"
        "            for index, token in enumerate(args):\n"
        "                if token == '-f' and index + 1 < len(args) and args[index + 1].startswith('body='):\n"
        "                    body = args[index + 1][5:]\n"
        "                    break\n"
        "        state.setdefault('comment_bodies', []).append(body)\n"
        "        remaining = int(state.get('comment_post_failures_remaining', 0))\n"
        "        if remaining > 0:\n"
        "            state['comment_post_failures_remaining'] = remaining - 1\n"
        "            open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "            print(state.get('comment_post_fail_message', 'comment post failed'), file=sys.stderr)\n"
        "            raise SystemExit(1)\n"
        "        comment = state.get('created_comment', {'id': 101, 'url': 'https://github.com/acme/agentrunner/issues/42#issuecomment-101'})\n"
        "        open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "        print(json.dumps(comment))\n"
        "        raise SystemExit(0)\n"
        "    issue = state['created_issue']\n"
        "    print(json.dumps(issue))\n"
        "    raise SystemExit(0)\n"
        "print('unsupported gh invocation: ' + ' '.join(args), file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding='utf-8',
    )
    script.chmod(0o755)
    return script


def run_python(repo_copy: Path, args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=str(repo_copy), env=env, capture_output=True, text=True)


def seed_repo_and_env(tmp: Path) -> tuple[Path, dict[str, str], Path]:
    repo_copy = tmp / 'repo'
    shutil.copytree(ROOT, repo_copy)
    (repo_copy / 'pyproject.toml').write_text(
        '[tool.agentrunner.github]\n'
        'enabled = true\n'
        'owner = "acme"\n'
        'repo = "agentrunner"\n',
        encoding='utf-8',
    )
    fake_bin = tmp / 'bin'
    fake_bin.mkdir(parents=True, exist_ok=True)
    make_fake_gh(fake_bin)
    fake_state = tmp / 'fake-gh-state.json'
    write_json(fake_state, {
        'issue_list': [],
        'pull_request_list': [],
        'created_issue': {
            'number': 42,
            'id': 'ISSUE_kwDOAAAB',
            'url': 'https://github.com/acme/agentrunner/issues/42',
            'state': 'OPEN',
            'title': 'GitHub-backed workflow phase 1',
        },
        'created_pull_request': {
            'number': 8,
            'id': 'PR_kwDOAAAB',
            'url': 'https://github.com/acme/agentrunner/pull/8',
            'state': 'OPEN',
            'title': 'GitHub-backed workflow phase 1',
            'headRefName': 'feature/agentrunner/github-backed-workflow-phase1',
            'baseRefName': 'main',
        },
        'pull_requests_by_number': {
            '8': {
                'number': 8,
                'id': 'PR_kwDOAAAB',
                'url': 'https://github.com/acme/agentrunner/pull/8',
                'state': 'OPEN',
                'title': 'GitHub-backed workflow phase 1',
                'headRefName': 'feature/agentrunner/github-backed-workflow-phase1',
                'baseRefName': 'main',
            },
        },
        'created_comment': {
            'id': 101,
            'url': 'https://github.com/acme/agentrunner/issues/42#issuecomment-101',
        },
    })
    env = dict(os.environ)
    env['PATH'] = f"{fake_bin}:{env.get('PATH', '')}"
    env['FAKE_GH_STATE'] = str(fake_state)
    env['PYTHONPATH'] = str(repo_copy / 'agentrunner/scripts')
    return repo_copy, env, fake_state


def test_sync_lifecycle_issue_update_throttles_duplicate_write_and_persists_projection() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-throttle-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)
        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'execution',
            'currentSubtaskId': 'github-backed-workflow-3',
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="subtask_started", summary="Started subtask.", queue_item={"id": "q1", "role": "developer", "repo_path": repo})\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="subtask_started", summary="Started subtask.", queue_item={"id": "q1", "role": "developer", "repo_path": repo})\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        fake = load_json(fake_state)
        edit_calls = [call for call in fake['calls'] if call[:2] == ['issue', 'edit']]
        assert len(edit_calls) == 1
        body = fake['edited_bodies'][0]
        assert '## Current status' in body
        assert 'subtask_started' in body
        assert 'Started subtask.' in body

        saved = load_json(state_path)
        assert saved['githubMirror']['lifecycle']['event'] == 'subtask_started'
        assert saved['githubMirror']['lifecycle']['queueItemId'] == 'q1'
        assert saved['githubMirror']['lastSyncAt']
        assert 'degradedSync' not in saved['githubMirror']


def test_invoker_merge_blocked_records_degraded_sync_when_issue_refresh_fails() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-degraded-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)
        fake = load_json(fake_state)
        fake['fail_issue_edit'] = True
        fake['fail_issue_edit_message'] = 'boom: edit denied'
        write_json(fake_state, fake)

        state_dir = temp_root / 'state'
        initiative_id = 'agentrunner-github-backed-workflow-phase1'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'statusMessage': {
                'target': {'channel': 'discord', 'target': 'channel:1'},
                'handle': {'id': 'msg-1', 'channelId': '1', 'provider': 'discord'},
                'delivery': {'status': 'active', 'lastOperation': 'update', 'metadata': {}},
                'history': [],
            },
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
            },
        })
        write_json(state_dir / 'initiatives' / initiative_id / 'brief.json', {
            'initiativeId': initiative_id,
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })

        code = (
            'import invoker\n'
            'invoker.gateway_http_invoke = lambda *a, **k: {"ok": True, "messageId": "msg-1", "channelId": "1"}\n'
            f'state_dir = r"{state_dir}"\n'
            f'repo = r"{repo_copy}"\n'
            'ok = invoker.emit_initiative_status_update(state_dir, queue_item={"id": "merge-1", "role": "merger", "repo_path": repo, "branch": "feature/agentrunner/github-backed-workflow-phase1", "base": "main", "initiative": {"initiativeId": "agentrunner-github-backed-workflow-phase1"}}, result={"status": "blocked", "summary": "Merge blocked by policy.", "mergeBlocker": {"detail": "Needs human intervention."}})\n'
            'raise SystemExit(0 if ok else 1)\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        saved = load_json(initiative_state_path)
        degraded = saved['githubMirror']['degradedSync']
        assert degraded['reason'] == 'lifecycle_sync_failed'
        assert 'merge_blocked' in degraded['summary']
        assert 'boom: edit denied' in degraded['summary']
        assert saved['githubMirror']['lifecycle']['event'] == 'merge_blocked'
        assert saved['githubMirror']['lifecycle']['blockedReason'] == 'Needs human intervention.'




def test_sync_lifecycle_issue_update_retries_comment_sync_after_failed_identical_update() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-comment-retry-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)
        fake = load_json(fake_state)
        fake['comment_post_failures_remaining'] = 1
        fake['comment_post_fail_message'] = 'boom: comment denied'
        write_json(fake_state, fake)

        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
                'pullRequest': {'number': 8, 'handle': 'acme/agentrunner#PR8'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'kwargs = dict(repo_path=repo, initiative_state_path=path, lifecycle_event="merge_completed", summary="Merge landed.", queue_item={"id": "merge-1", "role": "merger", "repo_path": repo}, result={"status": "ok", "commit": "abc123", "merged": True})\n'
            'sync_lifecycle_issue_update(**kwargs)\n'
            'sync_lifecycle_issue_update(**kwargs)\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        fake = load_json(fake_state)
        edit_calls = [call for call in fake['calls'] if call[:2] == ['issue', 'edit']]
        comment_calls = [call for call in fake['calls'] if call[:2] == ['api', 'repos/acme/agentrunner/issues/8/comments']]
        assert len(edit_calls) == 1
        assert len(comment_calls) == 2
        assert fake['comment_post_attempts'] == 2

        saved = load_json(state_path)
        comment_sync = saved['githubMirror']['commentSync']
        assert comment_sync['lastAttemptDigest']
        assert comment_sync['lastDigest'] == comment_sync['lastAttemptDigest']
        assert comment_sync['lastTargetKind'] == 'pull_request'
        assert comment_sync['lastTargetNumber'] == 8
        assert 'degradedSync' not in saved['githubMirror']



def test_sync_lifecycle_issue_update_dedupes_repeated_pull_request_comment_event() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-comment-dedupe-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)

        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
                'pullRequest': {'number': 8, 'handle': 'acme/agentrunner#PR8'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'kwargs = dict(repo_path=repo, initiative_state_path=path, lifecycle_event="merge_completed", summary="Merge landed.", queue_item={"id": "merge-1", "role": "merger", "repo_path": repo}, result={"status": "ok", "commit": "abc123", "merged": True})\n'
            'sync_lifecycle_issue_update(**kwargs)\n'
            'sync_lifecycle_issue_update(**kwargs)\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        fake = load_json(fake_state)
        comment_calls = [call for call in fake['calls'] if call[:2] == ['api', 'repos/acme/agentrunner/issues/8/comments']]
        assert len(comment_calls) == 1
        assert fake['comment_post_attempts'] == 1

        saved = load_json(state_path)
        comment_sync = saved['githubMirror']['commentSync']
        assert comment_sync['lastTargetKind'] == 'pull_request'
        assert comment_sync['lastTargetNumber'] == 8
        assert 'degradedSync' not in saved['githubMirror']



def test_sync_lifecycle_issue_update_routes_issue_and_pr_comment_lanes_end_to_end() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-comment-routing-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)

        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'review-manager',
            'currentSubtaskId': 'github-backed-workflow-3',
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
                'pullRequest': {'number': 8, 'handle': 'acme/agentrunner#PR8'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="initiative_blocked", summary="Manager paused the initiative pending clarification.", queue_item={"id": "mgr-1", "role": "manager", "repo_path": repo}, result={"status": "blocked"}, blocked_reason="Need a tighter operator-facing routing note.")\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="review_blocked", summary="Reviewer found one bounded fix.", queue_item={"id": "review-1", "role": "reviewer", "repo_path": repo}, result={"status": "blocked", "findings": [{"title": "Tighten docs", "detail": "Explain which lane gets the lifecycle note."}]}, blocked_reason="Docs routing note missing.")\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        fake = load_json(fake_state)
        issue_comment_calls = [call for call in fake['calls'] if call[:2] == ['api', 'repos/acme/agentrunner/issues/42/comments']]
        pr_comment_calls = [call for call in fake['calls'] if call[:2] == ['api', 'repos/acme/agentrunner/issues/8/comments']]
        assert len(issue_comment_calls) == 1
        assert len(pr_comment_calls) == 1
        assert fake['comment_post_attempts'] == 2
        assert any('Manager paused the initiative pending clarification.' in (body or '') for body in fake['comment_bodies'])
        assert any('Reviewer found one bounded fix.' in (body or '') for body in fake['comment_bodies'])

        saved = load_json(state_path)
        comment_sync = saved['githubMirror']['commentSync']
        assert comment_sync['lastEvent'] == 'review_blocked'
        assert comment_sync['lastTargetKind'] == 'pull_request'
        assert comment_sync['lastTargetNumber'] == 8
        assert saved['githubMirror']['lifecycle']['event'] == 'review_blocked'
        assert 'degradedSync' not in saved['githubMirror']



def test_sync_lifecycle_issue_update_records_comment_sync_degraded_details() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-comment-degraded-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)
        fake = load_json(fake_state)
        fake['comment_post_failures_remaining'] = 1
        fake['comment_post_fail_message'] = 'boom: comment denied'
        write_json(fake_state, fake)

        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
                'pullRequest': {'number': 8, 'handle': 'acme/agentrunner#PR8'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="merge_completed", summary="Merge landed.", queue_item={"id": "merge-1", "role": "merger", "repo_path": repo}, result={"status": "ok", "commit": "abc123", "merged": True})\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        saved = load_json(state_path)
        degraded = saved['githubMirror']['degradedSync']
        assert degraded['reason'] == 'comment_sync_failed'
        assert 'merge_completed' in degraded['summary']
        assert 'boom: comment denied' in degraded['summary']
        assert saved['githubMirror']['lifecycle']['event'] == 'merge_completed'
        assert saved['githubMirror']['lastSyncAt']

        details = degraded['details']
        assert details['lifecycleEvent'] == 'merge_completed'
        assert details['targetKind'] == 'pull_request'
        assert details['targetNumber'] == 8
        assert details['targetHandle'] == 'acme/agentrunner#PR8'
        assert details['queueItemId'] == 'merge-1'
        assert details['role'] == 'merger'
        assert details['resultStatus'] == 'ok'
        assert details['commit'] == 'abc123'



def test_sync_lifecycle_issue_update_creates_late_pull_request_on_closure_transition() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-pr-create-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)
        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="initiative_phase_changed", summary="Initiative is queued for closure merge.", queue_item={"id": "merge-queue", "role": "merger", "repo_path": repo}, result={"status": "ok"})\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        fake = load_json(fake_state)
        pr_list_calls = [call for call in fake['calls'] if call[:2] == ['pr', 'list']]
        assert len(pr_list_calls) == 1
        pr_create_calls = [call for call in fake['calls'] if call[:2] == ['api', 'repos/acme/agentrunner/pulls']]
        assert len(pr_create_calls) == 1

        saved = load_json(state_path)
        pull_request = saved['githubMirror']['pullRequest']
        assert pull_request['number'] == 8
        assert pull_request['headRef'] == 'feature/agentrunner/github-backed-workflow-phase1'
        assert pull_request['baseRef'] == 'main'
        assert 'degradedSync' not in saved['githubMirror']


def test_merge_blocked_without_explicit_blocked_merger_result_does_not_create_pull_request() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-lifecycle-pr-safe-blocked-') as tmp:
        temp_root = Path(tmp)
        repo_copy, env, fake_state = seed_repo_and_env(temp_root)
        state_path = temp_root / 'state.json'
        brief_path = temp_root / 'brief.json'
        write_json(brief_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'title': 'GitHub-backed workflow phase 1',
            'objective': 'Mirror lifecycle milestones compactly.',
        })
        write_json(state_path, {
            'initiativeId': 'agentrunner-github-backed-workflow-phase1',
            'phase': 'closure-merger',
            'currentSubtaskId': None,
            'managerBriefPath': str(brief_path),
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
            'githubMirror': {
                'issue': {'number': 42, 'handle': 'acme/agentrunner#42'},
            },
        })

        code = (
            'from github_backing import sync_lifecycle_issue_update\n'
            f'path = r"{state_path}"\n'
            f'repo = r"{repo_copy}"\n'
            'sync_lifecycle_issue_update(repo_path=repo, initiative_state_path=path, lifecycle_event="merge_blocked", summary="Merge blocked by policy.", queue_item={"id": "merge-1", "role": "merger", "repo_path": repo}, result={"status": "blocked"}, blocked_reason="Needs human intervention.")\n'
        )
        proc = run_python(repo_copy, ['-c', code], env=env)
        assert proc.returncode == 0, proc.stdout + proc.stderr

        fake = load_json(fake_state)
        assert not any(call[:1] == ['pr'] for call in fake['calls'])
        assert not any(call[:2] == ['api', 'repos/acme/agentrunner/pulls'] for call in fake['calls'])

        saved = load_json(state_path)
        assert 'pullRequest' not in saved['githubMirror']
        assert saved['githubMirror']['lifecycle']['event'] == 'merge_blocked'


def main() -> int:
    test_sync_lifecycle_issue_update_throttles_duplicate_write_and_persists_projection()
    test_sync_lifecycle_issue_update_retries_comment_sync_after_failed_identical_update()
    test_sync_lifecycle_issue_update_dedupes_repeated_pull_request_comment_event()
    test_sync_lifecycle_issue_update_routes_issue_and_pr_comment_lanes_end_to_end()
    test_sync_lifecycle_issue_update_records_comment_sync_degraded_details()
    test_sync_lifecycle_issue_update_creates_late_pull_request_on_closure_transition()
    test_merge_blocked_without_explicit_blocked_merger_result_does_not_create_pull_request()
    test_invoker_merge_blocked_records_degraded_sync_when_issue_refresh_fails()
    print('ok: github-backed lifecycle refreshes stay compact, prove issue-vs-PR comment routing end to end, dedupe repeated comments, retain degraded comment-sync details, create a late closure PR when needed, and keep blocked merge sync semantics safe')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
