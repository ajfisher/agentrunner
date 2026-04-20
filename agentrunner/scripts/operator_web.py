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
from datetime import datetime, timezone
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
class WebChip:
    label: str
    tone: str = "neutral"


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
    status_summary: str
    updated_line: str
    updated_summary: str
    chips: tuple[WebChip, ...]
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


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _humanize_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m" if remainder == 0 else f"{minutes}m {remainder}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h" if minutes == 0 else f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d" if hours == 0 else f"{days}d {hours}h"


def _recency_from_updated_at(value: Any) -> tuple[str, str, int | None]:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return ("recency unknown", "neutral", None)
    now = datetime.now(timezone.utc)
    age_seconds = max(0, int((now - parsed).total_seconds()))
    if age_seconds <= 30:
        return (f"fresh · updated {_humanize_age(age_seconds)} ago", "good", age_seconds)
    if age_seconds <= 300:
        return (f"recent · updated {_humanize_age(age_seconds)} ago", "info", age_seconds)
    if age_seconds <= 1800:
        return (f"aging · updated {_humanize_age(age_seconds)} ago", "warn", age_seconds)
    return (f"stale · updated {_humanize_age(age_seconds)} ago", "danger", age_seconds)


def _warning_tone(severity: str) -> str:
    normalized = severity.lower()
    if normalized in {"error", "critical"}:
        return "danger"
    if normalized in {"warn", "warning"}:
        return "warn"
    if normalized in {"ok", "success"}:
        return "good"
    if normalized == "info":
        return "info"
    return "neutral"


def _status_chip(snapshot: dict[str, Any]) -> WebChip:
    status = str(snapshot.get("status") or "unknown")
    tone_map = {
        "active": "good",
        "ok": "good",
        "idle": "neutral",
        "paused": "warn",
        "missing": "danger",
        "snapshot-unavailable": "danger",
        "unknown": "warn",
    }
    return WebChip(label=f"overall {status.replace('-', ' ')}", tone=tone_map.get(status, "info"))


def _queue_chip(snapshot: dict[str, Any]) -> WebChip:
    queue = snapshot.get("queue")
    depth = queue.get("depth", 0) if isinstance(queue, dict) else 0
    current = snapshot.get("current")
    is_running = isinstance(current, dict) and bool(current)
    if is_running:
        return WebChip(label=f"running · queue depth {depth}", tone="good" if depth == 0 else "info")
    if depth > 0:
        return WebChip(label=f"queued · {depth} waiting", tone="warn")
    return WebChip(label="idle · queue clear", tone="neutral")


def _warnings_chip(snapshot: dict[str, Any]) -> WebChip:
    warnings = _as_list(snapshot.get("warnings"), label="snapshot.warnings")
    if not warnings:
        return WebChip(label="warnings none", tone="good")
    severities = [
        str(item.get("severity") or "info")
        for item in warnings
        if isinstance(item, dict)
    ]
    if any(severity.lower() in {"error", "critical"} for severity in severities):
        tone = "danger"
    elif any(severity.lower() in {"warn", "warning"} for severity in severities):
        tone = "warn"
    else:
        tone = "info"
    noun = "warning" if len(warnings) == 1 else "warnings"
    return WebChip(label=f"{len(warnings)} {noun}", tone=tone)


def _recency_chip(snapshot: dict[str, Any]) -> WebChip:
    summary, tone, _ = _recency_from_updated_at(snapshot.get("updatedAt"))
    return WebChip(label=summary, tone=tone)


