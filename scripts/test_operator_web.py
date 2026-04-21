#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
            'closure': {
                'state': 'execution-active',
                'handoffSafe': False,
                'quiet': False,
                'initiativePhase': 'implementation',
                'reason': 'initiative is still in design/execution or runtime work remains before closure is settled',
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
    assert payload['statusSummary'] == 'Active — developer is working on developer-1 with 2 more queued.'
    assert payload['updatedSummary'].startswith('Snapshot recency: ')
    assert [chip['label'] for chip in payload['chips'][:3]] == [
        'overall active',
        'running · queue depth 2',
        '1 warning',
    ]
    assert payload['chips'][0]['tone'] == 'good'
    watch_titles = [group['title'] for group in payload['watchGroups']]
    assert watch_titles == [
        'What is happening now?',
        'What is next?',
        'What just finished?',
        'What needs attention?',
    ]
    assert payload['watchGroups'][0]['summary'] == 'Developer is working on developer-1.'
    assert payload['watchGroups'][1]['summary'] == 'Next up: reviewer-1.'
    assert payload['watchGroups'][2]['summary'] == 'Most recently finished: architect-1 (ok).'
    assert payload['watchGroups'][3]['summary'] == '1 warning needs attention.'
    queue_lines = payload['watchGroups'][1]['lines']
    assert '2 items are waiting in the queue.' in queue_lines
    assert 'Coming up next: reviewer-1, manager-1' in queue_lines
    titles = [section['title'] for section in payload['sections']]
    assert titles == ['initiative context', 'closure details', 'warning details', 'reconciliation details']


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
    assert 'Active — developer is working on developer-1 with 2 more queued.' in html
    assert 'Operator watch surface' in html
    assert 'A read-only watch surface for the current run, queued stack, recent completion, and any blocked, waiting, or handoff-safety signals.' in html
    assert 'What is happening now?' in html
    assert 'Live execution focus' in html
    assert 'Queued stack' in html
    assert 'Attention + handoff' in html
    assert 'Show the bounded queue stack so the next few follow-up turns are understandable without reading raw mechanics files.' in html
    assert 'Most recently finished: architect-1 (ok).' in html
    assert 'overall active' in html
    assert 'running · queue depth 2' in html
    assert 'read-only browser renderer' in html
    assert 'data-refresh-ms="5000"' in html
    assert 'window.setInterval(refreshSnapshot, refreshMs);' in html
    assert "fetch(`/v1/operator/snapshot?project=${encodeURIComponent(project)}`" in html


def test_initial_page_model_json_is_safe_against_script_breakout() -> None:
    envelope = sample_envelope()
    envelope['snapshot']['queue']['preview'][0]['goal'] = 'goal </script><script>alert(1)</script>'
    html = operator_web.render_html_from_snapshot_envelope(envelope)
    assert '</script><script>alert(1)</script>' not in html
    assert '\\u003c/script\\u003e\\u003cscript\\u003ealert(1)\\u003c/script\\u003e' in html
    assert 'alert(1)' in html
    assert 'const initialPageModel = {' in html


def test_unavailable_renderer_uses_degraded_status_chips() -> None:
    html = operator_web.render_unavailable_html(
        project='demo',
        artifact_path='/tmp/demo/operator_status.json',
        notes=('No canonical snapshot is available yet.',),
    )
    assert 'Snapshot unavailable — the browser surface cannot confidently describe current mechanics state yet.' in html
    assert 'overall snapshot unavailable' in html
    assert 'What needs attention?' in html
    assert 'Canonical snapshot missing.' in html
    assert 'Canonical operator snapshot is missing or malformed' in html


def test_refresh_model_keeps_paused_status_chip_in_warn_tone() -> None:
    envelope = sample_envelope()
    envelope['snapshot']['status'] = 'paused'
    envelope['snapshot']['current'] = {}
    envelope['snapshot']['queue'] = {'depth': 0, 'nextIds': [], 'preview': []}
    envelope['snapshot']['warnings'] = []

    model = operator_web.build_page_model_from_snapshot_envelope(envelope)
    payload = operator_web.page_model_payload(model)
    html = operator_web.render_html_from_snapshot_envelope(envelope)

    assert payload['chips'][0] == {'label': 'overall paused', 'tone': 'warn'}
    assert '"paused": "warn"' in html
    assert "const statusTone = statusToneMap[status] || 'info';" in html


def test_running_status_gets_good_tone_in_server_payload_and_refresh_bundle() -> None:
    envelope = sample_envelope()
    envelope['snapshot']['status'] = 'running'

    model = operator_web.build_page_model_from_snapshot_envelope(envelope)
    payload = operator_web.page_model_payload(model)
    html = operator_web.render_html_from_snapshot_envelope(envelope)

    assert payload['chips'][0] == {'label': 'overall running', 'tone': 'good'}
    assert '"running": "good"' in html
    assert 'overall running' in html
    assert "const statusTone = statusToneMap[status] || 'info';" in html


def test_cli_supports_fixture_and_built_in_smoke_render_paths() -> None:
    with tempfile.TemporaryDirectory(prefix='operator-web-') as tmp:
        tmp_path = Path(tmp)
        fixture_path = tmp_path / 'snapshot.json'
        output_path = tmp_path / 'operator.html'
        fixture_path.write_text(json.dumps(sample_envelope(), indent=2) + '\n', encoding='utf-8')

        fixture_proc = subprocess.run(
            [sys.executable, str(ROOT), '--snapshot-file', str(fixture_path), '--output', str(output_path)],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
        assert fixture_proc.returncode == 0, fixture_proc.stderr
        assert 'AgentRunner operator · demo' in output_path.read_text(encoding='utf-8')

        smoke_proc = subprocess.run(
            [sys.executable, str(ROOT), '--smoke-sample'],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
        assert smoke_proc.returncode == 0, smoke_proc.stderr
        assert 'AgentRunner operator · sample-project' in smoke_proc.stdout
        assert 'no mechanics reads' in smoke_proc.stdout


def test_top_level_cli_uses_api_as_the_launch_path_for_browser_work() -> None:
    proc = subprocess.run(
        [sys.executable, '-m', 'agentrunner', 'api', '--help'],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert '--host' in proc.stdout
    assert '--port' in proc.stdout
    assert 'read-only local AgentRunner operator snapshot API' in proc.stdout


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
    test_initial_page_model_json_is_safe_against_script_breakout()
    test_unavailable_renderer_uses_degraded_status_chips()
    test_refresh_model_keeps_paused_status_chip_in_warn_tone()
    test_running_status_gets_good_tone_in_server_payload_and_refresh_bundle()
    test_cli_supports_fixture_and_built_in_smoke_render_paths()
    test_top_level_cli_uses_api_as_the_launch_path_for_browser_work()
    test_top_level_cli_no_longer_exposes_web_command()
    print('ok: browser viewmodel/html seam renders canonical operator snapshots with compact status chips and clearer human summaries while staying on the api-first read-only path')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
