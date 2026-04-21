#!/usr/bin/env python3
"""Small read-only terminal surface for the canonical AgentRunner operator snapshot.

This module stays deliberately bounded:
- local terminal only
- read-only over the canonical operator snapshot/read model
- no queue/state mutation actions
- stdlib-only refresh/render loop so the first contract does not add a heavy UI runtime

It supports three useful modes:
- ``--once``: render a single text snapshot and exit
- ``--smoke-sample`` / ``--snapshot-file``: render against a local fixture/sample without live mechanics
- interactive curses surface: attachable readonly panes with refresh/navigation/quit only
"""
from __future__ import annotations

import argparse
import curses
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from agentrunner.scripts import operator_data

DEFAULT_REFRESH_SECONDS = 2.0
MIN_REFRESH_SECONDS = 0.2
KEY_QUIT = {ord("q"), ord("Q")}
KEY_REFRESH = {ord("r"), ord("R")}
KEY_NEXT = {9, curses.KEY_RIGHT, curses.KEY_DOWN, ord("l"), ord("j")}
KEY_PREV = {curses.KEY_LEFT, curses.KEY_UP, ord("h"), ord("k")}
KEY_SCROLL_DOWN = {curses.KEY_NPAGE, ord("J")}
KEY_SCROLL_UP = {curses.KEY_PPAGE, ord("K")}


@dataclass(frozen=True)
class Pane:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ScreenState:
    header_lines: tuple[str, ...]
    panes: tuple[Pane, ...]
    footer_hint: str


SAMPLE_SNAPSHOT: dict[str, object] = {
    "contract": dict(operator_data.OPERATOR_SNAPSHOT_CONTRACT),
    "project": "sample-project",
    "status": "running",
    "updatedAt": "2026-04-20T10:12:00+10:00",
    "current": {
        "queueItemId": "sample-dev-001",
        "role": "developer",
        "branch": "feature/example",
        "startedAt": "2026-04-20T10:03:00+10:00",
        "ageSeconds": 540,
        "runId": "run-sample-1",
        "sessionKey": "session-sample-1",
        "resultPath": "/tmp/sample-dev-001.json",
    },
    "queue": {
        "depth": 3,
        "nextIds": ["sample-review-002", "sample-merge-003"],
        "preview": [
            {
                "queueItemId": "sample-review-002",
                "role": "reviewer",
                "branch": "feature/example",
                "goal": "Review the readonly TUI surface",
            },
            {
                "queueItemId": "sample-merge-003",
                "role": "merger",
                "branch": "feature/example",
                "goal": "Merge after checks pass",
            },
        ],
    },
    "initiative": {
        "initiativeId": "agentrunner-operator-tui",
        "phase": "implementation",
        "currentSubtaskId": "operator-tui-readonly-surface",
        "branch": "feature/agentrunner/operator-tui",
        "base": "main",
        "statePath": "/tmp/initiative-state.json",
    },
    "lastCompleted": {
        "queueItemId": "sample-arch-000",
        "role": "architect",
        "status": "ok",
        "summary": "Proposed a minimal readonly TUI adapter over the canonical snapshot.",
        "endedAt": "2026-04-20T09:58:00+10:00",
        "runId": "run-sample-0",
        "sessionKey": "session-sample-0",
        "branch": "feature/agentrunner/operator-tui",
        "base": "main",
    },
    "warnings": [
        {
            "code": "snapshot_stale",
            "severity": "warning",
            "summary": "Snapshot is older than the last observed tick.",
            "details": "Operator may want to hit refresh or inspect recent mechanics runs.",
        }
    ],
    "resultHint": "Developer surfaced a fixture-backed smoke path for the readonly surface.",
}


def _clip(value: object, limit: int = 120) -> str:
    text = operator_data.clip(value, limit)
    return text if text else "-"


