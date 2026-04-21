#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    from .status_artifact import build_status_artifact
except ImportError:  # pragma: no cover - script-mode fallback
    from status_artifact import build_status_artifact

ROOT = Path('/home/openclaw/projects/agentrunner')
INVOKER = ROOT / 'agentrunner/scripts/invoker.py'


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def should_poll_project(state_dir: Path) -> bool:
    state = load_json(state_dir / 'state.json', {})
    queue = load_json(state_dir / 'queue.json', [])
    running = bool(state.get('running'))
    if running or bool(queue):
        return True

    try:
        artifact = build_status_artifact(state_dir)
    except Exception:
        return False

    closure = artifact.get('closure') if isinstance(artifact, dict) else None
    if not isinstance(closure, dict):
        return False

    handoff_safe = closure.get('handoffSafe')
    return handoff_safe is False


def canonical_project_name(state_dir: Path) -> str:
    state = load_json(state_dir / 'state.json', {})
    project = state.get('project') if isinstance(state, dict) else None
    if isinstance(project, str) and project.strip():
        return project
    return state_dir.name


def find_projects(projects_root: Path, explicit: list[str], explicit_state_dirs: list[str]) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    for raw in explicit_state_dirs:
        state_dir = Path(raw)
        if (state_dir / 'state.json').exists() and (state_dir / 'queue.json').exists():
            resolved = state_dir.resolve()
            if resolved not in seen:
                out.append((canonical_project_name(state_dir), state_dir))
                seen.add(resolved)

    if explicit:
        for name in explicit:
            p = projects_root / name
            if (p / 'state.json').exists() and (p / 'queue.json').exists():
                resolved = p.resolve()
                if resolved not in seen:
                    out.append((name, p))
                    seen.add(resolved)
        return out

    if explicit_state_dirs:
        return out

    if not projects_root.exists():
        return out
    for child in sorted(projects_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / 'state.json').exists() and (child / 'queue.json').exists():
            resolved = child.resolve()
            if resolved not in seen:
                out.append((child.name, child))
                seen.add(resolved)
    return out


def run_invoker(project: str, state_dir: Path, *, announce: bool, channel: str | None, to: str | None, timeout_seconds: int, dry_run: bool) -> int:
    cmd = [
        'python3',
        str(INVOKER),
        '--project',
        project,
        '--state-dir',
        str(state_dir),
        '--timeout-seconds',
        str(timeout_seconds),
    ]
    if announce:
        cmd.append('--announce')
        if channel:
            cmd += ['--channel', channel]
        if to:
            cmd += ['--to', to]

    if dry_run:
        print('[dry-run]', ' '.join(cmd))
        return 0

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f'[error] {project}: invoker rc={proc.returncode}')
        if proc.stderr.strip():
            print(proc.stderr.strip())
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description='Reliability poller for agentrunner project state dirs.')
    ap.add_argument('--projects-root', default='/home/openclaw/.agentrunner/projects')
    ap.add_argument('--project', action='append', default=[], help='Project name(s) to poll; if omitted, poll all detected projects')
    ap.add_argument('--state-dir', action='append', default=[], help='Explicit state dir(s) to poll, even if they do not match the projects-root/project-name layout')
    ap.add_argument('--announce', action='store_true', help='Pass through announce mode to invoker (off by default)')
    ap.add_argument('--channel', default=None)
    ap.add_argument('--to', default=None)
    ap.add_argument('--timeout-seconds', type=int, default=540)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    projects_root = Path(args.projects_root)
    projects = find_projects(projects_root, args.project, args.state_dir)
    if not projects:
        print('No projects found to poll.')
        return 0

    attempted = 0
    for name, state_dir in projects:
        if not should_poll_project(state_dir):
            continue
        attempted += 1
        run_invoker(
            name,
            state_dir,
            announce=args.announce,
            channel=args.channel,
            to=args.to,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )

    print(f'Polled {attempted} project(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
