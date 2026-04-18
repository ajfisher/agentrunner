#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from initiative_coordinator import append_queue_event, ensure_initiative_paths

ROOT = Path('/home/openclaw/projects/agentrunner')
STATE_ROOT = Path('/home/openclaw/.agentrunner/projects')
PROJECTS_ROOT = Path('/home/openclaw/projects')
RELIABILITY_POLL = ROOT / 'agentrunner/scripts/reliability_poll.py'


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


def parse_json_object(raw: str, *, label: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'{label} must be valid JSON: {exc}') from exc
    if not isinstance(value, dict):
        raise SystemExit(f'{label} must be a JSON object')
    return value


def load_brief_from_args(args) -> tuple[dict, str, Path | None]:
    provided = []
    if args.manager_brief_path:
        provided.append('path')
    if args.manager_brief_artifact_path:
        provided.append('artifact')
    if args.manager_brief_json:
        provided.append('json')
    if args.manager_brief_stdin:
        provided.append('stdin')
    if len(provided) != 1:
        raise SystemExit('provide exactly one manager brief source: --manager-brief-path, --manager-brief-artifact-path, --manager-brief-json, or --manager-brief-stdin')

    source = provided[0]
    source_path: Path | None = None
    if source == 'path':
        source_path = Path(args.manager_brief_path)
        if not source_path.exists():
            raise SystemExit(f'manager brief path does not exist: {source_path}')
        try:
            value = json.loads(source_path.read_text())
        except json.JSONDecodeError as exc:
            raise SystemExit(f'manager brief path must contain valid JSON: {exc}') from exc
        source_label = f'path:{source_path}'
    elif source == 'artifact':
        source_path = Path(args.manager_brief_artifact_path)
        if not source_path.exists():
            raise SystemExit(f'manager brief artifact path does not exist: {source_path}')
        try:
            value = json.loads(source_path.read_text())
        except json.JSONDecodeError as exc:
            raise SystemExit(f'manager brief artifact path must contain valid JSON: {exc}') from exc
        source_label = f'artifact:{source_path}'
    elif source == 'json':
        value = parse_json_object(args.manager_brief_json, label='--manager-brief-json')
        source_label = 'json:arg'
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            raise SystemExit('--manager-brief-stdin was set but stdin was empty')
        value = parse_json_object(raw, label='stdin manager brief')
        source_label = 'json:stdin'

    if not isinstance(value, dict):
        raise SystemExit('manager brief must be a JSON object')
    return value, source_label, source_path


def validate_manager_brief(brief: dict, *, initiative_id: str, project: str, branch: str, base: str) -> list[str]:
    errors: list[str] = []
    required_strings = ['title', 'objective']
    for field in required_strings:
        value = brief.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f'brief.{field} must be a non-empty string')

    for field in ['desiredOutcomes', 'definitionOfDone']:
        value = brief.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f'brief.{field} must be a non-empty list')

    constraints = brief.get('constraints')
    if constraints is not None and not isinstance(constraints, dict):
        errors.append('brief.constraints must be an object when present')

    if brief.get('initiativeId') not in (None, initiative_id):
        errors.append(f'brief.initiativeId mismatch: expected {initiative_id!r}')
    if brief.get('project') not in (None, project):
        errors.append(f'brief.project mismatch: expected {project!r}')
    if brief.get('suggestedBranch') not in (None, branch):
        errors.append(f'brief.suggestedBranch mismatch: expected {branch!r}')
    if brief.get('baseBranch') not in (None, base):
        errors.append(f'brief.baseBranch mismatch: expected {base!r}')

    return errors


def ensure_project_state(state_path: Path, project: str, branch: str) -> None:
    if state_path.exists():
        return
    save_json(state_path, {
        'project': project,
        'running': False,
        'updatedAt': iso_now(),
        'current': None,
        'limits': {'maxExtraDevTurns': 1},
        'policy': {'extraDevTurnReset': 'on_branch_change'},
        'runtime': {'extraDevTurnsUsed': 0, 'lastBranch': branch},
    })


def build_kickoff_item(*, project: str, repo_path: str | None, initiative_id: str, branch: str, base: str) -> dict:
    return {
        'id': f'{initiative_id}-manager',
        'project': project,
        'role': 'manager',
        'createdAt': iso_now(),
        'repo_path': repo_path,
        'branch': branch,
        'base': base,
        'goal': f'Write the Manager kickoff brief for initiative {initiative_id}. Read the provided manager brief source, normalize it to the initiative-local brief artifact, and make the initiative ready for Architect planning.',
        'checks': [],
        'constraints': {'initiativePhase': 'design-manager'},
        'contextFiles': [],
        'initiative': {
            'initiativeId': initiative_id,
            'phase': 'design-manager',
            'branch': branch,
            'base': base,
        },
    }


