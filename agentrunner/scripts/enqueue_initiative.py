#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/openclaw/projects/agentrunner')
STATE_ROOT = Path('/home/openclaw/.agentrunner/projects')
PROJECTS_ROOT = Path('/home/openclaw/projects')


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


def load_brief_from_args(args) -> tuple[dict, str]:
    provided = []
    if args.manager_brief_path:
        provided.append('path')
    if args.manager_brief_json:
        provided.append('json')
    if args.manager_brief_stdin:
        provided.append('stdin')
    if len(provided) != 1:
        raise SystemExit('provide exactly one manager brief source: --manager-brief-path, --manager-brief-json, or --manager-brief-stdin')

    source = provided[0]
    if source == 'path':
        path = Path(args.manager_brief_path)
        if not path.exists():
            raise SystemExit(f'manager brief path does not exist: {path}')
        try:
            value = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise SystemExit(f'manager brief path must contain valid JSON: {exc}') from exc
        source_label = f'path:{path}'
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
    return value, source_label


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


def ensure_initiative_paths(state_dir: Path, initiative_id: str, branch: str, base: str) -> dict:
    initiative_dir = state_dir / 'initiatives' / initiative_id
    state_path = initiative_dir / 'state.json'
    paths = {
        'initiativeDir': str(initiative_dir),
        'initiativeStatePath': str(state_path),
        'managerBriefPath': str(initiative_dir / 'brief.json'),
        'architectPlanPath': str(initiative_dir / 'plan.json'),
        'managerDecisionPath': str(initiative_dir / 'decision.json'),
    }
    save_json(state_path, {
        'initiativeId': initiative_id,
        'phase': 'design-manager',
        'managerBriefPath': paths['managerBriefPath'],
        'architectPlanPath': paths['architectPlanPath'],
        'managerDecisionPath': paths['managerDecisionPath'],
        'currentSubtaskId': None,
        'completedSubtasks': [],
        'pendingSubtasks': [],
        'branch': branch,
        'base': base,
        'writtenAt': iso_now(),
    })
    return paths


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


def preflight(args, brief: dict, *, state_dir: Path, state: dict, queue: list, repo_path: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_manager_brief(brief, initiative_id=args.initiative_id, project=args.project, branch=args.branch, base=args.base))

    if not repo_path.exists():
        errors.append(f'repo path does not exist: {repo_path}')

    current = state.get('current') if isinstance(state.get('current'), dict) else None
    current_initiative = current.get('queueItem', {}).get('initiative') if current and isinstance(current.get('queueItem'), dict) and isinstance(current.get('queueItem').get('initiative'), dict) else None
    if current_initiative and current_initiative.get('initiativeId') == args.initiative_id:
        errors.append(f'initiative {args.initiative_id} is already running')

    state_pointer = state.get('initiative') if isinstance(state.get('initiative'), dict) else None
    if state_pointer and state_pointer.get('initiativeId') == args.initiative_id:
        errors.append(f'state.json already points at initiative {args.initiative_id}')

    if queue_contains_initiative(queue, args.initiative_id):
        errors.append(f'queue already contains initiative {args.initiative_id}')

    initiative_dir = state_dir / 'initiatives' / args.initiative_id
    if initiative_dir.exists():
        errors.append(f'initiative state already exists: {initiative_dir}')

    kickoff_paths = [
        state_dir / 'results' / f'{args.initiative_id}-manager.json',
        state_dir / 'handoffs' / f'{args.initiative_id}-manager.json',
        state_dir / 'review_findings' / f'{args.initiative_id}-manager.json',
    ]
    existing = [str(path) for path in kickoff_paths if path.exists()]
    if existing:
        errors.append('kickoff artifacts already exist for this initiative: ' + ', '.join(existing))

    return errors


def append_queue_event(state_dir: Path, item: dict) -> None:
    events = state_dir / 'queue_events.ndjson'
    out = state_dir / 'queue.json'
    cmd = [
        'python3',
        str(ROOT / 'agentrunner/scripts/queue_ledger.py'),
        '--events', str(events),
        '--out', str(out),
        '--append',
        '--kind', 'INSERT_FRONT',
        '--item', json.dumps(item, ensure_ascii=False),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description='Preflight and enqueue a new initiative kickoff item.')
    ap.add_argument('--project', required=True)
    ap.add_argument('--initiative-id', required=True)
    ap.add_argument('--branch', required=True)
    ap.add_argument('--base', required=True)
    ap.add_argument('--repo-path')
    ap.add_argument('--state-dir')
    ap.add_argument('--manager-brief-path')
    ap.add_argument('--manager-brief-json')
    ap.add_argument('--manager-brief-stdin', action='store_true')
    args = ap.parse_args()

    brief, brief_source = load_brief_from_args(args)
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

    errors = preflight(args, brief, state_dir=state_dir, state=state or {}, queue=queue, repo_path=repo_path)
    if errors:
        raise SystemExit('preflight failed:\n- ' + '\n- '.join(errors))

    ensure_project_state(state_path, args.project, args.branch)
    paths = ensure_initiative_paths(state_dir, args.initiative_id, args.branch, args.base)

    normalized_brief = dict(brief)
    normalized_brief['initiativeId'] = args.initiative_id
    normalized_brief['project'] = args.project
    normalized_brief['repoPath'] = str(repo_path)
    normalized_brief['baseBranch'] = args.base
    normalized_brief['suggestedBranch'] = args.branch
    normalized_brief['writtenAt'] = normalized_brief.get('writtenAt') or iso_now()
    normalized_brief['briefSource'] = brief_source
    save_json(paths['managerBriefPath'], normalized_brief)

    kickoff_item = build_kickoff_item(project=args.project, repo_path=str(repo_path), initiative_id=args.initiative_id, branch=args.branch, base=args.base)
    append_queue_event(state_dir, kickoff_item)

    state = load_json(state_path, {})
    state['initiative'] = {
        'initiativeId': args.initiative_id,
        'phase': 'design-manager',
        'statePath': paths['initiativeStatePath'],
    }
    state['updatedAt'] = iso_now()
    save_json(state_path, state)

    print(json.dumps({
        'status': 'ok',
        'project': args.project,
        'initiativeId': args.initiative_id,
        'queueItemId': kickoff_item['id'],
        'stateDir': str(state_dir),
        'managerBriefPath': paths['managerBriefPath'],
        'branch': args.branch,
        'base': args.base,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