def _wrap_text(text: str, width: int) -> list[str]:
    width = max(8, width)
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _wrap_block(lines: Iterable[str], width: int) -> list[str]:
    wrapped: list[str] = []
    for line in lines:
        raw = str(line)
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw[indent:]
        if not body:
            wrapped.append("")
            continue
        for idx, segment in enumerate(_wrap_text(body, max(8, width - indent))):
            prefix = " " * indent if idx == 0 else " " * indent
            wrapped.append(f"{prefix}{segment}".rstrip())
    return wrapped


def _pane(title: str, lines: Iterable[str]) -> Pane:
    return Pane(title=title, lines=tuple(str(line) for line in lines))


def _notes_lines(notes: Iterable[str]) -> tuple[str, ...]:
    normalized = [str(note) for note in notes if str(note).strip()]
    return tuple(normalized or ["No snapshot notes."])


def build_screen_state(project: str, resolved: operator_data.OperatorSnapshotRead) -> ScreenState:
    view = operator_data.build_operator_screen_view(project, resolved, queue_preview=5)
    artifact = resolved.artifact or {}
    snapshot_current = operator_data.snapshot_current(artifact) or {}
    snapshot_initiative = operator_data.snapshot_initiative(artifact) or {}
    snapshot_last_completed = operator_data.snapshot_last_completed(artifact) or {}
    warnings = operator_data.snapshot_warnings(artifact)
    result_hint = operator_data.snapshot_result_hint(artifact)
    runtime = operator_data.snapshot_runtime(artifact) or {}
    reconciliation = operator_data.snapshot_reconciliation(artifact) or {}

    header_lines = (
        f"AgentRunner operator TUI · project={view.project}",
        view.mode_line,
        view.status_line,
        view.updated_line,
    )

    project_status_lines = [
        view.status_line,
        view.updated_line,
        f"artifact path: {resolved.artifact_path}",
        f"state dir: {resolved.state_dir}",
    ]
    if runtime:
        project_status_lines.append(
            f"runtime: extraDevTurnsUsed={_clip(runtime.get('extraDevTurnsUsed'))} lastBranch={_clip(runtime.get('lastBranch'))}"
        )
    if reconciliation:
        project_status_lines.append(
            f"reconciliation: decision={_clip(reconciliation.get('decision'))} reasons={len(reconciliation.get('reasons') or [])}"
        )

    current_lines = [
        f"queue item: {_clip(snapshot_current.get('queueItemId'))}",
        f"role: {_clip(snapshot_current.get('role'))}",
        f"branch: {_clip(snapshot_current.get('branch'))}",
        f"started: {_clip(snapshot_current.get('startedAt'))}",
        f"age seconds: {_clip(snapshot_current.get('ageSeconds'))}",
        f"run id: {_clip(snapshot_current.get('runId'))}",
        f"session: {_clip(snapshot_current.get('sessionKey'))}",
        f"result path: {_clip(snapshot_current.get('resultPath'))}",
    ]

    queue_lines = list(next(section.lines for section in view.sections if section.title == "queue"))

    initiative_lines = [
        f"initiative id: {_clip(snapshot_initiative.get('initiativeId'))}",
        f"phase: {_clip(snapshot_initiative.get('phase'))}",
        f"subtask: {_clip(snapshot_initiative.get('currentSubtaskId'))}",
        f"branch: {_clip(snapshot_initiative.get('branch'))}",
        f"base: {_clip(snapshot_initiative.get('base'))}",
        f"state path: {_clip(snapshot_initiative.get('statePath'))}",
    ]

    warning_lines: list[str] = []
    if warnings:
        for warning in warnings:
            first = f"[{_clip(warning.get('severity'), 16)}] {_clip(warning.get('code'), 40)}"
            summary = _clip(warning.get("summary"), 120)
            details = warning.get("details")
            warning_lines.append(first)
            warning_lines.append(f"  {summary}")
            if details:
                warning_lines.append(f"  details: {_clip(details, 120)}")
    else:
        warning_lines.append("No warnings.")

    result_lines = [
        f"hint: {_clip(result_hint or 'No result hint available.', 160)}",
        f"last item: {_clip(snapshot_last_completed.get('queueItemId'))}",
        f"last role: {_clip(snapshot_last_completed.get('role'))}",
        f"last status: {_clip(snapshot_last_completed.get('status'))}",
        f"last summary: {_clip(snapshot_last_completed.get('summary'), 160)}",
    ]

    panes = (
        _pane("Project status", project_status_lines),
        _pane("Current item", current_lines),
        _pane("Queue preview", queue_lines),
        _pane("Initiative context", initiative_lines),
        _pane("Warnings", warning_lines),
        _pane("Result hints", result_lines),
        _pane("Snapshot notes", _notes_lines(resolved.notes)),
    )
    return ScreenState(
        header_lines=header_lines,
        panes=panes,
        footer_hint="tab/←/→/↑/↓ move · pgup/pgdn scroll · r refresh · q quit · readonly surface",
    )


