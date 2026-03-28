# Architecture

## Two-layer model

### 1) Mechanics layer (deterministic, outside agent control)
Responsibilities:
- Maintain per-project **state** and **queue**
- Enforce **run-lock** (one job running at a time)
- Write **append-only tick logs** (ground truth)
- Dispatch agent runs via **`/hooks/agent`**
- Detect completion via deterministic **result files**

This layer should be boring and auditable.

### 2) Cognition layer (agent turns)
Responsibilities:
- Execute one bounded task according to the role prompt
- Report results in a structured way
- Write a deterministic result artifact for mechanics to observe

The agent must not be able to rewrite mechanics history.

## Current dispatch pattern

- A small **invoker** runs on a fast cadence (e.g. every 2 minutes).
- It pops the next queue item and dispatches it with `POST /hooks/agent`.
- It supplies a deterministic `sessionKey` and a `RESULT_PATH`.
- The worker writes `AGENTRUNNER_RESULT_JSON` as its last line and writes the same JSON to the result file.
- On the next invoker tick, mechanics sees the result file, appends a tick record, updates queue state, and unlocks.

## Invariants
- **Append-only**: ticks are never rewritten; corrections are new entries.
- **Branch discipline**: Dev work lands on a feature/fix branch; review/merge operate on that branch.
- **Bounded extra dev turns**: at most 1 (configurable) extra dev item may be inserted before the next review.
- **Deterministic identity**: each dispatched run has a stable session key:
  - `hook:agentrunner:<project>:<queueItemId>`

## Worker output contract
Each worker run MUST end with a single line:

`AGENTRUNNER_RESULT_JSON: { ... }`

And it MUST write the same JSON object to the provided result file path.

## Operator-facing Discord summaries

Human-visible Discord messages are **not** the source of truth.
Structured state lives in result/handoff JSON artifacts and `ticks.ndjson`.

Discord output should be:
- concise
- role-prefixed (`Developer ›`, `Reviewer ›`, etc.)
- 2–5 short bullets max
- free of raw JSON payloads

This keeps operator channels readable while mechanics consumes deterministic artifacts.