def queue_contains_initiative(queue: list, initiative_id: str) -> bool:
    for item in queue:
        if not isinstance(item, dict):
            continue
        initiative = item.get('initiative') if isinstance(item.get('initiative'), dict) else None
        if initiative and initiative.get('initiativeId') == initiative_id:
            return True
        if item.get('id') == f'{initiative_id}-manager':
            return True
    return False


def kickoff_status(state: dict, queue: list, *, initiative_id: str, state_dir: Path) -> tuple[str, str] | None:
    current = state.get('current') if isinstance(state.get('current'), dict) else None
    queue_item = current.get('queueItem') if current and isinstance(current.get('queueItem'), dict) else None
    current_initiative = queue_item.get('initiative') if queue_item and isinstance(queue_item.get('initiative'), dict) else None
    if current_initiative and current_initiative.get('initiativeId') == initiative_id:
        return 'noop', f'kickoff already active for initiative {initiative_id} ({queue_item.get("id") or f"{initiative_id}-manager"})'

    if queue_contains_initiative(queue, initiative_id):
        return 'noop', f'kickoff already pending for initiative {initiative_id} ({initiative_id}-manager)'

    initiative_dir = state_dir / 'initiatives' / initiative_id
    if initiative_dir.exists():
        return 'noop', f'initiative already exists at {initiative_dir}'

    kickoff_paths = [
        state_dir / 'results' / f'{initiative_id}-manager.json',
        state_dir / 'handoffs' / f'{initiative_id}-manager.json',
        state_dir / 'review_findings' / f'{initiative_id}-manager.json',
    ]
    existing = [str(path) for path in kickoff_paths if path.exists()]
    if existing:
        return 'noop', 'kickoff artifacts already exist for this initiative: ' + ', '.join(existing)

    return None


def active_initiative_conflict(state: dict, *, initiative_id: str) -> str | None:
    state_pointer = state.get('initiative') if isinstance(state.get('initiative'), dict) else None
    if not state_pointer:
        return None
    active_id = state_pointer.get('initiativeId')
    if not isinstance(active_id, str) or not active_id.strip():
        return None
    if active_id == initiative_id:
        return f'state.json already points at initiative {initiative_id}'
    return f'state.json already points at active initiative {active_id}; refusing to enqueue {initiative_id}'


def preflight(args, brief: dict, *, state_dir: Path, state: dict, queue: list, repo_path: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_manager_brief(brief, initiative_id=args.initiative_id, project=args.project, branch=args.branch, base=args.base))

    if not repo_path.exists():
        errors.append(f'repo path does not exist: {repo_path}')

    state_conflict = active_initiative_conflict(state, initiative_id=args.initiative_id)
    if state_conflict:
        errors.append(state_conflict)

    if args.poll_after_enqueue and not RELIABILITY_POLL.exists():
        errors.append(f'reliability poll script does not exist: {RELIABILITY_POLL}')

    return errors


def materialize_manager_brief(*, brief: dict, brief_source: str, brief_source_path: Path | None, destination_path: Path, args, repo_path: Path) -> tuple[Path, str]:
    if brief_source.startswith('artifact:'):
        if brief_source_path is None:
            raise SystemExit('internal error: artifact source path missing')
        source_path = brief_source_path.resolve()
        destination = destination_path.resolve()
        if source_path != destination:
            raise SystemExit(
                '--manager-brief-artifact-path must point at the initiative-local brief artifact path for this enqueue run; '
                'use --manager-brief-path to copy a brief file into place'
            )
        return destination_path, 'consumed existing initiative brief artifact'

    normalized_brief = dict(brief)
    normalized_brief['initiativeId'] = args.initiative_id
    normalized_brief['project'] = args.project
    normalized_brief['repoPath'] = str(repo_path)
    normalized_brief['baseBranch'] = args.base
    normalized_brief['suggestedBranch'] = args.branch
    normalized_brief['writtenAt'] = normalized_brief.get('writtenAt') or iso_now()
    normalized_brief['briefSource'] = brief_source
    save_json(destination_path, normalized_brief)

    if brief_source.startswith('path:'):
        return destination_path, 'copied brief file into initiative brief artifact'
    return destination_path, 'wrote normalized initiative brief artifact'


