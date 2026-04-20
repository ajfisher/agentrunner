#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'agentrunner/scripts/operator_api.py'


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def fetch(url: str, *, method: str = 'GET') -> tuple[int, dict, dict[str, str]]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode('utf-8') if method != 'HEAD' else ''
            data = json.loads(body) if body else {}
            return resp.status, data, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        data = json.loads(body) if body else {}
        return exc.code, data, dict(exc.headers.items())


def fetch_text(url: str, *, method: str = 'GET') -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode('utf-8') if method != 'HEAD' else ''
            return resp.status, body, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        return exc.code, body, dict(exc.headers.items())


def start_api(home: Path, *, port: int) -> subprocess.Popen[str]:
    env = dict(**__import__('os').environ)
    env['HOME'] = str(home)
    return subprocess.Popen(
        ['python3', str(API), '--host', '127.0.0.1', '--port', str(port)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_until_ready(port: int) -> None:
    deadline = time.time() + 5
    url = f'http://127.0.0.1:{port}/v1/operator/snapshot?project=missing'
    last_error = None
    while time.time() < deadline:
        try:
            fetch(url)
            return
        except Exception as exc:  # pragma: no cover - startup timing only
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f'API did not become ready: {last_error}')


def test_snapshot_happy_path(home: Path, *, port: int) -> None:
    state_dir = home / '.agentrunner/projects/demo'
    write_json(state_dir / 'operator_status.json', {
        'project': 'demo',
        'status': 'idle-pending',
        'current': None,
        'queue': {'depth': 1, 'nextIds': ['reviewer-1'], 'preview': []},
        'initiative': None,
        'lastCompleted': None,
        'warnings': [],
        'reconciliation': {'decision': 'idle-pending', 'summary': 'queued work remains', 'reasons': []},
        'updatedAt': '2026-04-19T00:00:00Z',
        'resultHint': None,
    })

    status, data, headers = fetch(f'http://127.0.0.1:{port}/v1/operator/snapshot?project=demo')
    assert status == 200
    assert headers.get('Content-Type', '').startswith('application/json')
    assert data['project'] == 'demo'
    assert data['artifactPath'].endswith('/.agentrunner/projects/demo/operator_status.json')
    assert data['notes'] == []
    assert sorted(data.keys()) == ['artifactPath', 'notes', 'project', 'snapshot']
    assert sorted(data['snapshot'].keys()) == [
        'current',
        'initiative',
        'lastCompleted',
        'project',
        'queue',
        'reconciliation',
        'resultHint',
        'status',
        'updatedAt',
        'warnings',
    ]
    assert data['snapshot']['status'] == 'idle-pending'
    assert data['snapshot']['queue']['nextIds'] == ['reviewer-1']
    assert data['snapshot']['reconciliation']['decision'] == 'idle-pending'
    assert data['snapshot']['updatedAt'] == '2026-04-19T00:00:00Z'


def test_browser_surface_happy_path(home: Path, *, port: int) -> None:
    state_dir = home / '.agentrunner/projects/demo'
    write_json(state_dir / 'operator_status.json', {
        'project': 'demo',
        'status': 'active',
        'current': {'queueItemId': 'developer-1', 'role': 'developer', 'branch': 'feature/demo', 'ageSeconds': 12},
        'queue': {'depth': 1, 'nextIds': ['reviewer-1'], 'preview': [{'queueItemId': 'reviewer-1', 'role': 'reviewer', 'branch': 'feature/demo', 'goal': 'Review it'}]},
        'initiative': {'initiativeId': 'demo-web-ui', 'phase': 'implementation', 'currentSubtaskId': 'minimal-browser-surface'},
        'lastCompleted': {'queueItemId': 'architect-1', 'role': 'architect', 'status': 'ok', 'summary': 'Shaped the readonly page.'},
        'warnings': [{'code': 'snapshot_stale', 'severity': 'warning', 'summary': 'Snapshot may lag slightly.'}],
        'reconciliation': {'decision': 'active', 'summary': 'live state and snapshot agree', 'reasons': []},
        'updatedAt': '2026-04-19T00:00:00Z',
        'resultHint': None,
    })

    status, body, headers = fetch_text(f'http://127.0.0.1:{port}/operator?project=demo')
    assert status == 200
    assert headers.get('Content-Type', '').startswith('text/html')
    assert 'AgentRunner operator · demo' in body
    assert 'Snapshot may be stale relative to recent mechanics activity.' in body
    assert 'developer-1 | developer | feature/demo | age=12s' in body
    assert 'Review it' in body
    assert 'data-refresh-ms="5000"' in body
    assert 'window.setInterval(refreshSnapshot, refreshMs);' in body
    assert "fetch(`/v1/operator/snapshot?project=${encodeURIComponent(project)}`" in body
    assert 'approve' not in body.lower()
    assert 'retry' not in body.lower()
    assert 'enqueue' not in body.lower()


def test_browser_surface_degrades_clearly_when_snapshot_is_missing(port: int) -> None:
    status, body, headers = fetch_text(f'http://127.0.0.1:{port}/operator?project=missing')
    assert status == 404
    assert headers.get('Content-Type', '').startswith('text/html')
    assert 'snapshot unavailable' in body.lower()
    assert 'Canonical operator snapshot is missing or malformed' in body


def test_missing_project_is_a_clear_400(port: int) -> None:
    status, data, _ = fetch(f'http://127.0.0.1:{port}/v1/operator/snapshot')
    assert status == 400
    assert data['error'] == 'missing_project'


def test_invalid_project_name_is_a_clear_400(port: int) -> None:
    status, data, _ = fetch(f'http://127.0.0.1:{port}/v1/operator/snapshot?project=../../nope')
    assert status == 400
    assert data['error'] == 'invalid_project'


def test_missing_snapshot_is_a_clear_404(port: int) -> None:
    status, data, _ = fetch(f'http://127.0.0.1:{port}/v1/operator/snapshot?project=missing')
    assert status == 404
    assert data['error'] == 'snapshot_unavailable'
    assert data['details']['project'] == 'missing'


def test_unknown_path_is_a_clear_404(port: int) -> None:
    status, data, _ = fetch(f'http://127.0.0.1:{port}/v1/nope?project=demo')
    assert status == 404
    assert data['error'] == 'not_found'


def test_write_method_is_rejected_with_405(port: int) -> None:
    status, data, headers = fetch(f'http://127.0.0.1:{port}/v1/operator/snapshot?project=demo', method='POST')
    assert status == 405
    assert data['error'] == 'method_not_allowed'
    assert 'GET' in headers.get('Allow', '')
    assert 'HEAD' in headers.get('Allow', '')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='operator-api-home-') as tmp:
        home = Path(tmp)
        port = 18765
        proc = start_api(home, port=port)
        try:
            wait_until_ready(port)
            test_snapshot_happy_path(home, port=port)
            test_browser_surface_happy_path(home, port=port)
            test_browser_surface_degrades_clearly_when_snapshot_is_missing(port)
            test_missing_project_is_a_clear_400(port)
            test_invalid_project_name_is_a_clear_400(port)
            test_missing_snapshot_is_a_clear_404(port)
            test_unknown_path_is_a_clear_404(port)
            test_write_method_is_rejected_with_405(port)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    print('ok: operator API serves read-only snapshot JSON with explicit 4xx responses for bad input and no write endpoints')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