def _status_summary(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status") or "unknown").replace("-", " ")
    queue = snapshot.get("queue")
    depth = queue.get("depth", 0) if isinstance(queue, dict) else 0
    current = snapshot.get("current")
    warnings = _as_list(snapshot.get("warnings"), label="snapshot.warnings")
    if isinstance(current, dict) and current:
        queue_item = current.get("queueItemId") or "current work"
        role = current.get("role") or "worker"
        if depth > 0:
            return f"{status.capitalize()} — {role} is working on {queue_item} with {depth} more queued."
        return f"{status.capitalize()} — {role} is working on {queue_item} and the queue is otherwise clear."
    if depth > 0:
        return f"{status.capitalize()} — nothing is running right now, but {depth} queued item{'s' if depth != 1 else ''} are waiting."
    if warnings:
        return f"{status.capitalize()} — the queue is clear, but there {'are' if len(warnings) != 1 else 'is'} {len(warnings)} warning{'s' if len(warnings) != 1 else ''} worth checking."
    return f"{status.capitalize()} — nothing is running and the queue is clear."


def _updated_summary(snapshot: dict[str, Any]) -> str:
    summary, _, _ = _recency_from_updated_at(snapshot.get("updatedAt"))
    return f"Snapshot recency: {summary}."


def _line_current(snapshot: dict[str, Any]) -> str:
    current = snapshot.get("current")
    if not isinstance(current, dict) or not current:
        return "No job is currently running."
    parts = [
        current.get("queueItemId") or "unknown-item",
        current.get("role") or "unknown-role",
    ]
    branch = current.get("branch")
    if branch:
        parts.append(branch)
    age = current.get("ageSeconds")
    if age is not None:
        parts.append(f"running for {age}s")
    return "Running now: " + " | ".join(str(part) for part in parts)


def _line_queue(snapshot: dict[str, Any]) -> tuple[str, ...]:
    queue = snapshot.get("queue")
    if not isinstance(queue, dict):
        return ("Queue state is unavailable.",)
    depth = int(queue.get("depth", 0) or 0)
    if depth <= 0:
        lines = ["Queue is clear."]
    elif depth == 1:
        lines = ["1 item is waiting in the queue."]
    else:
        lines = [f"{depth} items are waiting in the queue."]
    next_ids = _as_list(queue.get("nextIds"), label="snapshot.queue.nextIds")
    if next_ids:
        lines.append("Coming up next: " + ", ".join(str(item) for item in next_ids))
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
            lines.append("Queued: " + " | ".join(str(bit) for bit in bits))
        else:
            lines.append("Queued: " + str(item))
    return tuple(lines)


def _line_initiative(snapshot: dict[str, Any]) -> tuple[str, ...]:
    initiative = snapshot.get("initiative")
    if not isinstance(initiative, dict) or not initiative:
        return ("No active initiative context.",)
    lines = [f"Initiative: {initiative.get('initiativeId', 'unknown-initiative')}"]
    phase = initiative.get("phase")
    subtask = initiative.get("currentSubtaskId")
    if phase:
        lines.append(f"Phase: {phase}")
    if subtask:
        lines.append(f"Current subtask: {subtask}")
    return tuple(lines)


def _line_last_completed(snapshot: dict[str, Any]) -> tuple[str, ...]:
    last = snapshot.get("lastCompleted")
    if not isinstance(last, dict) or not last:
        return ("Nothing has completed recently.",)
    parts = [
        last.get("queueItemId") or "unknown-item",
        last.get("role") or "unknown-role",
        last.get("status") or "unknown-status",
    ]
    summary = last.get("summary")
    if summary:
        parts.append(str(summary))
    return ("Most recent completion: " + " | ".join(str(part) for part in parts),)


def _line_warnings(snapshot: dict[str, Any]) -> tuple[str, ...]:
    warnings = _as_list(snapshot.get("warnings"), label="snapshot.warnings")
    if not warnings:
        return ("No warnings reported by the canonical snapshot.",)
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
        return ("Reconciliation details are unavailable.",)
    lines = [f"Decision: {rec.get('decision', 'unknown')}"]
    summary = rec.get("summary")
    if summary:
        lines.append(f"Why: {summary}")
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
    chips = (
        _status_chip(snapshot),
        _queue_chip(snapshot),
        _warnings_chip(snapshot),
        _recency_chip(snapshot),
    )
    return OperatorPageModel(
        project=project,
        artifact_path=artifact_path,
        mode_line="Mode: browser renderer over canonical /v1/operator/snapshot",
        status_line=f"Status: {snapshot.get('status', 'unknown')}",
        status_summary=_status_summary(snapshot),
        updated_line=f"Updated: {snapshot.get('updatedAt', 'unknown')}",
        updated_summary=_updated_summary(snapshot),
        chips=chips,
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
        "statusSummary": model.status_summary,
        "updatedLine": model.updated_line,
        "updatedSummary": model.updated_summary,
        "chips": [asdict(chip) for chip in model.chips],
        "notes": list(model.notes),
        "sections": [asdict(section) for section in model.sections],
        "bannerLines": list(model.banner_lines),
    }


def _json_for_html_script(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html(model: OperatorPageModel) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    initial_payload = page_model_payload(model)
    initial_payload_json = _json_for_html_script(initial_payload)
    refresh_ms = 5000
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
      --panel-soft: #0b1220;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --border: #334155;
      --banner: #7c2d12;
      --banner-border: #fb923c;
      --chip-neutral-bg: #1e293b;
      --chip-neutral-text: #cbd5e1;
      --chip-info-bg: rgba(56, 189, 248, .16);
      --chip-info-text: #7dd3fc;
      --chip-good-bg: rgba(34, 197, 94, .16);
      --chip-good-text: #86efac;
      --chip-warn-bg: rgba(245, 158, 11, .16);
      --chip-warn-text: #fcd34d;
      --chip-danger-bg: rgba(248, 113, 113, .16);
      --chip-danger-text: #fca5a5;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 1.25rem; border-bottom: 1px solid var(--border); background: rgba(17,24,39,.9); }}
    main {{ padding: 1.25rem; display: grid; gap: 1rem; }}
    .meta {{ display: grid; gap: .35rem; color: var(--muted); }}
    .hero {{ display: grid; gap: .85rem; background: var(--panel-soft); border: 1px solid var(--border); border-radius: 16px; padding: 1rem; }}
    .hero-copy {{ display: grid; gap: .35rem; }}
    .hero-summary {{ font-size: 1.05rem; font-weight: 600; line-height: 1.4; }}
    .hero-updated {{ color: var(--muted); }}
    .chip-row {{ display: flex; flex-wrap: wrap; gap: .55rem; }}
    .chip {{ display: inline-flex; align-items: center; border-radius: 999px; padding: .35rem .7rem; font-size: .87rem; font-weight: 700; letter-spacing: .01em; border: 1px solid transparent; }}
    .chip-neutral {{ background: var(--chip-neutral-bg); color: var(--chip-neutral-text); border-color: rgba(148, 163, 184, .24); }}
    .chip-info {{ background: var(--chip-info-bg); color: var(--chip-info-text); border-color: rgba(56, 189, 248, .28); }}
    .chip-good {{ background: var(--chip-good-bg); color: var(--chip-good-text); border-color: rgba(34, 197, 94, .30); }}
    .chip-warn {{ background: var(--chip-warn-bg); color: var(--chip-warn-text); border-color: rgba(245, 158, 11, .30); }}
    .chip-danger {{ background: var(--chip-danger-bg); color: var(--chip-danger-text); border-color: rgba(248, 113, 113, .30); }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 1rem; }}
    .banner-stack {{ display: grid; gap: .75rem; }}
    .banner {{ background: var(--banner); border: 1px solid var(--banner-border); border-radius: 12px; padding: .85rem 1rem; font-weight: 600; }}
    h1, h2 {{ margin: 0 0 .75rem 0; }}
    h1 {{ font-size: 1.25rem; }}
    h2 {{ font-size: 1rem; color: var(--accent); text-transform: capitalize; }}
    ul {{ margin: 0; padding-left: 1.1rem; }}
    li {{ margin: .3rem 0; }}
    code {{ color: var(--accent); }}
    footer {{ padding: 0 1.25rem 1.25rem; color: var(--muted); display: grid; gap: .35rem; }}
  </style>
</head>
<body data-project="{esc(model.project)}" data-refresh-ms="{refresh_ms}">
  <header>
    <h1 id=\"page-title\">AgentRunner operator · {esc(model.project)}</h1>
    <div class=\"meta\" id=\"page-meta\"></div>
  </header>
  <main>
    <section class=\"hero\">
      <div class=\"hero-copy\">
        <div class=\"hero-summary\" id=\"status-summary\"></div>
        <div class=\"hero-updated\" id=\"updated-summary\"></div>
      </div>
      <div class=\"chip-row\" id=\"page-chips\"></div>
    </section>
    <div class=\"banner-stack\" id=\"page-banners\"></div>
    <section class=\"card\">
      <h2>snapshot notes</h2>
      <ul id=\"page-notes\"></ul>
    </section>
    <div class=\"card-grid\" id=\"page-sections\"></div>
  </main>
  <footer>
    <div>Read-only browser renderer over the canonical /v1/operator/snapshot contract.</div>
    <div id=\"refresh-status\"></div>
  </footer>
  <script>
    const initialPageModel = {initial_payload_json};
    const refreshMs = Number(document.body.dataset.refreshMs || '5000');
    const project = document.body.dataset.project || initialPageModel.project;

    function escapeHtml(value) {{
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }}

    function renderPage(model, refreshLabel) {{
      document.title = `AgentRunner operator · ${{model.project}}`;
      document.getElementById('page-title').textContent = `AgentRunner operator · ${{model.project}}`;
      document.getElementById('page-meta').innerHTML = [
        `<div>${{escapeHtml(model.modeLine)}}</div>`,
        `<div>${{escapeHtml(model.statusLine)}}</div>`,
        `<div>${{escapeHtml(model.updatedLine)}}</div>`,
        `<div>artifact: <code>${{escapeHtml(model.artifactPath || 'n/a')}}</code></div>`,
      ].join('');
      document.getElementById('status-summary').textContent = model.statusSummary || '';
      document.getElementById('updated-summary').textContent = model.updatedSummary || '';

      const chips = model.chips && model.chips.length
        ? model.chips.map((chip) => `<span class=\"chip chip-${{escapeHtml(chip.tone || 'neutral')}}\">${{escapeHtml(chip.label)}}</span>`).join('')
        : '<span class="chip chip-neutral">no summary chips</span>';
      document.getElementById('page-chips').innerHTML = chips;

      const banners = model.bannerLines && model.bannerLines.length
        ? model.bannerLines.map((line) => `<div class=\"banner\">${{escapeHtml(line)}}</div>`).join('')
        : '';
      document.getElementById('page-banners').innerHTML = banners;

      const notes = model.notes && model.notes.length
        ? model.notes.map((line) => `<li>${{escapeHtml(line)}}</li>`).join('')
        : '<li>No snapshot notes.</li>';
      document.getElementById('page-notes').innerHTML = notes;

      const sections = (model.sections || []).map((section) => {{
        const lines = section.lines && section.lines.length
          ? section.lines.map((line) => `<li>${{escapeHtml(line)}}</li>`).join('')
          : '<li>none</li>';
        return `<section class=\"card\"><h2>${{escapeHtml(section.title)}}</h2><ul>${{lines}}</ul></section>`;
      }}).join('');
      document.getElementById('page-sections').innerHTML = sections;
      document.getElementById('refresh-status').textContent = refreshLabel;
    }}

    function recencyFromUpdatedAt(updatedAt) {{
      if (typeof updatedAt !== 'string' || !updatedAt) {{
        return {{label: 'recency unknown', tone: 'neutral'}};
      }}
      const timestamp = Date.parse(updatedAt);
      if (Number.isNaN(timestamp)) {{
        return {{label: 'recency unknown', tone: 'neutral'}};
      }}
      const ageSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
      if (ageSeconds <= 30) return {{label: `fresh · updated ${{ageSeconds}}s ago`, tone: 'good'}};
      if (ageSeconds <= 300) return {{label: `recent · updated ${{Math.floor(ageSeconds / 60)}}m ago`, tone: 'info'}};
      if (ageSeconds <= 1800) return {{label: `aging · updated ${{Math.floor(ageSeconds / 60)}}m ago`, tone: 'warn'}};
      return {{label: `stale · updated ${{Math.floor(ageSeconds / 3600)}}h ago`, tone: 'danger'}};
    }}

    function pageModelFromEnvelope(envelope) {{
      const snapshot = envelope && envelope.snapshot && typeof envelope.snapshot === 'object' ? envelope.snapshot : {{}};
      const warnings = Array.isArray(snapshot.warnings) ? snapshot.warnings : [];
      const warningCodes = new Set(
        warnings
          .filter((item) => item && typeof item === 'object' && item.code != null)
          .map((item) => String(item.code))
      );
      const bannerLines = [];
      if (warningCodes.has('stale_snapshot') || warningCodes.has('snapshot_stale')) {{
        bannerLines.push('Snapshot may be stale relative to recent mechanics activity.');
      }}
      if (['missing', 'snapshot-unavailable', 'unknown'].includes(snapshot.status)) {{
        bannerLines.push('Snapshot is not currently giving a confident operator answer.');
      }}

      const current = snapshot.current && typeof snapshot.current === 'object' ? snapshot.current : null;
      let currentLine = 'No job is currently running.';
      if (current && Object.keys(current).length) {{
        const bits = [current.queueItemId || 'unknown-item', current.role || 'unknown-role'];
        if (current.branch) bits.push(String(current.branch));
        if (current.ageSeconds != null) bits.push(`running for ${{current.ageSeconds}}s`);
        currentLine = 'Running now: ' + bits.join(' | ');
      }}

      const queue = snapshot.queue && typeof snapshot.queue === 'object' ? snapshot.queue : null;
      const queueDepth = queue ? Number(queue.depth ?? 0) : 0;
      const queueLines = [];
      if (!queue) {{
        queueLines.push('Queue state is unavailable.');
      }} else if (queueDepth <= 0) {{
        queueLines.push('Queue is clear.');
      }} else if (queueDepth === 1) {{
        queueLines.push('1 item is waiting in the queue.');
      }} else {{
        queueLines.push(`${{queueDepth}} items are waiting in the queue.`);
      }}
      const nextIds = Array.isArray(queue && queue.nextIds) ? queue.nextIds : [];
      if (nextIds.length) queueLines.push('Coming up next: ' + nextIds.map(String).join(', '));
      const preview = Array.isArray(queue && queue.preview) ? queue.preview : [];
      for (const item of preview.slice(0, 5)) {{
        if (item && typeof item === 'object') {{
          const bits = [item.queueItemId || 'unknown-item', item.role || 'unknown-role'];
          if (item.branch) bits.push(String(item.branch));
          if (item.goal) bits.push(String(item.goal));
          queueLines.push('Queued: ' + bits.join(' | '));
        }} else {{
          queueLines.push('Queued: ' + String(item));
        }}
      }}

      const initiative = snapshot.initiative && typeof snapshot.initiative === 'object' ? snapshot.initiative : null;
      const initiativeLines = !initiative || !Object.keys(initiative).length
        ? ['No active initiative context.']
        : [
            `Initiative: ${{initiative.initiativeId || 'unknown-initiative'}}`,
            ...(initiative.phase ? [`Phase: ${{initiative.phase}}`] : []),
            ...(initiative.currentSubtaskId ? [`Current subtask: ${{initiative.currentSubtaskId}}`] : []),
          ];

      const lastCompleted = snapshot.lastCompleted && typeof snapshot.lastCompleted === 'object' ? snapshot.lastCompleted : null;
      const lastCompletedLines = !lastCompleted || !Object.keys(lastCompleted).length
        ? ['Nothing has completed recently.']
        : [
            'Most recent completion: ' + [
              lastCompleted.queueItemId || 'unknown-item',
              lastCompleted.role || 'unknown-role',
              lastCompleted.status || 'unknown-status',
              ...(lastCompleted.summary ? [String(lastCompleted.summary)] : []),
            ].join(' | '),
          ];

      const warningLines = warnings.length
        ? warnings.slice(0, 5).map((item) => item && typeof item === 'object'
            ? `${{item.severity || 'info'}}: ${{item.summary || item.code || 'warning'}}`
            : String(item))
        : ['No warnings reported by the canonical snapshot.'];

      const reconciliation = snapshot.reconciliation && typeof snapshot.reconciliation === 'object' ? snapshot.reconciliation : null;
      const reconciliationLines = !reconciliation || !Object.keys(reconciliation).length
        ? ['Reconciliation details are unavailable.']
        : [
            `Decision: ${{reconciliation.decision || 'unknown'}}`,
            ...(reconciliation.summary ? [`Why: ${{reconciliation.summary}}`] : []),
          ];

      const status = String(snapshot.status || 'unknown');
      const statusLabel = status.replaceAll('-', ' ');
      let statusSummary = `${{statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1)}} — nothing is running and the queue is clear.`;
      if (current && Object.keys(current).length) {{
        const queueItemId = current.queueItemId || 'current work';
        const role = current.role || 'worker';
        statusSummary = queueDepth > 0
          ? `${{statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1)}} — ${{role}} is working on ${{queueItemId}} with ${{queueDepth}} more queued.`
          : `${{statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1)}} — ${{role}} is working on ${{queueItemId}} and the queue is otherwise clear.`;
      }} else if (queueDepth > 0) {{
        statusSummary = `${{statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1)}} — nothing is running right now, but ${{queueDepth}} queued item${{queueDepth === 1 ? '' : 's'}} are waiting.`;
      }} else if (warnings.length) {{
        statusSummary = `${{statusLabel.charAt(0).toUpperCase() + statusLabel.slice(1)}} — the queue is clear, but there ${{warnings.length === 1 ? 'is' : 'are'}} ${{warnings.length}} warning${{warnings.length === 1 ? '' : 's'}} worth checking.`;
      }}

      const recency = recencyFromUpdatedAt(snapshot.updatedAt);
      const chips = [];
      const statusTone = ['active', 'ok'].includes(status) ? 'good' : ['missing', 'snapshot-unavailable'].includes(status) ? 'danger' : status === 'unknown' ? 'warn' : 'neutral';
      chips.push({{label: `overall ${{statusLabel}}`, tone: statusTone}});
      if (current && Object.keys(current).length) {{
        chips.push({{label: `running · queue depth ${{queueDepth}}`, tone: queueDepth === 0 ? 'good' : 'info'}});
      }} else if (queueDepth > 0) {{
        chips.push({{label: `queued · ${{queueDepth}} waiting`, tone: 'warn'}});
      }} else {{
        chips.push({{label: 'idle · queue clear', tone: 'neutral'}});
      }}
      if (!warnings.length) {{
        chips.push({{label: 'warnings none', tone: 'good'}});
      }} else {{
        const severe = warnings.some((item) => item && typeof item === 'object' && ['error', 'critical'].includes(String(item.severity || '').toLowerCase()));
        const warned = warnings.some((item) => item && typeof item === 'object' && ['warn', 'warning'].includes(String(item.severity || '').toLowerCase()));
        chips.push({{label: `${{warnings.length}} warning${{warnings.length === 1 ? '' : 's'}}`, tone: severe ? 'danger' : warned ? 'warn' : 'info'}});
      }}
      chips.push(recency);

      return {{
        project: String(envelope.project || snapshot.project || project || 'unknown-project'),
        artifactPath: String(envelope.artifactPath || ''),
        modeLine: 'Mode: browser renderer over canonical /v1/operator/snapshot',
        statusLine: `Status: ${{snapshot.status || 'unknown'}}`,
        statusSummary,
        updatedLine: `Updated: ${{snapshot.updatedAt || 'unknown'}}`,
        updatedSummary: `Snapshot recency: ${{recency.label}}.`,
        chips,
        notes: Array.isArray(envelope.notes) ? envelope.notes.map(String) : [],
        sections: [
          {{title: 'current', lines: [currentLine]}},
          {{title: 'queue', lines: queueLines}},
          {{title: 'initiative', lines: initiativeLines}},
          {{title: 'last completed', lines: lastCompletedLines}},
          {{title: 'warnings', lines: warningLines}},
          {{title: 'reconciliation', lines: reconciliationLines}},
        ],
        bannerLines,
      }};
    }}

    async function refreshSnapshot() {{
      try {{
        const response = await fetch(`/v1/operator/snapshot?project=${{encodeURIComponent(project)}}`, {{
          method: 'GET',
          headers: {{'Accept': 'application/json'}},
          cache: 'no-store',
        }});
        const envelope = await response.json();
        if (!response.ok) {{
          throw new Error(envelope && envelope.message ? envelope.message : `snapshot refresh failed with ${{response.status}}`);
        }}
        renderPage(pageModelFromEnvelope(envelope), `Auto-refreshing every ${{Math.round(refreshMs / 1000)}}s · last refresh ok at ${{new Date().toLocaleTimeString()}}`);
      }} catch (error) {{
        document.getElementById('refresh-status').textContent = `Auto-refreshing every ${{Math.round(refreshMs / 1000)}}s · refresh failed: ${{error.message}}`;
      }}
    }}

    renderPage(initialPageModel, `Auto-refreshing every ${{Math.round(refreshMs / 1000)}}s · waiting for first refresh…`);
    window.setInterval(refreshSnapshot, refreshMs);
    window.setTimeout(refreshSnapshot, refreshMs);
  </script>
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
        status_summary="Snapshot unavailable — the browser surface cannot confidently describe current mechanics state yet.",
        updated_line="Updated: unavailable",
        updated_summary="Snapshot recency: recency unknown.",
        chips=(
            WebChip(label="overall snapshot unavailable", tone="danger"),
            WebChip(label="queue unknown", tone="warn"),
            WebChip(label="warnings present", tone="warn"),
            WebChip(label="recency unknown", tone="neutral"),
        ),
        notes=notes or ("No canonical snapshot is available yet.",),
        sections=(
            WebSection(title="current", lines=("Current work is unavailable.",)),
            WebSection(title="queue", lines=("Queue state is unavailable.",)),
            WebSection(title="initiative", lines=("Initiative context is unavailable.",)),
            WebSection(title="last completed", lines=("Recent completion data is unavailable.",)),
            WebSection(title="warnings", lines=("warning: canonical snapshot missing",)),
            WebSection(title="reconciliation", lines=("Reconciliation details are unavailable.",)),
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