def _lines_for_snapshot(project: str, resolved: operator_data.OperatorSnapshotRead) -> list[str]:
    state = build_screen_state(project, resolved)
    lines = list(state.header_lines)
    for pane in state.panes:
        lines.append("")
        lines.append(f"{pane.title}:")
        lines.extend(f"- {line}" for line in pane.lines)
    lines.append("")
    lines.append(f"controls: {state.footer_hint}")
    return lines


def render_snapshot(project: str, resolved: operator_data.OperatorSnapshotRead) -> str:
    return "\n".join(_lines_for_snapshot(project, resolved)) + "\n"


def read_snapshot_file(path: str | Path) -> operator_data.OperatorSnapshotRead:
    snapshot_path = Path(path).expanduser().resolve()
    artifact = operator_data.parse_artifact(snapshot_path)
    project = operator_data.snapshot_project(artifact) or snapshot_path.stem
    return operator_data.OperatorSnapshotRead(
        state_dir=snapshot_path.parent,
        artifact_path=snapshot_path,
        artifact=artifact,
        notes=(f"info: loaded snapshot fixture from {snapshot_path}",),
    )


def sample_snapshot(project: str = "sample-project") -> operator_data.OperatorSnapshotRead:
    artifact = dict(SAMPLE_SNAPSHOT)
    artifact["project"] = project
    return operator_data.OperatorSnapshotRead(
        state_dir=Path.cwd(),
        artifact_path=Path.cwd() / f"{project}-operator_status.sample.json",
        artifact=artifact,
        notes=("info: using built-in sample snapshot (no mechanics reads)",),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the optional local read-only AgentRunner terminal UI"
    )
    parser.add_argument("--project", help="Project id to inspect")
    parser.add_argument("--state-dir", help="Explicit runtime state dir override")
    parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Refresh cadence for the local redraw loop (default: {DEFAULT_REFRESH_SECONDS})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render a single snapshot and exit (useful for smoke tests)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear the terminal between redraws in non-curses render mode",
    )
    parser.add_argument(
        "--rebuild-missing",
        action="store_true",
        help="If operator_status.json is missing, do a bounded manual rebuild from mechanics files",
    )
    parser.add_argument(
        "--rebuild-malformed",
        action="store_true",
        help="If operator_status.json is malformed, do a bounded manual rebuild from mechanics files",
    )
    parser.add_argument(
        "--write-rebuild",
        action="store_true",
        help="Persist a bounded rebuild back to operator_status.json",
    )
    parser.add_argument(
        "--snapshot-file",
        help="Load a snapshot fixture JSON file instead of reading a live project state dir",
    )
    parser.add_argument(
        "--smoke-sample",
        action="store_true",
        help="Render against a built-in sample snapshot without live mechanics",
    )
    parser.add_argument(
        "--text-watch",
        action="store_true",
        help="Use the plain text redraw loop instead of the curses TUI",
    )
    return parser


