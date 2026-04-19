#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        },
    )

    for command, needles in {
        "status": ["project: demo", "status: ACTIVE | developer-smoke | developer | feature/agentrunner/real-cli-surface | age=19s"],
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
