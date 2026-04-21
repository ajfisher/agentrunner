# Operator Visibility Backlog

## Why this exists

`agentrunner` is getting good at *doing* work, but operator visibility is still too archaeology-heavy.

Right now, understanding what the system is doing often requires manually reconstructing state from:
- `state.json`
- `queue.json`
- `queue_events.ndjson`
- `ticks.ndjson`
- `results/*.json`
- initiative-local files (`brief.json`, `plan.json`, `decision.json`, etc.)

That is acceptable during early mechanics proving, but it is not a good long-term operator surface.

The next usability layer should make it easy to answer:
- What is running right now?
- What is queued next?
- What initiative/phase is active?
- Is anything blocked or stale?
- What just happened?

## Closure/handoff semantic note

Operator surfaces must distinguish four different truths that can otherwise collapse into the same misleading “looks quiet” impression:

- **execution activity** — normal design/implementation/review work is still happening (`closure.state=execution-active`)
- **closure activity** — feature work may be done enough that runtime/queue can briefly look quiet, but non-terminal closure follow-up still remains (`closure.state=closure-active`)
- **blocked state** — operator-visible state is blocked/conflicted and handoff is unsafe (`closure.state=blocked`)
- **true clean idle** — runtime is quiet *and* no non-terminal closure work remains (`closure.state=idle-clean`, `handoffSafe=true`)

Concrete regression case to keep proving:
- feature work is complete
- a Manager closure pass sends the initiative back for Architect replan / pytest-doc proof hardening
- queue depth can briefly hit zero before the next handoff item lands
- operator/watcher surfaces must still report `closure-active` or otherwise clearly show `handoffSafe=false`
- only once the initiative reaches terminal success and runtime is quiet should the surface reconcile to true clean idle

## Desired principle

Define **one canonical operator-facing status artifact** first, then let all surfaces consume that.

Surfaces should be adapters, not archaeologists.

---

## Proposed priority order

### 1) Canonical operator status artifact
Add a small summarized per-project artifact, e.g.:
- `~/.agentrunner/projects/<project>/operator_status.json`

This should be the blessed machine-readable summary for operator-facing tools.

### Draft shape

```json
{
  "project": "agentrunner",
  "status": "active",
  "current": {
    "queueItemId": "agentrunner-tick-tailer-architect",
    "role": "architect",
    "branch": "feature/agentrunner/tick-tailer",
    "startedAt": "2026-04-18T06:57:37Z",
    "ageSeconds": 123
  },
  "queue": {
    "depth": 0,
    "nextIds": []
  },
  "initiative": {
    "initiativeId": "agentrunner-tick-tailer",
    "phase": "design-architect",
    "currentSubtaskId": null
  },
  "lastCompleted": {
    "queueItemId": "agentrunner-tick-tailer-manager",
    "role": "manager",
    "status": "ok",
    "summary": "Wrote the manager brief..."
  },
  "warnings": [],
  "updatedAt": "2026-04-18T07:01:00Z"
}
```

### Minimum fields
- project id
- global project status (`active`, `blocked`, `idle-clean`, `idle-pending`, `conflicted`)
- current item summary
- queue depth + next item ids
- initiative id/phase if present
- last completed item summary
- warnings / stale-run flags
- explicit reconciliation payload (sources + precedence + reasons)
- updated timestamp

### Canonical warning semantics
- `warnings` should be a list of compact structured objects, not a bag of prose strings.
- Each warning should ideally include:
  - `code` (stable machine-readable identifier)
  - `severity` (`info`, `warning`, `error`)
  - `summary` (short operator-facing description)
  - optional `details`
- A stale active run should surface as `code: "stale_run"` based on runtime timestamps/timeouts.
- Warning presence informs the top-level `status`, but warnings themselves remain derivative and must not mutate queue/state.

### Why this comes first
Because every future surface becomes easier if it can read one compact truth file instead of reconstructing live state from multiple artifacts.

---

### 2) Queue / status CLI
Build a proper operator-friendly CLI layer that reads the canonical status artifact first and only falls back to raw mechanics files in explicit, bounded recovery modes.

Candidate commands:
- `agentrunner status --project <project>`
- `agentrunner queue --project <project>`
- `agentrunner initiatives --project <project>`
- `agentrunner watch --project <project>`