def _clear_screen() -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def _load(args: argparse.Namespace) -> operator_data.OperatorSnapshotRead:
    if args.snapshot_file:
        return read_snapshot_file(args.snapshot_file)
    if args.smoke_sample:
        project = args.project or "sample-project"
        return sample_snapshot(project)
    if not args.project and not args.state_dir:
        raise operator_data.CliUsageError("provide --project or --state-dir (or use --smoke-sample/--snapshot-file)")
    return operator_data.resolve_operator_snapshot(
        project=args.project,
        state_dir=args.state_dir,
        rebuild_missing=args.rebuild_missing,
        rebuild_malformed=args.rebuild_malformed,
        write_rebuild=args.write_rebuild,
    )


def _draw_box(stdscr: curses.window, y: int, x: int, h: int, w: int, *, selected: bool, title: str) -> None:
    attr = curses.A_BOLD | (curses.A_REVERSE if selected else 0)
    stdscr.addnstr(y, x, "+" + "-" * max(0, w - 2) + "+", w, attr)
    for row in range(1, max(1, h - 1)):
        stdscr.addnstr(y + row, x, "|" + " " * max(0, w - 2) + "|", w)
    if h > 1:
        stdscr.addnstr(y + h - 1, x, "+" + "-" * max(0, w - 2) + "+", w, attr)
    label = f" {title} "
    if w > 4:
        stdscr.addnstr(y, x + 2, label, max(0, w - 4), attr)


def _render_pane(
    stdscr: curses.window,
    pane: Pane,
    *,
    y: int,
    x: int,
    h: int,
    w: int,
    selected: bool,
    scroll: int,
) -> None:
    _draw_box(stdscr, y, x, h, w, selected=selected, title=pane.title)
    inner_w = max(8, w - 4)
    wrapped = _wrap_block(pane.lines, inner_w)
    max_scroll = max(0, len(wrapped) - max(0, h - 2))
    offset = min(max(0, scroll), max_scroll)
    visible = wrapped[offset : offset + max(0, h - 2)]
    attr = curses.A_BOLD if selected else curses.A_NORMAL
    for idx, line in enumerate(visible, start=1):
        stdscr.addnstr(y + idx, x + 2, line, inner_w, attr)
    if max_scroll > 0:
        marker = f"{offset + 1}-{min(len(wrapped), offset + max(0, h - 2))}/{len(wrapped)}"
        stdscr.addnstr(y + h - 1, max(x + 2, x + w - len(marker) - 2), marker, len(marker), curses.A_DIM)


