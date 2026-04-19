# agentrunner

A small, git-versioned runner framework to orchestrate autonomous agent work *deterministically*.

Core idea: split the system into two layers:
- **Mechanics layer** (outside agent control): queue, cadence, locks, append-only logs, scheduling.
- **Cognition layer** (agent turns): role-specific prompts that execute bounded tasks.

This repo contains the mechanics code + role prompt templates + docs/schemas.

Runtime state lives in **`/home/openclaw/.agentrunner/`** (one subdir per project).

## Design goals
- Append-only logs (no rewriting history)
- Git-flow friendly (feature branches, review, merge)
- Queue-driven (no modulo role math required)
- Bounded autonomy (limits on extra dev turns)
- Conservative merge behavior by default (prefer fast-forward; block rather than improvise)
- Reliable unattended progression via lightweight invoker polling (`scripts/reliability_poll.py`)

## Layout
- `agentrunner/scripts/` – invoker + utilities (canonical artifact helpers: `emit_result.py`, `emit_handoff.py`)
- `agentrunner/prompts/` – role prompt templates
- `agentrunner/schemas/` – JSON Schemas
- `agentrunner/docs/` – architecture + how-to

## Next
- Implement invoker: 1-minute supervisor that schedules one-shot OpenClaw cron jobs.

## Scheduling bridge (implemented)

`agentrunner/scripts/invoker.py` can now schedule OpenClaw **one-shot** cron jobs via:

- `openclaw cron add --json --at <iso> --session isolated --message ...`

### Example (manual)

```bash
mkdir -p /home/openclaw/.agentrunner/projects/picv_spike
cp agentrunner/examples/state.json /home/openclaw/.agentrunner/projects/picv_spike/state.json
cp agentrunner/examples/queue.json /home/openclaw/.agentrunner/projects/picv_spike/queue.json

python3 agentrunner/scripts/invoker.py \
  --project picv_spike \
  --state-dir /home/openclaw/.agentrunner/projects/picv_spike \
  --announce \
  --channel discord \
  --to channel:1477159463143084217
```

### System cron (supervisor)

Run invoker every minute:

```cron
* * * * * /usr/bin/python3 /home/openclaw/projects/agentrunner/agentrunner/scripts/invoker.py --project picv_spike --state-dir /home/openclaw/.agentrunner/projects/picv_spike --announce --channel discord --to channel:1477159463143084217
```

## Operator status CLI

Use the canonical operator CLI entrypoint for read-only status/queue/initiative views.
It prefers `operator_status.json` and only falls back to a bounded manual rebuild when you ask for it explicitly, so operators do not have to reconstruct state by hand from `state.json`, `queue.json`, `ticks.ndjson`, and `results/*.json` during the normal happy path.

```bash
python3 agentrunner/scripts/operator_cli.py status --project picv_spike
```

Useful variants:
- queue preview: `python3 agentrunner/scripts/operator_cli.py queue --project picv_spike`
- initiative summary: `python3 agentrunner/scripts/operator_cli.py initiatives --project picv_spike`
- bounded manual rebuild when the artifact is missing: `python3 agentrunner/scripts/operator_cli.py status --project picv_spike --rebuild-missing --write-rebuild`
- watch mode: `python3 agentrunner/scripts/operator_cli.py watch --project picv_spike --interval 5`

How the operator surfaces fit together:
- `operator_cli.py` is the canonical read-only operator entrypoint for present-tense status/queue/initiative views.
- `operator_status.json` is the blessed derivative artifact that keeps those views compact and machine-readable.
- `status.py` is the explicit rebuild/debug helper when you intentionally want to regenerate the artifact from mechanics files.
- `tick_tailer.py` is the recent-history companion for "what just happened?", not a replacement for the status artifact.

Rule of thumb:
- reach for `agentrunner status` / `queue` / `initiatives` first
- use `status.py` only for recovery/debugging or when you intentionally want to refresh `operator_status.json`
- use `tick_tailer.py` when you want a compact validated event timeline instead of the current snapshot

## Tick tailer helper

For a compact recent-history view of tick activity, use:

```bash
python3 agentrunner/scripts/tick_tailer.py --project agentrunner
```

This helper is intentionally complementary to `status.py`:
- `status.py` answers the present-tense operator question: what is running, queued, or blocked right now?
- `tick_tailer.py` answers the recent-history question: what just happened over the last few validated ticks?

Useful variants:
- latest 25 valid tick records: `python3 agentrunner/scripts/tick_tailer.py --project agentrunner -n 25`
- stream newly appended valid records without replaying the initial snapshot twice: `python3 agentrunner/scripts/tick_tailer.py --project agentrunner --follow`

## Initiative enqueue helper

Use the stdlib-only enqueue helper to seed a new initiative kickoff safely:

```bash
python3 agentrunner/scripts/enqueue_initiative.py \
  --project agentrunner \
  --initiative-id agentrunner-enqueue-cli \
  --branch feature/agentrunner/enqueue-cli \
  --base master \
  --manager-brief-path /path/to/brief.json
```

Example using inline JSON instead of a file:

```bash
python3 agentrunner/scripts/enqueue_initiative.py \
  --project agentrunner \
  --initiative-id docs-refresh \
  --branch feature/agentrunner/docs-refresh \
  --base master \
  --manager-brief-json '{
    "title": "Refresh docs",
    "objective": "Clarify operator docs for the enqueue flow.",
    "desiredOutcomes": ["Docs updated"],
    "definitionOfDone": ["README and state docs mention the canonical enqueue path"]
  }'
```

Operator-facing happy-path output is a compact JSON summary containing at least:
- `status: "ok"`
- `initiativeId`
- `queueItemId` (for the kickoff Manager item)
- `managerBriefPath`
- `briefAction`
- optional `pollSummary` / `pollDetails` when `--poll-after-enqueue` is used

Guardrails before any writes occur:
- requires exactly one manager brief source (`--manager-brief-path`, `--manager-brief-artifact-path`, `--manager-brief-json`, or `--manager-brief-stdin`)
- rejects duplicate initiative ids already present in the runnable queue, active run state, or initiative-local state/artifacts
- rejects pre-existing kickoff result/handoff/review artifacts for the same initiative
- normalizes the brief into `initiatives/<initiativeId>/brief.json` and enqueues the canonical Manager kickoff item only after preflight passes

Important: `queue.json` is a **materialized view**, not an enqueue authority.
Do **not** add items by editing `queue.json` directly. The authoritative enqueue path is the queue-event ledger via `enqueue_initiative.py` (or other ledger-writing helpers), after which mechanics rebuilds `queue.json` as a convenience view.

Duplicate handling is intentionally conservative:
- if the same initiative is already active, pending, or has initiative-local kickoff artifacts, the helper returns a `noop` summary instead of enqueueing a second kickoff
- if `state.json` already points at a different active initiative, preflight fails rather than silently changing focus

Lightweight proof / operator test recipe:
1. Prepare a disposable project state dir under `~/.agentrunner/projects/<scratch-project>/`.
2. Run `enqueue_initiative.py` once with a valid brief and confirm the summary reports `status: "ok"` plus `<initiativeId>-manager` as the kickoff item.
3. Run the same command again with the same `initiativeId` and confirm the summary reports `status: "noop"` with an “already active/pending/exists” style message.
4. Optionally run once with `--poll-after-enqueue` to confirm the helper also reports the reliability poll summary without requiring any direct `queue.json` edits.