### Desired outputs
- current active item
- queue depth / next items
- initiative phase
- last completed item
- blocked/stale warnings
- age/duration hints
- clear operator notes when the blessed artifact is missing or malformed, instead of forcing raw-file archaeology

Operator contract:
- default path: consume `operator_status.json` for compact readable output
- explicit recovery path: allow bounded rebuilds via the CLI and `status.py`
- adjacent history path: leave recent-tick narration to `tick_tailer.py`, rather than overloading the status command

This is the cheapest, highest-leverage visibility surface once the status artifact exists.

---

### 3) Tick-tail helper
The current initiative (`tail_ticks.py`) is part of the same operator-visibility story.

It should remain a narrow, readable recent-history view, not a replacement for the status artifact.

Role in the stack:
- `operator_status.json` → present tense / summarized state
- `tail_ticks.py` → recent history / event timeline

---

### 4) Initiative enqueue CLI
Separate but tightly related operator usability improvement.

A thin wrapper should:
- scaffold an initiative
- write the manager brief
- enqueue the kickoff item through the queue ledger path
- optionally kick one poll
- print a clean operator summary

This removes the current footgun where writing `queue.json` directly looks like an enqueue but is not the authoritative path.
The operator contract should say this plainly: `queue.json` is a materialized view, not an enqueue authority, and duplicate initiative ids must be rejected or converted into a visible `noop` rather than producing a second kickoff.

---

### 5) Optional TUI
Once the canonical status artifact exists, a terminal UI becomes straightforward.

Current bounded contract direction:
- canonical launch shape: `python3 -m agentrunner tui --project <project>`
- local-only and read-only over the canonical operator snapshot/read model
- no queue mutation, retry, approval, or control affordances
- first runtime choice should stay conservative (stdlib redraw loop or equivalently bounded local framework), so the operator contract settles before a heavier TUI stack does

Potential layout:
- project list
- active item / role / branch
- queue view
- recent tick stream
- warnings / stale indicators

Recommendation: keep this out of the critical path until the status artifact contract exists.

---

### 6) Optional web / dashboard integration
Potentially expose operator status through:
- a small local web page
- the existing local JSON endpoint
- MQTT status topics for the cluster dashboard

Current bounded direction:
- do **not** assume a separate `python3 -m agentrunner web` runtime yet
- prefer attaching any browser UI to `python3 -m agentrunner api --host 127.0.0.1 --port 8765`
- keep the surface localhost-first, read-only, and downstream of the canonical operator snapshot contract
- do not imply queue/state mutation or public hosting by default

If MQTT broadcast coverage exists, keep it hermetic by default: prove payload/topic shape through a stub publisher seam rather than depending on a real broker during ordinary CI runs.

Useful for ambient visibility in the studio.

Candidate displayed fields:
- project name
- idle / active / blocked
- current role
- current queue item
- initiative phase
- queue depth
- stale warning / age
- reconciliation winner / updated timestamp

Again: this should consume the canonical status artifact rather than inventing its own reconstruction logic.

---

### 7) Optional Discord status card / announcements
Potential future operator channel surface.

Possible modes:
- manual “show me status” response
- transition-triggered summaries for:
  - blocked runs
  - architect plan ready
  - reviewer approved
  - merger complete

Recommendation: do **not** start here. It is useful, but it becomes much simpler and less noisy once the operator status artifact exists.

---

## Recommended implementation order

1. `operator_status.json` canonical artifact
2. queue/status CLI surface
3. tick tailer helper (already underway)
4. initiative enqueue CLI
5. optional TUI
6. optional dashboard/web integration
7. optional Discord status card/announce layer

---

## Acceptance for the first visibility slice

A good first milestone would let an operator answer these from one command:
- what is running now?
- what is queued?
- what initiative phase is active?
- what completed most recently?
- is anything stale or blocked?

If that is easy, the later surfaces are mostly packaging.

---

## Design note

The real architectural choice here is:

> Do we keep building many small ad-hoc views over raw runtime files,
> or do we bless one operator-facing summary contract?

Recommendation: bless the contract.

That keeps the mechanics truth append-only and detailed, while giving humans a stable window into the system.
