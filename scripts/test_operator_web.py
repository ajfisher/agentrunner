#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentrunner.scripts import operator_web

ROOT = operator_web.__file__


def sample_envelope() -> dict:
    return {
        'project': 'demo',
        'artifactPath': '/tmp/demo/operator_status.json',
        'notes': ['using canonical snapshot api'],
        'snapshot': {
            'project': 'demo',
            'status': 'active',
            'current': {
                'queueItemId': 'developer-1',
                'role': 'developer',
                'branch': 'feature/agentrunner/operator-web-ui',
                'ageSeconds': 42,
            },
            'queue': {
                'depth': 2,
                'nextIds': ['reviewer-1', 'manager-1'],
                'preview': [
                    {
                        'queueItemId': 'reviewer-1',
                        'role': 'reviewer',
                        'branch': 'feature/agentrunner/operator-web-ui',
                        'goal': 'Review the browser seam',
                    }
                ],
            },
            'initiative': {
                'initiativeId': 'agentrunner-operator-web-ui',
                'phase': 'implementation',
                'currentSubtaskId': 'operator-web-ui-http-and-viewmodel-seam',
            },
            'lastCompleted': {
                'queueItemId': 'architect-1',
                'role': 'architect',
                'status': 'ok',
                'summary': 'Locked the API-first seam.',
            },
            'warnings': [
                {'severity': 'info', 'summary': 'read-only browser renderer'},
            ],
            'reconciliation': {
                'decision': 'active',
                'summary': 'active runtime lock matches canonical snapshot',
                'reasons': [],
            },
            'updatedAt': '2026-04-20T01:00:00Z',
        },
    }


def test_page_model_is_derived_from_canonical_snapshot_contract() -> None:
    model = operator_web.build_page_model_from_snapshot_envelope(sample_envelope())
    payload = operator_web.page_model_payload(model)
    assert payload['project'] == 'demo'
    assert payload['artifactPath'].endswith('/tmp/demo/operator_status.json')
    assert payload['modeLine'] == 'Mode: browser renderer over canonical /v1/operator/snapshot'
    assert payload['statusLine'] == 'Status: active'
    titles = [section['title'] for section in payload['sections']]
    assert titles == ['current', 'queue', 'initiative', 'last completed', 'warnings', 'reconciliation']
    queue_lines = next(section['lines'] for section in payload['sections'] if section['title'] == 'queue')
    assert 'Depth: 2' in queue_lines
    assert 'Next: reviewer-1, manager-1' in queue_lines


def test_renderer_requires_the_canonical_snapshot_fields() -> None:
    try:
        operator_web.build_page_model_from_snapshot_envelope({'snapshot': {'status': 'active'}})
    except operator_web.OperatorWebContractError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError('expected OperatorWebContractError')
    assert 'snapshot missing required fields:' in message
    assert 'queue' in message
    assert 'updatedAt' in message


def test_rendered_html_mentions_the_api_contract_not_a_second_runtime() -> None:
    html = operator_web.render_html_from_snapshot_envelope(sample_envelope())
    assert 'AgentRunner operator · demo' in html
    assert '/v1/operator/snapshot' in html
    assert 'developer-1 | developer | feature/agentrunner/operator-web-ui | age=42s' in html
    assert 'read-only browser renderer' in html


def test_top_level_cli_no_longer_exposes_web_command() -> None:
    proc = subprocess.run(
        [sys.executable, '-m', 'agentrunner', 'web'],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert 'invalid choice' in proc.stderr
    assert 'web' in proc.stderr


def main() -> int:
    test_page_model_is_derived_from_canonical_snapshot_contract()
    test_renderer_requires_the_canonical_snapshot_fields()
    test_rendered_html_mentions_the_api_contract_not_a_second_runtime()
    test_top_level_cli_no_longer_exposes_web_command()
    print('ok: browser viewmodel/html seam renders from canonical snapshot envelopes and no longer exposes a separate web runtime')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
