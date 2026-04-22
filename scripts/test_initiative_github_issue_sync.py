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
        "open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "if args[:2] == ['issue', 'edit'] and '--body' in args:\n"
        "    body = args[args.index('--body') + 1]\n"
        "    state.setdefault('edited_bodies', []).append(body)\n"
        "    issue_number = int(args[2])\n"
        "    issue = state.get('issues_by_number', {}).get(str(issue_number)) or state.get('created_issue') or {}\n"
        "    issue = dict(issue)\n"
        "    issue['number'] = issue_number\n"
        "    open(state_path, 'w', encoding='utf-8').write(json.dumps(state, indent=2) + '\\n')\n"
        "    print(json.dumps(issue))\n"
        "    raise SystemExit(0)\n"
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
        "    issue = state['created_issue']\n"
        "    print(json.dumps(issue))\n"
        "    raise SystemExit(0)\n"
        "print('unsupported gh invocation: ' + ' '.join(args), file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding='utf-8',
    )
    script.chmod(0o755)
    return script


def base_brief() -> dict:
    return {
        'initiativeId': 'agentrunner-github-backed-workflow-phase1',
        'title': 'GitHub-backed workflow phase 1',
        'objective': 'Mirror the initiative to GitHub without making GitHub authoritative.',
        'desiredOutcomes': ['Create or reuse one issue', 'Persist issue linkage into initiative-local state'],
        'definitionOfDone': ['Manager kickoff stores issue metadata for later lifecycle steps'],
    }


def base_queue_item(repo_path: Path, initiative_id: str) -> dict:
    return {
        'id': f'{initiative_id}-manager',
        'project': 'agentrunner',
        'role': 'manager',
        'repo_path': str(repo_path),
        'branch': 'feature/agentrunner/github-backed-workflow-phase1',
        'base': 'main',
        'initiative': {
            'initiativeId': initiative_id,
            'phase': 'design-manager',
            'branch': 'feature/agentrunner/github-backed-workflow-phase1',
            'base': 'main',
        },
    }


def seed_manager_completion(state_dir: Path, repo_path: Path, *, initiative_id: str) -> Path:
    initiative_dir = state_dir / 'initiatives' / initiative_id
    initiative_state_path = initiative_dir / 'state.json'
    brief_path = initiative_dir / 'brief.json'
    write_json(brief_path, base_brief())
    write_json(initiative_state_path, {
        'initiativeId': initiative_id,
        'phase': 'design-manager',
        'managerBriefPath': str(brief_path),
        'architectPlanPath': str(initiative_dir / 'plan.json'),
        'managerDecisionPath': str(initiative_dir / 'decision.json'),
        'currentSubtaskId': None,
        'completedSubtasks': [],
        'pendingSubtasks': [],
        'branch': 'feature/agentrunner/github-backed-workflow-phase1',
        'base': 'main',
    })
    queue_item = base_queue_item(repo_path, initiative_id)
    write_json(state_dir / 'state.json', {
        'project': 'agentrunner',
        'running': False,
        'current': None,
        'lastCompleted': {
            'queueItemId': queue_item['id'],
            'role': 'manager',
            'queueItem': queue_item,
            'resultPath': str(state_dir / 'results' / f"{queue_item['id']}.json"),
        },
        'initiative': {
            'initiativeId': initiative_id,
            'phase': 'design-manager',
            'statePath': str(initiative_state_path),
        },
    })
    write_json(state_dir / 'queue.json', [])
    write_json(state_dir / 'results' / f"{queue_item['id']}.json", {
        'status': 'ok',
        'role': 'manager',
        'summary': 'Wrote manager brief.',
        'checks': [],
        'writtenAt': '2026-04-22T06:00:00+00:00',
    })
    return initiative_state_path


