# Architecture

## Two-layer model

### 1) Mechanics layer (deterministic, outside agent control)
Responsibilities:
- Maintain per-project **state** and **queue**
- Enforce **run-lock** (one job running at a time)
- Write **append-only tick logs** (ground truth)
- Schedule/trigger agent runs (OpenClaw one-shot cron jobs)

This layer should be boring and auditable.

### 2) Cognition layer (agent turns)
Responsibilities:
- Execute one bounded task according to the role prompt
- Report results in a structured way

The agent must not be able to rewrite mechanics history.

## Scheduling pattern: invoker → one-shot jobs

- A small **invoker** runs on a fast cadence (e.g. every minute).
- It pops the next queue item and schedules an OpenClaw cron one-shot job.
- When the job finishes, it appends a tick record.

## Invariants
- **Append-only**: ticks are never rewritten; corrections are new entries.
- **Branch discipline**: Dev work lands on a feature branch; review/merge operate on that branch.
- **Bounded extra dev turns**: at most 1 (configurable) extra dev item may be inserted before the next review.

## Worker output contract (structured footer)

Each worker run MUST end with a single line:

`AGENTRUNNER_RESULT_JSON: { ... }`

The invoker parses this from the cron run summary and uses it for:
- tick records (`ticks.ndjson`)
- bounded insertion of an extra Developer turn (`INSERT_FRONT`)
