#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')


def load_json(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='invoker-terminal-closure-guard-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        state_dir = temp_root / 'state'
        state_path = state_dir / 'state.json'
        queue_path = state_dir / 'queue.json'
        initiative_id = 'tail-case-terminal-success'
        reviewer_qid = f'{initiative_id}-reviewer'
        reviewer_result_path = state_dir / 'results' / f'{reviewer_qid}.json'
        handoff_path = state_dir / 'handoffs' / f'{reviewer_qid}.json'
        initiative_state_path = state_dir / 'initiatives' / initiative_id / 'state.json'
        stale_followup_id = f'{reviewer_qid}-followup-stale'

        write_json(queue_path, [
            {
                'id': stale_followup_id,
                'project': 'agentrunner',
                'role': 'developer',
                'createdAt': '2026-04-19T06:20:00+00:00',
                'repo_path': str(repo_path),
                'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                'base': 'master',
                'goal': 'Stale follow-up that should be scrubbed once closure is terminal.',
                'checks': [],
                'constraints': {},
                'contextFiles': [],
                'initiative': {
                    'initiativeId': initiative_id,
                    'subtaskId': 'implement-terminal-closure-guard',
                    'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                    'base': 'master',
                },
            }
        ])
        write_json(initiative_state_path, {
            'initiativeId': initiative_id,
            'phase': 'completed',
            'managerBriefPath': str(state_dir / 'initiatives' / initiative_id / 'brief.json'),
            'architectPlanPath': str(state_dir / 'initiatives' / initiative_id / 'plan.json'),
            'managerDecisionPath': str(state_dir / 'initiatives' / initiative_id / 'decision.json'),
            'currentSubtaskId': None,
            'completedSubtasks': ['implement-terminal-closure-guard'],
            'pendingSubtasks': [],
            'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
            'base': 'master',
            'writtenAt': '2026-04-19T06:19:00+00:00',
        })
        write_json(reviewer_result_path, {
            'status': 'ok',
            'role': 'reviewer',
            'summary': 'Reviewer arrived late, but the initiative is already terminal-success.',
            'approved': True,
            'findings': [
                {
                    'title': 'This follow-up should never be re-enqueued after closure',
                    'detail': 'Terminal closure already happened.',
                }
            ],
            'requestExtraDevTurn': True,
            'requestReason': 'Would normally request a developer follow-up.',
            'writtenAt': '2026-04-19T06:21:00+00:00',
            'checks': [],
        })
        write_json(handoff_path, {
            'sourceQueueItemId': reviewer_qid,
            'sourceRole': 'reviewer',
            'targetRole': 'developer',
            'project': 'agentrunner',
            'repoPath': str(repo_path),
            'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
            'base': 'master',
            'goal': 'This developer follow-up must be ignored because the initiative is already completed.',
            'checks': [],
            'findings': [
                {
                    'title': 'Late reviewer handoff',
                    'detail': 'Should be dropped after terminal closure.',
                }
            ],
            'contextFiles': [],
            'constraints': {},
            'writtenAt': '2026-04-19T06:21:00+00:00',
        })
        write_json(state_path, {
            'project': 'agentrunner',
            'running': True,
            'current': {
                'queueItemId': reviewer_qid,
                'role': 'reviewer',
                'queueItem': {
                    'id': reviewer_qid,
                    'project': 'agentrunner',
                    'role': 'reviewer',
                    'repo_path': str(repo_path),
                    'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                    'base': 'master',
                    'goal': 'Late reviewer completion.',
                    'checks': [],
                    'initiative': {
                        'initiativeId': initiative_id,
                        'subtaskId': 'implement-terminal-closure-guard',
                        'branch': 'feature/agentrunner/tail-case-initiative-cleanup',
                        'base': 'master',
                    },
                },
                'runId': 'run-late-reviewer',
                'sessionKey': 'hook:agentrunner:agentrunner:reviewer',
                'startedAt': '2026-04-19T06:20:30+00:00',
                'resultPath': str(reviewer_result_path),
                'handoffPath': str(handoff_path),
                'announce': False,
                'channel': 'discord',
                'to': '',
            },
            'runtime': {
                'extraDevTurnsUsed': 0,
                'lastBranch': 'feature/agentrunner/tail-case-initiative-cleanup',
            },
            'limits': {
                'maxExtraDevTurns': 1,
            },
            'updatedAt': '2026-04-19T06:20:30+00:00',
        })

        proc = subprocess.run([
            sys.executable,
            str(repo_path / 'agentrunner/scripts/invoker.py'),
            '--project', 'agentrunner',
            '--state-dir', str(state_dir),
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f'invoker failed: {proc.stdout}{proc.stderr}')

        queue_after = load_json(queue_path)
        if queue_after != []:
            raise SystemExit(f'terminal-success guard should scrub follow-ups, got queue: {queue_after}')

        state_after = load_json(state_path)
        current = state_after.get('current')
        if current is not None:
            raise SystemExit(f'expected invoker to clear current run, got: {current}')
        runtime = state_after.get('runtime') or {}
        if runtime.get('extraDevTurnsUsed') != 0:
            raise SystemExit(f'terminal-success guard should not consume extra dev turns, got: {runtime}')

        handoff_materialized = state_dir / 'review_findings' / f'{reviewer_qid}.json'
        if handoff_materialized.exists():
            raise SystemExit(f'terminal-success guard should not materialize review findings for scrubbed follow-up: {handoff_materialized}')

    print('ok: invoker drops late follow-ups once initiative closure is terminal-success')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
