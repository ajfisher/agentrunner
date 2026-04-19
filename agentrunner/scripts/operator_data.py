#!/usr/bin/env python3
"""Shared read-only operator data contract helpers for AgentRunner.

This module names the per-project operator snapshot contract and centralizes
artifact loading / bounded rebuild policy so operator-facing surfaces do not
re-implement it ad hoc.

It is intentionally stdlib-only. Loading helpers are read-only; they never
mutate mechanics-owned state. Rebuild/write remains an explicit caller action.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

DEFAULT_PROJECTS_ROOT = Path.home() / ".agentrunner" / "projects"
OPERATOR_STATUS_FILENAME = "operator_status.json"
OPERATOR_SNAPSHOT_CONTRACT = {
    "name": "agentrunner.operator-status-snapshot",
    "version": 1,
    "filename": OPERATOR_STATUS_FILENAME,
    "pathPattern": "~/.agentrunner/projects/<project>/operator_status.json",
    "ownership": "derivative operator-facing snapshot",
}


class CliUsageError(RuntimeError):
    """Raised when operator input is incomplete or contradictory."""


BuildArtifact = Callable[..., dict[str, Any]]
WriteArtifact = Callable[[Path, dict[str, Any]], Path]


def clip(value: Any, limit: int = 120) -> str:
    if value is None:
        return "-"
    text = str(value).strip().replace("\n", " ")
    text = " ".join(text.split())
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def parse_artifact(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} did not contain a JSON object")
    return data


def infer_state_dir(*, state_dir: str | None = None, project: str | None = None) -> Path:
    if state_dir:
        return Path(state_dir).expanduser().resolve()
    if project:
        return (DEFAULT_PROJECTS_ROOT / project).resolve()
    raise CliUsageError("provide --project or --state-dir")


def operator_snapshot_path(state_dir: Path) -> Path:
    return state_dir / OPERATOR_STATUS_FILENAME


def load_operator_snapshot(
    state_dir: Path,
    *,
    queue_preview: int,
    tick_count: int,
    rebuild_missing: bool,
    rebuild_malformed: bool,
    write_rebuild: bool,
    build_status_artifact: BuildArtifact,
    write_status_artifact: WriteArtifact,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Load the canonical operator snapshot, with explicit bounded rebuild fallback.

    The loader itself is read-only. Rebuild/write only occurs when the caller has
    explicitly opted into the bounded fallback path.
    """
    notes: list[str] = []
    artifact_path = operator_snapshot_path(state_dir)
    artifact: dict[str, Any] | None = None

    if artifact_path.exists():
        try:
            artifact = parse_artifact(artifact_path)
        except Exception as exc:
            notes.append(f"warning: {OPERATOR_STATUS_FILENAME} is malformed: {clip(exc, 160)}")
            if rebuild_malformed:
                artifact = build_status_artifact(state_dir, queue_preview=queue_preview, tick_count=tick_count)
                notes.append("info: rebuilt operator snapshot from mechanics files because --rebuild-malformed was set")
                if write_rebuild:
                    write_status_artifact(state_dir, artifact)
                    notes.append(f"info: refreshed {artifact_path}")
            else:
                notes.append("hint: rerun with --rebuild-malformed to use the bounded manual fallback")
    else:
        notes.append(f"warning: operator snapshot missing at {artifact_path}")
        if rebuild_missing:
            artifact = build_status_artifact(state_dir, queue_preview=queue_preview, tick_count=tick_count)
            notes.append("info: rebuilt operator snapshot from mechanics files because --rebuild-missing was set")
            if write_rebuild:
                write_status_artifact(state_dir, artifact)
                notes.append(f"info: wrote {artifact_path}")
        else:
            notes.append("hint: rerun with --rebuild-missing for a bounded manual rebuild")

    return artifact, notes