def run_coordinator(repo_copy: Path, state_dir: Path, *, env: dict[str, str]) -> dict:
    proc = subprocess.run(
        [sys.executable, str(repo_copy / COORDINATOR), '--state-dir', str(state_dir)],
        cwd=str(repo_copy),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_manager_kickoff_creates_and_persists_github_issue() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-create-') as tmp:
        temp_root = Path(tmp)
        repo_copy = temp_root / 'repo'
        shutil.copytree(ROOT, repo_copy)
        (repo_copy / 'pyproject.toml').write_text(
            '[tool.agentrunner.github]\n'
            'enabled = true\n'
            'owner = "acme"\n'
            'repo = "agentrunner"\n',
            encoding='utf-8',
        )

        state_dir = temp_root / 'state'
        initiative_id = 'agentrunner-github-backed-workflow-phase1'
        initiative_state_path = seed_manager_completion(state_dir, repo_copy, initiative_id=initiative_id)

        fake_bin = temp_root / 'bin'
        fake_bin.mkdir(parents=True, exist_ok=True)
        make_fake_gh(fake_bin)
        fake_state = temp_root / 'fake-gh-state.json'
        write_json(fake_state, {
            'issue_list': [],
            'created_issue': {
                'number': 42,
                'id': 'ISSUE_kwDOAAAB',
                'url': 'https://github.com/acme/agentrunner/issues/42',
                'state': 'OPEN',
                'title': 'GitHub-backed workflow phase 1',
            },
        })

        env = dict(os.environ)
        env['PATH'] = f"{fake_bin}:{env.get('PATH', '')}"
        env['FAKE_GH_STATE'] = str(fake_state)

        payload = run_coordinator(repo_copy, state_dir, env=env)
        assert payload == {'changed': True}

        initiative_state = load_json(initiative_state_path)
        assert initiative_state['phase'] == 'design-architect'
        mirror = initiative_state['githubMirror']
        assert mirror['config']['owner'] == 'acme'
        assert mirror['issue']['number'] == 42
        assert mirror['issue']['handle'] == 'acme/agentrunner#42'
        assert mirror['issue']['url'] == 'https://github.com/acme/agentrunner/issues/42'
        assert 'degradedSync' not in mirror
        assert isinstance(mirror.get('lastSyncAt'), str) and mirror['lastSyncAt']

        queue = load_json(state_dir / 'queue.json')
        assert queue[0]['role'] == 'architect'
        assert queue[0]['initiative']['initiativeId'] == initiative_id

        gh_calls = load_json(fake_state)['calls']
        assert gh_calls[0][:2] == ['issue', 'list']
        assert gh_calls[1][:3] == ['api', 'repos/acme/agentrunner/issues', '--method']


def test_manager_kickoff_reconciles_existing_issue_without_creating_new_one() -> None:
    with tempfile.TemporaryDirectory(prefix='initiative-gh-reconcile-') as tmp:
        temp_root = Path(tmp)
        repo_copy = temp_root / 'repo'
        shutil.copytree(ROOT, repo_copy)
        (repo_copy / 'pyproject.toml').write_text(
            '[tool.agentrunner.github]\n'
            'enabled = true\n'
            'owner = "acme"\n'
            'repo = "agentrunner"\n',
            encoding='utf-8',
        )

        state_dir = temp_root / 'state'
        initiative_id = 'agentrunner-github-backed-workflow-phase1'
        initiative_state_path = seed_manager_completion(state_dir, repo_copy, initiative_id=initiative_id)
        initiative_state = load_json(initiative_state_path)
        initiative_state['githubMirror'] = {
            'issue': {
                'number': 7,
                'handle': 'acme/agentrunner#7',
                'url': 'https://github.com/acme/agentrunner/issues/7',
            }
        }
        write_json(initiative_state_path, initiative_state)

        fake_bin = temp_root / 'bin'
        fake_bin.mkdir(parents=True, exist_ok=True)
        make_fake_gh(fake_bin)
        fake_state = temp_root / 'fake-gh-state.json'
        write_json(fake_state, {
            'issue_list': [],
            'issues_by_number': {
                '7': {
                    'number': 7,
                    'id': 'ISSUE_kwDOEXISTING',
                    'url': 'https://github.com/acme/agentrunner/issues/7',
                    'state': 'OPEN',
                    'title': 'GitHub-backed workflow phase 1',
                }
            },
            'created_issue': {
                'number': 999,
                'id': 'should-not-be-used',
                'url': 'https://github.com/acme/agentrunner/issues/999',
                'state': 'OPEN',
                'title': 'unexpected',
            },
        })

        env = dict(os.environ)
        env['PATH'] = f"{fake_bin}:{env.get('PATH', '')}"
        env['FAKE_GH_STATE'] = str(fake_state)

        payload = run_coordinator(repo_copy, state_dir, env=env)
        assert payload == {'changed': True}

        initiative_state_after = load_json(initiative_state_path)
        assert initiative_state_after['githubMirror']['issue']['number'] == 7
        assert initiative_state_after['githubMirror']['issue']['id'] == 'ISSUE_kwDOEXISTING'
        gh_calls = load_json(fake_state)['calls']
        assert gh_calls[0][:3] == ['issue', 'view', '7']
        assert not any(call[:1] == ['api'] for call in gh_calls)
