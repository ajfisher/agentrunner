#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='reliability-poll-closure-watch-') as tmp:
        temp_root = Path(tmp)
        repo_path = temp_root / 'repo'
        shutil.copytree(ROOT, repo_path)

        import sys
        sys.path.insert(0, str(repo_path / 'agentrunner/scripts'))
        import reliability_poll  # type: ignore

        closure_active_dir = temp_root / 'closure-active'
        write_json(closure_active_dir / 'initiatives' / 'closure-stuck' / 'state.json', {
            'initiativeId': 'closure-stuck',
            'phase': 'review-manager',
            'branch': 'feature/agentrunner/closure-handoff-state-semantics',
            'base': 'master',
        })
        write_json(closure_active_dir / 'state.json', {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'initiative': {
                'initiativeId': 'closure-stuck',
                'phase': 'review-manager',
                'statePath': str(closure_active_dir / 'initiatives' / 'closure-stuck' / 'state.json'),
            },
            'updatedAt': '2026-04-21T01:55:00+00:00',
        })
        write_json(closure_active_dir / 'queue.json', [])
        if reliability_poll.should_poll_project(closure_active_dir) is not True:
            raise SystemExit('reliability poll should keep watching when closure.handoffSafe is false, even if queue is empty')

        clean_dir = temp_root / 'idle-clean'
        write_json(clean_dir / 'state.json', {
            'project': 'agentrunner',
            'running': False,
            'current': None,
            'updatedAt': '2026-04-21T01:56:00+00:00',
        })
        write_json(clean_dir / 'queue.json', [])
        if reliability_poll.should_poll_project(clean_dir) is not False:
            raise SystemExit('reliability poll should stay quiet once closure becomes handoff-safe idle-clean')

    print('ok: reliability poll watches explicit closure semantics instead of queue quietness alone')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
