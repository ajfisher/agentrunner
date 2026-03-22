# State + Queue

Runtime state lives in `/home/openclaw/.agentrunner/projects/<project>/`.

Files:
- `state.json` – lock + current run info
- `queue.json` – materialized runnable queue
- `queue_events.ndjson` – append-only ledger of queue mutations
- `ticks.ndjson` – append-only ground truth of runs

Queue events are the source of truth; `queue.json` is a convenience view.

## Queue mutations

Queue is driven by an append-only ledger (`queue_events.ndjson`). Supported kinds:
- `ENQUEUE` / `INSERT_FRONT` (with `item`)
- `CANCEL` (with `id`)
- `DEQUEUE` (with `id`)
- `DONE` (with `id`, `status`)

`queue.json` is a materialized view rebuilt by `queue_ledger.py`.

## Completion + unlocking

`invoker.py` stores the OpenClaw cron `jobId` in `state.json.current.jobId`.
On subsequent invocations, invoker polls:

- `openclaw cron runs --id <jobId> --limit 1`

When the job has an entry with `action="finished"`, invoker:
- appends a tick record to `ticks.ndjson`
- writes a `DONE` event to the queue ledger
- clears `state.running` and `state.current`

## Extra Developer Turn reset policy

State includes `policy.extraDevTurnReset` to control when mechanics resets `runtime.extraDevTurnsUsed`.
Supported values:
- `on_branch_change` (default): reset when the next dequeued item targets a different branch.
- `on_non_dev`: reset when the next dequeued item is not a Developer role.
- `on_review_start`: reset when the next dequeued item is a Reviewer role.
This reset is mechanics-owned; Architect/Manager may recommend policy, but workers do not directly mutate counters.