def run_reliability_poll(*, project: str, state_dir: Path) -> tuple[str, list[str]]:
    cmd = [
        'python3',
        str(RELIABILITY_POLL),
        '--projects-root',
        str(state_dir.parent),
        '--project',
        project,
        '--state-dir',
        str(state_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    lines: list[str] = []
    if proc.stdout.strip():
        lines.extend(line.strip() for line in proc.stdout.splitlines() if line.strip())
    if proc.stderr.strip():
        lines.extend(line.strip() for line in proc.stderr.splitlines() if line.strip())
    if proc.returncode != 0:
        raise SystemExit(
            'enqueue completed, but the requested reliability poll failed '
            f'(rc={proc.returncode}): ' + (' | '.join(lines) if lines else 'no output')
        )
    summary = lines[-1] if lines else 'Polled 1 project(s).'
    return summary, lines


def main() -> int:
    ap = argparse.ArgumentParser(description='Preflight and enqueue a new initiative kickoff item.')
    ap.add_argument('--project', required=True)
    ap.add_argument('--initiative-id', required=True)
    ap.add_argument('--branch', required=True)
    ap.add_argument('--base', required=True)
    ap.add_argument('--repo-path')
    ap.add_argument('--state-dir')
    ap.add_argument('--manager-brief-path', help='Path to a brief JSON file to copy into the initiative brief artifact')
    ap.add_argument('--manager-brief-artifact-path', help='Path to an already-prepared initiative brief artifact to consume in place')
    ap.add_argument('--manager-brief-json')
    ap.add_argument('--manager-brief-stdin', action='store_true')
    ap.add_argument('--poll-after-enqueue', action='store_true', help='Run one reliability_poll.py pass for this project after enqueue completes')
    args = ap.parse_args()

    brief, brief_source, brief_source_path = load_brief_from_args(args)
    state_dir = Path(args.state_dir) if args.state_dir else (STATE_ROOT / args.project)
    repo_path = Path(args.repo_path) if args.repo_path else (PROJECTS_ROOT / args.project)
    state_path = state_dir / 'state.json'
    queue_path = state_dir / 'queue.json'

    state = load_json(state_path, {})
    queue = load_json(queue_path, [])
    if not isinstance(queue, list):
        raise SystemExit('queue.json must contain a JSON array when present')
    if state and not isinstance(state, dict):
        raise SystemExit('state.json must contain a JSON object when present')

    existing = kickoff_status(state or {}, queue, initiative_id=args.initiative_id, state_dir=state_dir)
    if existing:
        status, message = existing
        print(json.dumps({
            'status': status,
            'project': args.project,
            'initiativeId': args.initiative_id,
            'message': message,
            'stateDir': str(state_dir),
            'branch': args.branch,
            'base': args.base,
            'pollAfterEnqueue': False,
        }, indent=2, ensure_ascii=False))
        return 0

    errors = preflight(args, brief, state_dir=state_dir, state=state or {}, queue=queue, repo_path=repo_path)
    if errors:
        raise SystemExit('preflight failed:\n- ' + '\n- '.join(errors))

    ensure_project_state(state_path, args.project, args.branch)
    paths = ensure_initiative_paths(str(state_dir), {
        'initiativeId': args.initiative_id,
        'phase': 'design-manager',
        'branch': args.branch,
        'base': args.base,
    })

    manager_brief_path, brief_action = materialize_manager_brief(
        brief=brief,
        brief_source=brief_source,
        brief_source_path=brief_source_path,
        destination_path=Path(paths['managerBriefPath']),
        args=args,
        repo_path=repo_path,
    )

    kickoff_item = build_kickoff_item(project=args.project, repo_path=str(repo_path), initiative_id=args.initiative_id, branch=args.branch, base=args.base)
    append_queue_event(str(state_dir), 'INSERT_FRONT', item=kickoff_item)

    state = load_json(state_path, {})
    state['initiative'] = {
        'initiativeId': args.initiative_id,
        'phase': 'design-manager',
        'statePath': paths['initiativeStatePath'],
    }
    state['updatedAt'] = iso_now()
    save_json(state_path, state)

    poll_summary = None
    poll_details: list[str] = []
    if args.poll_after_enqueue:
        poll_summary, poll_details = run_reliability_poll(project=args.project, state_dir=state_dir)

    print(json.dumps({
        'status': 'ok',
        'project': args.project,
        'initiativeId': args.initiative_id,
        'queueItemId': kickoff_item['id'],
        'stateDir': str(state_dir),
        'managerBriefPath': str(manager_brief_path),
        'briefAction': brief_action,
        'branch': args.branch,
        'base': args.base,
        'pollAfterEnqueue': bool(args.poll_after_enqueue),
        'pollSummary': poll_summary,
        'pollDetails': poll_details,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
