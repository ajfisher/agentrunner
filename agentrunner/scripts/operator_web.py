#!/usr/bin/env python3
"""Browser renderer helpers for the canonical AgentRunner operator snapshot.

This module intentionally does *not* serve HTTP for the first browser-facing
slice. The approved seam is:
- launch the existing local read-only API entrypoint
- consume ``/v1/operator/snapshot?project=<project>``
- render HTML from that canonical snapshot contract

Keeping the browser layer here renderer-only avoids introducing a second local
web runtime while still giving future browser adapters a shared viewmodel/HTML
seam.
"""
from __future__ import annotations

import argparse
import json
import html
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from . import operator_tui
    from .operator_data import resolve_operator_snapshot
except ImportError:  # pragma: no cover - script-mode fallback
    script_root = Path(__file__).resolve().parents[2]
    if str(script_root) not in sys.path:
        sys.path.insert(0, str(script_root))
    from agentrunner.scripts import operator_tui  # type: ignore
    from agentrunner.scripts.operator_data import resolve_operator_snapshot  # type: ignore


@dataclass(frozen=True)
class WebSection:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class OperatorPageModel:
    project: str
    artifact_path: str
    mode_line: str
    status_line: str
    updated_line: str
    notes: tuple[str, ...]
    sections: tuple[WebSection, ...]
    banner_lines: tuple[str, ...] = ()


REQUIRED_SNAPSHOT_FIELDS = (
    "status",
    "current",
    "queue",
    "initiative",
    "lastCompleted",
    "warnings",
    "reconciliation",
    "updatedAt",
)


class OperatorWebContractError(ValueError):
    """Raised when the canonical snapshot envelope is missing required fields."""


def _as_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OperatorWebContractError(f"{label} must be an object")
    return value


