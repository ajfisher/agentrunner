# State + Queue

Runtime state lives in `/home/openclaw/.agentrunner/projects/<project>/`.

Files:
- `state.json` – lock + current run info
- `queue.json` – materialized runnable queue
- `queue_events.ndjson` – append-only ledger of queue mutations
- `ticks.ndjson` – append-only ground truth of completed runs
- `results/<queueItemId>.json` – deterministic completion/result artifact written by workers

Queue events are the source of truth; `queue.json` is a convenience view.

For a quick read-only operator snapshot across these files, use:
`python3 agentrunner/scripts/status.py --state-dir /home/openclaw/.agentrunner/projects/<project>`
It summarizes active/idle state, a short queue view, the last completed item, and the latest tick/result hint.

## Queue mutations
Supported kinds:
- `ENQUEUE` / `INSERT_FRONT` (with `item`)
- `CANCEL` (with `id`)
- `DEQUEUE` (with `id`)
- `DONE` (with `id`, `status`)

`queue.json` is a materialized view rebuilt by `queue_ledger.py`.

## Dispatch + completion
Current dispatch uses `/hooks/agent` rather than CLI cron scheduling.

The invoker stores in `state.json.current`:
- `queueItemId`
- `role`
- `runId`
- `sessionKey`
- `resultPath`
- `startedAt`

Completion rule:
- if `results/<queueItemId>.json` exists, the invoker treats the run as complete
- it appends a tick record to `ticks.ndjson`
- writes a `DONE` event to the queue ledger
- clears `state.running` and `state.current`

## Extra Developer Turn reset policy
State includes `policy.extraDevTurnReset` to control when mechanics resets `runtime.extraDevTurnsUsed`.
Supported values:
- `on_branch_change` (default): reset when the next dequeued item targets a different branch.
- `on_non_dev`: reset when the next dequeued item is not a Developer role.
- `on_review_start`: reset when the next dequeued item is a Reviewer role.

This reset is mechanics-owned; Architect/Manager may recommend policy, but workers do not directly mutate counters.

## Reliability polling (recommended)

Because queue/state advancement happens when `invoker.py` runs, unattended operation should use a lightweight periodic poller.

Script:
- `agentrunner/scripts/reliability_poll.py`

Typical usage:
- Poll all projects with active work (running or non-empty queue):
  - `python3 agentrunner/scripts/reliability_poll.py`
- Poll a single project:
  - `python3 agentrunner/scripts/reliability_poll.py --project agentrunner`
- Dry-run command preview:
  - `python3 agentrunner/scripts/reliability_poll.py --dry-run`

User-systemd timer (recommended for unattended progression):
- Service/timer templates live in:
  - `scripts/systemd/agentrunner-reliability-poll.service`
  - `scripts/systemd/agentrunner-reliability-poll.timer`
- Install for the current user:
  - `mkdir -p ~/.config/systemd/user`
  - `cp scripts/systemd/agentrunner-reliability-poll.{service,timer} ~/.config/systemd/user/`
  - `systemctl --user daemon-reload`
  - `systemctl --user enable --now agentrunner-reliability-poll.timer`
- Verify:
  - `systemctl --user status agentrunner-reliability-poll.timer`
  - `journalctl --user -u agentrunner-reliability-poll.service -n 50 --no-pager`

Notes:
- By default polling does **not** announce to chat (to avoid noise).
- Use `--announce --channel ... --to ...` only when you intentionally want operator messages forwarded during polls.

## Tick tailer helper

For a compact read-only view of recent tick activity, use:
`python3 agentrunner/scripts/tick_tailer.py --project <project>`

Typical usage examples:
- Show the latest 10 valid tick records for a project:
  - `python3 agentrunner/scripts/tick_tailer.py --project agentrunner`
- Show the latest 25 valid tick records:
  - `python3 agentrunner/scripts/tick_tailer.py --project agentrunner -n 25`
- Follow newly appended valid tick records after the initial snapshot:
  - `python3 agentrunner/scripts/tick_tailer.py --project agentrunner --follow`

Intent:
- keep operator output compact and human-scannable rather than dumping raw JSON
- highlight the most useful fields first: timestamp, queue item, role, status, branch, and a clipped detail
- tolerate noisy logs by skipping malformed JSON lines instead of failing the whole read

Bounded behavior:
- `--follow` only streams records appended after the initial snapshot; it does not replay the entire file again
- malformed non-empty lines are skipped and reported as a note so operators can spot log damage without losing valid records
- empty logs or logs with no valid JSON records produce a clear one-line message instead of a traceback
- if the ticks log or project directory is missing, the helper exits with an error message rather than creating files or mutating runtime state