def _render_screen(
    stdscr: curses.window,
    screen: ScreenState,
    *,
    selected_index: int,
    scroll_offsets: list[int],
    refresh_seconds: float,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    if height < 14 or width < 72:
        stdscr.addnstr(0, 0, "Terminal too small for operator TUI. Resize to at least 72x14.", max(1, width - 1), curses.A_BOLD)
        stdscr.addnstr(2, 0, screen.footer_hint, max(1, width - 1), curses.A_DIM)
        stdscr.refresh()
        return

    line_y = 0
    for header in screen.header_lines:
        stdscr.addnstr(line_y, 0, header, max(1, width - 1), curses.A_BOLD if line_y == 0 else curses.A_NORMAL)
        line_y += 1
    stdscr.hline(line_y, 0, ord("-"), max(1, width - 1))
    line_y += 1

    grid_top = line_y
    footer_y = height - 2
    grid_height = max(6, footer_y - grid_top)
    left_w = max(24, width // 2)
    right_w = max(24, width - left_w)
    col_gap = 0
    pane_h = max(3, grid_height // 3)
    last_h = grid_height - (pane_h * 2)
    pane_heights = (pane_h, pane_h, max(3, last_h))

    positions: list[tuple[int, int, int, int]] = []
    cy = grid_top
    for h in pane_heights:
        positions.append((cy, 0, h, left_w))
        cy += h
    cy = grid_top
    for h in pane_heights:
        positions.append((cy, left_w + col_gap, h, right_w))
        cy += h
    if len(screen.panes) > len(positions):
        positions.append((footer_y - 3, 0, 3, width))

    for idx, pane in enumerate(screen.panes[: len(positions)]):
        y, x, h, w = positions[idx]
        _render_pane(
            stdscr,
            pane,
            y=y,
            x=x,
            h=h,
            w=w,
            selected=idx == selected_index,
            scroll=scroll_offsets[idx],
        )

    footer = f"{screen.footer_hint} · refresh={refresh_seconds:g}s"
    stdscr.addnstr(height - 2, 0, footer, max(1, width - 1), curses.A_DIM)
    selected_name = screen.panes[selected_index].title if screen.panes else "-"
    stdscr.addnstr(height - 1, 0, f"selected pane: {selected_name}", max(1, width - 1), curses.A_DIM)
    stdscr.refresh()


def run_curses_ui(args: argparse.Namespace) -> int:
    def _curses_main(stdscr: curses.window) -> int:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(int(max(MIN_REFRESH_SECONDS, args.refresh_seconds) * 1000))
        selected = 0
        scroll_offsets: list[int] = []
        last_screen: ScreenState | None = None

        while True:
            resolved = _load(args)
            last_screen = build_screen_state(args.project or operator_data.snapshot_project(resolved.artifact or {}) or resolved.state_dir.name, resolved)
            if len(scroll_offsets) != len(last_screen.panes):
                scroll_offsets = [0 for _ in last_screen.panes]
                selected = min(selected, max(0, len(last_screen.panes) - 1))
            _render_screen(
                stdscr,
                last_screen,
                selected_index=selected,
                scroll_offsets=scroll_offsets,
                refresh_seconds=max(MIN_REFRESH_SECONDS, args.refresh_seconds),
            )
            key = stdscr.getch()
            if key == -1:
                continue
            if key in KEY_QUIT:
                return 0
            if key in KEY_REFRESH:
                continue
            if key in KEY_NEXT and last_screen.panes:
                selected = (selected + 1) % len(last_screen.panes)
                continue
            if key in KEY_PREV and last_screen.panes:
                selected = (selected - 1) % len(last_screen.panes)
                continue
            if key in KEY_SCROLL_DOWN and last_screen.panes:
                scroll_offsets[selected] += 3
                continue
            if key in KEY_SCROLL_UP and last_screen.panes:
                scroll_offsets[selected] = max(0, scroll_offsets[selected] - 3)
                continue

    try:
        return curses.wrapper(_curses_main)
    except KeyboardInterrupt:
        return 0


def run_text_watch(args: argparse.Namespace) -> int:
    try:
        while True:
            if not args.no_clear:
                _clear_screen()
            resolved = _load(args)
            project = args.project or operator_data.snapshot_project(resolved.artifact or {}) or resolved.state_dir.name
            sys.stdout.write(render_snapshot(project, resolved))
            sys.stdout.flush()
            time.sleep(args.refresh_seconds)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.refresh_seconds <= 0:
        parser.error("--refresh-seconds must be > 0")
    if args.snapshot_file and args.smoke_sample:
        parser.error("choose either --snapshot-file or --smoke-sample, not both")

    try:
        if args.once:
            resolved = _load(args)
            project = args.project or operator_data.snapshot_project(resolved.artifact or {}) or resolved.state_dir.name
            sys.stdout.write(render_snapshot(project, resolved))
            return 0
        if args.text_watch:
            return run_text_watch(args)
        return run_curses_ui(args)
    except operator_data.CliUsageError as exc:
        parser.error(str(exc))
    except FileNotFoundError as exc:
        parser.error(str(exc))
    except json.JSONDecodeError as exc:
        parser.error(f"snapshot fixture is malformed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