def _as_list(value: Any, *, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise OperatorWebContractError(f"{label} must be an array")
    return value


def _line_current(snapshot: dict[str, Any]) -> str:
    current = snapshot.get("current")
    if not isinstance(current, dict) or not current:
        return "Current: idle"
    parts = [
        current.get("queueItemId") or "unknown-item",
        current.get("role") or "unknown-role",
    ]
    branch = current.get("branch")
    if branch:
        parts.append(branch)
    age = current.get("ageSeconds")
    if age is not None:
        parts.append(f"age={age}s")
    return "Current: " + " | ".join(str(part) for part in parts)


def _line_queue(snapshot: dict[str, Any]) -> tuple[str, ...]:
    queue = snapshot.get("queue")
    if not isinstance(queue, dict):
        return ("Queue: unavailable",)
    lines = [f"Depth: {queue.get('depth', 0)}"]
    next_ids = _as_list(queue.get("nextIds"), label="snapshot.queue.nextIds")
    if next_ids:
        lines.append("Next: " + ", ".join(str(item) for item in next_ids))
    preview = _as_list(queue.get("preview"), label="snapshot.queue.preview")
    for item in preview[:5]:
        if isinstance(item, dict):
            bits = [
                item.get("queueItemId") or "unknown-item",
                item.get("role") or "unknown-role",
            ]
            branch = item.get("branch")
            goal = item.get("goal")
            if branch:
                bits.append(str(branch))
            if goal:
                bits.append(str(goal))
            lines.append(" | ".join(str(bit) for bit in bits))
        else:
            lines.append(str(item))
    return tuple(lines)


def _line_initiative(snapshot: dict[str, Any]) -> tuple[str, ...]:
    initiative = snapshot.get("initiative")
    if not isinstance(initiative, dict) or not initiative:
        return ("Initiative: none",)
    lines = [f"Initiative: {initiative.get('initiativeId', 'unknown-initiative')}"]
    phase = initiative.get("phase")
    subtask = initiative.get("currentSubtaskId")
    if phase:
        lines.append(f"Phase: {phase}")
    if subtask:
        lines.append(f"Subtask: {subtask}")
    return tuple(lines)


def _line_last_completed(snapshot: dict[str, Any]) -> tuple[str, ...]:
    last = snapshot.get("lastCompleted")
    if not isinstance(last, dict) or not last:
        return ("Last completed: none",)
    parts = [
        last.get("queueItemId") or "unknown-item",
        last.get("role") or "unknown-role",
        last.get("status") or "unknown-status",
    ]
    summary = last.get("summary")
    if summary:
        parts.append(str(summary))
    return ("Last completed: " + " | ".join(str(part) for part in parts),)


def _line_warnings(snapshot: dict[str, Any]) -> tuple[str, ...]:
    warnings = _as_list(snapshot.get("warnings"), label="snapshot.warnings")
    if not warnings:
        return ("Warnings: none",)
    lines: list[str] = []
    for item in warnings[:5]:
        if isinstance(item, dict):
            severity = item.get("severity") or "info"
            summary = item.get("summary") or item.get("code") or "warning"
            lines.append(f"{severity}: {summary}")
        else:
            lines.append(str(item))
    return tuple(lines)


def _line_reconciliation(snapshot: dict[str, Any]) -> tuple[str, ...]:
    rec = snapshot.get("reconciliation")
    if not isinstance(rec, dict) or not rec:
        return ("Reconciliation: unavailable",)
    lines = [f"Decision: {rec.get('decision', 'unknown')}"]
    summary = rec.get("summary")
    if summary:
        lines.append(f"Summary: {summary}")
    return tuple(lines)


def build_page_model_from_snapshot_envelope(envelope: dict[str, Any]) -> OperatorPageModel:
    payload = _as_mapping(envelope, label="envelope")
    snapshot = _as_mapping(payload.get("snapshot"), label="snapshot")
    missing = [field for field in REQUIRED_SNAPSHOT_FIELDS if field not in snapshot]
    if missing:
        raise OperatorWebContractError("snapshot missing required fields: " + ", ".join(missing))

    project = str(payload.get("project") or snapshot.get("project") or "unknown-project")
    artifact_path = str(payload.get("artifactPath") or "")
    notes = tuple(str(item) for item in _as_list(payload.get("notes"), label="notes"))
    warnings = _as_list(snapshot.get("warnings"), label="snapshot.warnings")
    warning_codes = {
        str(item.get("code"))
        for item in warnings
        if isinstance(item, dict) and item.get("code") is not None
    }
    banner_lines: list[str] = []
    if any(code in warning_codes for code in {"stale_snapshot", "snapshot_stale"}):
        banner_lines.append("Snapshot may be stale relative to recent mechanics activity.")
    if snapshot.get("status") in {"missing", "snapshot-unavailable", "unknown"}:
        banner_lines.append("Snapshot is not currently giving a confident operator answer.")

    sections = (
        WebSection(title="current", lines=(_line_current(snapshot),)),
        WebSection(title="queue", lines=_line_queue(snapshot)),
        WebSection(title="initiative", lines=_line_initiative(snapshot)),
        WebSection(title="last completed", lines=_line_last_completed(snapshot)),
        WebSection(title="warnings", lines=_line_warnings(snapshot)),
        WebSection(title="reconciliation", lines=_line_reconciliation(snapshot)),
    )
    return OperatorPageModel(
        project=project,
        artifact_path=artifact_path,
        mode_line="Mode: browser renderer over canonical /v1/operator/snapshot",
        status_line=f"Status: {snapshot.get('status', 'unknown')}",
        updated_line=f"Updated: {snapshot.get('updatedAt', 'unknown')}",
        notes=notes,
        sections=sections,
        banner_lines=tuple(banner_lines),
    )


def page_model_payload(model: OperatorPageModel) -> dict[str, Any]:
    return {
        "project": model.project,
        "artifactPath": model.artifact_path,
        "modeLine": model.mode_line,
        "statusLine": model.status_line,
        "updatedLine": model.updated_line,
        "notes": list(model.notes),
        "sections": [asdict(section) for section in model.sections],
        "bannerLines": list(model.banner_lines),
    }


def render_html(model: OperatorPageModel) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    note_items = "".join(f"<li>{esc(note)}</li>" for note in model.notes) or "<li>No snapshot notes.</li>"
    banner_html = "".join(f"<div class=\"banner\">{esc(line)}</div>" for line in model.banner_lines)
    section_cards = []
    for section in model.sections:
        line_items = "".join(f"<li>{esc(line)}</li>" for line in section.lines) or "<li>none</li>"
        section_cards.append(
            "<section class=\"card\">"
            f"<h2>{esc(section.title)}</h2>"
            f"<ul>{line_items}</ul>"
            "</section>"
        )
    cards = "".join(section_cards)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>AgentRunner operator · {esc(model.project)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --border: #334155;
      --banner: #7c2d12;
      --banner-border: #fb923c;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 1.25rem; border-bottom: 1px solid var(--border); background: rgba(17,24,39,.9); }}
    main {{ padding: 1.25rem; display: grid; gap: 1rem; }}
    .meta {{ display: grid; gap: .35rem; color: var(--muted); }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 1rem; }}
    .banner {{ background: var(--banner); border: 1px solid var(--banner-border); border-radius: 12px; padding: .85rem 1rem; font-weight: 600; }}
    h1, h2 {{ margin: 0 0 .75rem 0; }}
    h1 {{ font-size: 1.25rem; }}
    h2 {{ font-size: 1rem; color: var(--accent); text-transform: capitalize; }}
    ul {{ margin: 0; padding-left: 1.1rem; }}
    li {{ margin: .3rem 0; }}
    code {{ color: var(--accent); }}
    footer {{ padding: 0 1.25rem 1.25rem; color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>AgentRunner operator · {esc(model.project)}</h1>
    <div class=\"meta\">
      <div>{esc(model.mode_line)}</div>
      <div>{esc(model.status_line)}</div>
      <div>{esc(model.updated_line)}</div>
      <div>artifact: <code>{esc(model.artifact_path or 'n/a')}</code></div>
    </div>
  </header>
  <main>
    {banner_html}
    <section class=\"card\">
      <h2>snapshot notes</h2>
      <ul>{note_items}</ul>
    </section>
    <div class=\"card-grid\">{cards}</div>
  </main>
  <footer>Read-only browser renderer over the canonical /v1/operator/snapshot contract.</footer>
</body>
</html>
"""


def render_html_from_snapshot_envelope(envelope: dict[str, Any]) -> str:
    return render_html(build_page_model_from_snapshot_envelope(envelope))


def render_unavailable_html(*, project: str, artifact_path: str, notes: tuple[str, ...]) -> str:
    model = OperatorPageModel(
        project=project,
        artifact_path=artifact_path,
        mode_line="Mode: browser renderer over canonical /v1/operator/snapshot",
        status_line="Status: snapshot unavailable",
        updated_line="Updated: unavailable",
        notes=notes or ("No canonical snapshot is available yet.",),
        sections=(
            WebSection(title="current", lines=("Current: unavailable",)),
            WebSection(title="queue", lines=("Queue: unavailable",)),
            WebSection(title="initiative", lines=("Initiative: unavailable",)),
            WebSection(title="last completed", lines=("Last completed: unavailable",)),
            WebSection(title="warnings", lines=("warning: canonical snapshot missing",)),
            WebSection(title="reconciliation", lines=("Reconciliation: unavailable",)),
        ),
        banner_lines=("Canonical operator snapshot is missing or malformed; this page is showing a degraded read-only state.",),
    )
    return render_html(model)


def sample_snapshot_envelope() -> dict[str, Any]:
    snapshot = dict(operator_tui.SAMPLE_SNAPSHOT)
    snapshot.setdefault(
        "reconciliation",
        {
            "decision": snapshot.get("status", "unknown"),
            "summary": "sample readonly operator snapshot",
            "reasons": [],
        },
    )
    return {
        "project": "sample-project",
        "artifactPath": "/tmp/sample-project/operator_status.json",
        "notes": ["info: using built-in sample snapshot (no mechanics reads)"],
        "snapshot": snapshot,
    }


def render_html_for_project(
    *,
    project: str,
    state_dir: str | None = None,
    queue_preview: int = 5,
    tick_count: int = 3,
    rebuild_missing: bool = False,
    rebuild_malformed: bool = False,
    write_rebuild: bool = False,
) -> str:
    resolved = resolve_operator_snapshot(
        state_dir=state_dir,
        project=project,
        queue_preview=queue_preview,
        tick_count=tick_count,
        rebuild_missing=rebuild_missing,
        rebuild_malformed=rebuild_malformed,
        write_rebuild=write_rebuild,
    )
    if resolved.artifact is None:
        return render_unavailable_html(
            project=project,
            artifact_path=str(resolved.artifact_path),
            notes=resolved.notes,
        )
    return render_html_from_snapshot_envelope(
        {
            "project": project,
            "artifactPath": str(resolved.artifact_path),
            "notes": list(resolved.notes),
            "snapshot": resolved.artifact,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render the read-only AgentRunner operator HTML surface without starting a separate web runtime",
    )
    parser.add_argument("--project", help="Project id to render from the canonical operator snapshot")
    parser.add_argument("--state-dir", help="Explicit project state dir (alternative to --project)")
    parser.add_argument("--queue-preview", type=int, default=5, help="Queue preview size when bounded rebuild is enabled")
    parser.add_argument("--tick-count", type=int, default=3, help="Tick tail size when bounded rebuild is enabled")
    parser.add_argument("--rebuild-missing", action="store_true", help="If operator_status.json is missing, do a bounded manual rebuild from mechanics files")
    parser.add_argument("--rebuild-malformed", action="store_true", help="If operator_status.json is malformed, do a bounded manual rebuild from mechanics files")
    parser.add_argument("--write-rebuild", action="store_true", help="Persist a bounded rebuild back to operator_status.json")
    parser.add_argument("--snapshot-file", help="Render from a snapshot envelope fixture JSON file")
    parser.add_argument("--smoke-sample", action="store_true", help="Render against a built-in sample snapshot without live mechanics")
    parser.add_argument("--output", help="Write HTML to this file instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    modes = [bool(args.snapshot_file), bool(args.smoke_sample), bool(args.project or args.state_dir)]
    if sum(1 for enabled in modes if enabled) != 1:
        parser.error("choose exactly one render source: --snapshot-file, --smoke-sample, or --project/--state-dir")

    if args.snapshot_file:
        try:
            envelope = json.loads(Path(args.snapshot_file).read_text(encoding="utf-8"))
        except Exception as exc:
            parser.error(f"snapshot fixture is malformed: {exc}")
        html_text = render_html_from_snapshot_envelope(envelope)
    elif args.smoke_sample:
        html_text = render_html_from_snapshot_envelope(sample_snapshot_envelope())
    else:
        html_text = render_html_for_project(
            project=args.project or Path(args.state_dir).name,
            state_dir=args.state_dir,
            queue_preview=args.queue_preview,
            tick_count=args.tick_count,
            rebuild_missing=args.rebuild_missing,
            rebuild_malformed=args.rebuild_malformed,
            write_rebuild=args.write_rebuild,
        )

    if args.output:
        Path(args.output).write_text(html_text, encoding="utf-8")
    else:
        sys.stdout.write(html_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
