#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 4, 18, 23, 0, 0, tzinfo=timezone.utc)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def run_module(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agentrunner", *args],
        cwd=ROOT,
        text=True,
        input=input_text,
        capture_output=True,
        check=False,
    )


def init_status_repo(repo: Path, *, branch: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "AgentRunner Tests"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
    (repo / "README.md").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "master"], cwd=repo, check=True, capture_output=True, text=True)


def test_routed_status_queue_and_initiatives_use_disposable_operator_artifact(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    write_json(
        state_dir / "operator_status.json",
        {
            "project": "demo",
            "status": "active",
            "updatedAt": "2026-04-19T00:00:00Z",
            "current": {
                "queueItemId": "developer-smoke",
                "role": "developer",
                "branch": "feature/agentrunner/real-cli-surface",
                "startedAt": "2026-04-19T00:00:00Z",
                "ageSeconds": 19,
            },
            "queue": {
                "depth": 2,
                "nextIds": ["reviewer-smoke", "manager-wrap"],
                "preview": [
                    {
                        "queueItemId": "reviewer-smoke",
                        "role": "reviewer",
                        "branch": "feature/agentrunner/real-cli-surface",
                        "goal": "Review the smoke proof coverage.",
                    },
                    {
                        "queueItemId": "manager-wrap",
                        "role": "manager",
                        "branch": "feature/agentrunner/real-cli-surface",
                        "goal": "Close the initiative cleanly.",
                    },
                ],
            },
            "initiative": {
                "initiativeId": "agentrunner-real-cli-surface",
                "phase": "implementation",
                "currentSubtaskId": "smoke-proof",
            },
            "lastCompleted": {
                "queueItemId": "architect-plan",
                "role": "architect",
                "status": "ok",
                "summary": "Planned the CLI smoke coverage.",
                "endedAt": "2026-04-19T00:10:00Z",
            },
            "resultHint": "Smoke coverage is now routed through the top-level CLI.",
            "warnings": [],
            "reconciliation": {
                "decision": "active",
                "summary": "runtime lock and active run details agree on a live in-flight item",
                "reasons": [
                    {
                        "code": "active_run",
                        "source": "live_runtime",
                        "severity": "info",
                        "summary": "runtime lock and active run details agree on a live in-flight item",
                        "precedence": 5,
                    }
                ],
                "policy": {
                    "name": "canonical_runtime_reconciliation",
                    "version": 2,
                    "precedenceOrder": [
                        "integrity_conflicts",
                        "stale_active_runtime",
                        "live_repo_clean_overrides_stale_blocked_artifact",
                        "last_completed_blocked",
                        "active_runtime_lock",
                        "queued_backlog_without_active_run",
                        "idle_clean",
                    ],
                },
            },
        },
    )

    for command, needles in {
        "status": [
            "project: demo",
            "status: ACTIVE | developer-smoke | developer | feature/agentrunner/real-cli-surface | age=19s",
            "reconciliation: active | winner=source=live_runtime, rule=active_run, p5 | runtime lock and active run details agree on a live in-flight item | reasons=1",
            "operator hierarchy: canonical_runtime_reconciliation v2 | integrity_conflicts > stale_active_runtime > live_repo_clean_overrides_stale_blocked_ar… > last_completed_blocked > active_runtime_lock > queued_backlog_without_active_run > idle_clean",
        ],
        "queue": ["queue: 2 item(s) | next=reviewer-smoke, manager-wrap", "reviewer-smoke | reviewer | feature/agentrunner/real-cli-surface | Review the smoke proof coverage.", "manager-wrap | manager | feature/agentrunner/real-cli-surface | Close the initiative cleanly."],
        "initiatives": ["initiative: agentrunner-real-cli-surface | phase=implementation | subtask=smoke-proof", "result hint: Smoke coverage is now routed through the top-level CLI."],
    }.items():
        result = run_module(command, "--state-dir", str(state_dir))
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        for needle in needles:
            assert needle in result.stdout


def test_routed_brief_enqueues_valid_initiative_against_disposable_state(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    state_dir = tmp_path / "runtime"

    result = run_module(
        "brief",
        "--project",
        "demo",
        "--initiative-id",
        "demo-cli-surface",
        "--branch",
        "feature/agentrunner/real-cli-surface",
        "--base",
        "master",
        "--repo-path",
        str(repo_path),
        "--state-dir",
        str(state_dir),
        "--manager-brief-json",
        json.dumps(
            {
                "title": "Smoke proof the real CLI",
                "objective": "Show the top-level CLI can enqueue a valid brief.",
                "desiredOutcomes": ["Kickoff item created"],
                "definitionOfDone": ["Queue event emitted through the helper path"],
            }
        ),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["queueItemId"] == "demo-cli-surface-manager"
    assert payload["branch"] == "feature/agentrunner/real-cli-surface"

    brief_path = state_dir / "initiatives" / "demo-cli-surface" / "brief.json"
    assert Path(payload["managerBriefPath"]) == brief_path
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    assert brief["initiativeId"] == "demo-cli-surface"
    assert brief["project"] == "demo"
    assert brief["repoPath"] == str(repo_path)

    queue_events = (state_dir / "queue_events.ndjson").read_text(encoding="utf-8")
    assert "demo-cli-surface-manager" in queue_events
    assert '"kind": "INSERT_FRONT"' in queue_events


def test_routed_brief_failure_path_stays_operator_readable(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    state_dir = tmp_path / "runtime"

    result = run_module(
        "brief",
        "--project",
        "demo",
        "--initiative-id",
        "demo-cli-surface",
        "--branch",
        "feature/agentrunner/real-cli-surface",
        "--base",
        "master",
        "--repo-path",
        str(repo_path),
        "--state-dir",
        str(state_dir),
        "--manager-brief-json",
        "not-json",
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "--manager-brief-json must be valid JSON:" in result.stderr
    assert "JSONDecodeError" not in result.stderr


def test_status_rebuild_recovers_stale_blocked_merger_tail_when_repo_is_already_clean(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    state_dir = tmp_path / "runtime"
    init_status_repo(repo_path, branch="feature/agentrunner/state-reconciliation-weighting")
    subprocess.run(["git", "checkout", "master"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "merge", "--ff-only", "feature/agentrunner/state-reconciliation-weighting"], cwd=repo_path, check=True, capture_output=True, text=True)

    write_json(
        state_dir / "state.json",
        {
            "project": "agentrunner",
            "running": False,
            "updatedAt": (FIXED_NOW - timedelta(minutes=1)).isoformat(),
            "current": None,
            "lastCompleted": {
                "queueItemId": "merger-blocked",
                "role": "merger",
                "status": "blocked",
                "endedAt": (FIXED_NOW - timedelta(hours=2)).isoformat(),
                "queueItem": {
                    "repo_path": str(repo_path),
                    "branch": "feature/agentrunner/state-reconciliation-weighting",
                    "base": "master",
                },
            },
        },
    )
    write_json(state_dir / "queue.json", [])

    result = run_module(
        "status",
        "--state-dir",
        str(state_dir),
        "--rebuild-missing",
    )

    assert result.returncode == 0, result.stderr
    assert "status: IDLE-CLEAN" in result.stdout
    assert "reconciliation: idle-clean | winner=source=live_repo, rule=live_repo_clean_overrides_stale_blocked_artifact, p3 | live repo truth is clean/current, so it outranks a stale blocked completion artifact | reasons=1" in result.stdout
    assert "operator hierarchy: canonical_runtime_reconciliation v2 | integrity_conflicts > stale_active_runtime > live_repo_clean_overrides_stale_blocked_ar… > last_completed_blocked > active_runtime_lock > queued_backlog_without_active_run > idle_clean" in result.stdout
    assert "last completed: merger-blocked | merger | blocked" in result.stdout



def test_status_rebuild_keeps_repo_conflict_blocked_instead_of_auto_cleaning(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    state_dir = tmp_path / "runtime"
    init_status_repo(repo_path, branch="feature/agentrunner/state-reconciliation-weighting")
    (repo_path / "README.md").write_text("dirty now\n", encoding="utf-8")

    write_json(
        state_dir / "state.json",
        {
            "project": "agentrunner",
            "running": False,
            "updatedAt": (FIXED_NOW - timedelta(minutes=1)).isoformat(),
            "current": None,
            "lastCompleted": {
                "queueItemId": "merger-blocked",
                "role": "merger",
                "status": "blocked",
                "endedAt": (FIXED_NOW - timedelta(hours=2)).isoformat(),
                "queueItem": {
                    "repo_path": str(repo_path),
                    "branch": "feature/agentrunner/state-reconciliation-weighting",
                    "base": "master",
                },
            },
        },
    )
    write_json(state_dir / "queue.json", [])

    result = run_module(
        "status",
        "--state-dir",
        str(state_dir),
        "--rebuild-missing",
    )

    assert result.returncode == 0, result.stderr
    assert "status: BLOCKED" in result.stdout
    assert "reconciliation: blocked | winner=source=result_artifacts, rule=last_completed_blocked, p4 | most recent completed item ended blocked | reasons=1" in result.stdout
    assert "operator hierarchy: canonical_runtime_reconciliation v2 | integrity_conflicts > stale_active_runtime > live_repo_clean_overrides_stale_blocked_ar… > last_completed_blocked > active_runtime_lock > queued_backlog_without_active_run > idle_clean" in result.stdout
    assert "last completed: merger-blocked | merger | blocked" in result.stdout
