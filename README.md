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
  - includes `OPERATOR_MQTT_BROADCAST.md` for the disabled-by-default MQTT operator snapshot contract

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

## Canonical MVP CLI surface

The preferred operator path is the routed top-level CLI:

```bash
python3 -m agentrunner <command> [...args]
```

Implemented commands today:
- `python3 -m agentrunner brief`
- `python3 -m agentrunner status`
- `python3 -m agentrunner queue`
- `python3 -m agentrunner initiatives`
- `python3 -m agentrunner watch`
- `python3 -m agentrunner api`
- `python3 -m agentrunner tui`

Important limitation today:
- the routing contract is real and implemented now
- a bare `agentrunner ...` console-script shim may exist in some installs later, but should **not** be assumed in checkout-based/operator docs yet
- when in doubt, use `python3 -m agentrunner ...` as the canonical command form

Routing contract:
- `brief` delegates to `agentrunner/scripts/enqueue_initiative.py` via `enqueue_initiative.main(argv)`
- `status|queue|initiatives|watch` delegate to `agentrunner/scripts/operator_cli.py` via `operator_cli.main([subcommand, *argv])`
- `api` delegates to `agentrunner/scripts/operator_api.py` via `operator_api.main(argv)`
- `tui` delegates to `agentrunner/scripts/operator_tui.py` via `operator_tui.main(argv)`
- passthrough args are forwarded unchanged after the top-level subcommand; an optional `--` separator is accepted and stripped by the router before delegation
- routed commands intentionally preserve the underlying script exit codes instead of inventing new router-specific semantics

This keeps the top-level CLI canonical without duplicating mechanics logic in a second implementation.

## Operator status CLI

Use the routed top-level CLI first for read-only operator views. The lower-level scripts remain supported as compatibility paths and implementation surfaces underneath the router.

The status surface prefers `operator_status.json` and only falls back to a bounded manual rebuild when you ask for it explicitly, so operators do not have to reconstruct state by hand from `state.json`, `queue.json`, `ticks.ndjson`, and `results/*.json` during the normal happy path.

```bash
python3 -m agentrunner status --project picv_spike
python3 agentrunner/scripts/operator_cli.py status --project picv_spike   # compatibility / direct script form
```

Useful routed variants:
- queue preview: `python3 -m agentrunner queue --project picv_spike`
- initiative summary: `python3 -m agentrunner initiatives --project picv_spike`
- watch mode: `python3 -m agentrunner watch --project picv_spike --interval 5`

Intended watch workflow:
- start with `status` when you want a single current snapshot
- move to `watch` when you want the same operator truth re-rendered as one grouped watch surface instead of repeatedly re-running separate commands
- treat the watch surface as a single-page summary of now / next up / recent completion / warnings, not as a control panel
- when the surface looks quiet, check the waiting / blocked / handoff-safe cues before assuming the initiative is actually done

Useful compatibility/debug variants:
- direct script path: `python3 agentrunner/scripts/operator_cli.py queue --project picv_spike`
- bounded manual rebuild when the artifact is missing: `python3 agentrunner/scripts/operator_cli.py status --project picv_spike --rebuild-missing --write-rebuild`

How the operator surfaces fit together:
- `python3 -m agentrunner status|queue|initiatives|watch` is the preferred operator entrypoint.
- `operator_cli.py` is the lower-level compatibility implementation surface underneath that router.
- `operator_status.json` is the blessed derivative artifact that keeps current-state views compact and machine-readable.
- `operator_data.py` is the shared stdlib-only read model that owns artifact-first loading, bounded missing/malformed rebuild fallback, and the named snapshot accessors downstream adapters should use instead of poking through raw dicts.
- `status.py` is the explicit rebuild/debug helper when you intentionally want to regenerate the artifact from mechanics files.
- `tick_tailer.py` is the recent-history companion for "what just happened?", not a replacement for the status artifact.
- browser-facing UI is intentionally bounded to a local read-only attach path over the existing API entrypoint; see `agentrunner/docs/OPERATOR_WEB_UI.md`.

Regression proof coverage for the shared operator data layer now explicitly checks:
- canonical-artifact reads without opportunistic raw-file archaeology
- bounded fallback only when `--rebuild-missing` / `--rebuild-malformed` is explicitly requested
- minimum accessor fields future TUI / API / MQTT / web adapters will rely on (`status`, `current`, `queue`, `initiative`, `lastCompleted`, `warnings`, `reconciliation`, `updatedAt`)

Proof-check bootstrap for a clean checkout:
- run `./scripts/bootstrap_pytest.sh`
- then run `.venv/bin/pytest -q`
- the dev extra in `pyproject.toml` currently installs `pytest` for this proof path

Rule of thumb:
- reach for `python3 -m agentrunner status|queue|initiatives|watch --project <project>` first
- use `python3 -m agentrunner api --host 127.0.0.1 --port 8765` when you want a tiny optional local read-only HTTP adapter over the canonical operator snapshot (JSON at `/v1/operator/snapshot?project=<project>`, HTML at `/operator?project=<project>`)
- the browser page at `/operator?project=<project>` is intentionally a thin local read-only renderer that auto-refreshes by polling that same snapshot every 5 seconds; it is meant for colocated operator visibility, not as a second runtime or a write/control surface
- the intended watch surface groups the same operator truths onto one page: current status now, next up queue context, recent completion, and operator cues for waiting / blocked / handoff-safe state
- use `python3 -m agentrunner tui --project <project>` when you want a local terminal surface that keeps re-rendering the same canonical read model without adding any write/control affordances
- for a browser-facing UI, attach to that existing local API entrypoint rather than inventing a second control/runtime surface; the bounded contract is documented in `agentrunner/docs/OPERATOR_WEB_UI.md`
- keep the API on loopback unless you are intentionally placing another authenticated/local transport in front of it; the intended default is machine-facing localhost use, not a public/operator write surface
- the TUI is intentionally local and optional; today it is a small stdlib-only redraw loop over `operator_data`, not a second runtime, daemon, or operator authority
- use `python3 agentrunner/scripts/operator_cli.py ...` when you need the direct compatibility path or are debugging the router/delegation layer
- use `status.py` only for recovery/debugging or when you intentionally want to refresh `operator_status.json`
- use `tick_tailer.py` when you want a compact validated event timeline instead of the current snapshot

### Optional operator API (localhost-only by default)

When a local dashboard, TUI, script, or other machine-facing consumer wants JSON instead of terminal text, run:

```bash
python3 -m agentrunner api --host 127.0.0.1 --port 8765
```

Intended role:
- expose the already-built canonical `operator_status.json` snapshot over a tiny stdlib HTTP surface
- stay strictly **read-only** and derivative of mechanics-owned runtime truth
- give local consumers a stable JSON contract without forcing them to parse CLI text or reconstruct state from raw mechanics files

Local-use expectations:
- bind to `127.0.0.1` by default
- treat it as an **optional localhost adapter** for colocated tools, not the main human operator interface
- if you need remote access later, put an explicit authenticated transport/proxy in front of it rather than treating the raw server as an internet-facing API

Current endpoints:
- `GET /v1/operator/snapshot?project=<project>`
- `HEAD /v1/operator/snapshot?project=<project>`
- `GET /operator?project=<project>`
- `HEAD /operator?project=<project>`
- write methods are rejected with `405 method_not_allowed`

The browser page is intentionally thin and read-only:
- it renders the same canonical operator fields as the CLI/TUI surfaces (`status`, `current`, `queue`, `initiative`, `lastCompleted`, `warnings`, `reconciliation`, `updatedAt`)
- it degrades clearly when the canonical snapshot is missing by returning a bounded HTML "snapshot unavailable" page instead of inventing fallback controls
- it exposes no enqueue/retry/approve/write affordances or route handlers

For smoke proofs without a running local API or live mechanics files, render HTML directly from a fixture or built-in sample:
- `python3 agentrunner/scripts/operator_web.py --smoke-sample > /tmp/operator.html`
- `python3 agentrunner/scripts/operator_web.py --snapshot-file /path/to/envelope.json --output /tmp/operator.html`
- open `/tmp/operator.html` in a browser to verify the refreshed status presentation layout without any live mechanics/API dependency

For a local end-to-end smoke on the intended attach path:
- start the loopback-only API: `python3 -m agentrunner api --host 127.0.0.1 --port 8765`
- open `http://127.0.0.1:8765/operator?project=<project>`
- verify the page advertises auto-refresh, updates its refresh-status line after the first polling cycle, and stays read-only while reflecting the same canonical snapshot fields exposed at `/v1/operator/snapshot?project=<project>`

This same localhost-only API is the chosen attach surface for the optional browser UI. The UI is expected to be a thin read-only renderer over the canonical snapshot payload, not a queue/state mutation path and not a public hosting default.

Operator adapter stack for future UI work:
- CLI (`python3 -m agentrunner status|queue|initiatives|watch`) = preferred human/operator entrypoint
- localhost API (`python3 -m agentrunner api ...`) = canonical machine-facing adapter for JSON/HTML snapshot access
- web UI (`GET /operator?project=<project>`) = optional browser renderer over that API, not a second runtime authority
- TUI (`python3 -m agentrunner tui ...`) = optional local terminal adapter over the same snapshot/read model
- MQTT broadcast = optional downstream publish path for the same canonical operator data, disabled by default

### Optional local operator TUI

When a human operator wants a richer terminal view than the plain `status`/`queue` text, use:

```bash
python3 -m agentrunner tui --project picv_spike
```

Where it sits in the operator stack:
- mechanics-owned truth still lives in `state.json`, `queue.json`, `queue_events.ndjson`, `ticks.ndjson`, and result artifacts
- `operator_status.json` remains the blessed derivative snapshot built from that truth
- `agentrunner/scripts/operator_data.py` is the shared read model all operator adapters should consume first
- the text CLI, localhost API, optional MQTT broadcast, future web views, and this TUI are all adapters over that same operator contract
- the TUI is therefore a local human-facing lens, not a second runtime, controller, or source of truth

Current bounded contract:
- local terminal surface only; it is not a daemon, web app, or new mechanics authority
- read-only over the canonical `operator_status.json` snapshot via `agentrunner/scripts/operator_data.py`
- no queue mutation, retry, approve, or control actions; it is visibility-only by design
- framework/runtime choice for this first slice is intentionally conservative: stdlib-only terminal redraws instead of introducing a heavyweight TUI stack before the operator contract settles
- install/dependency expectation is intentionally light: no extra TUI package is required beyond the normal Python runtime; if a platform lacks `curses`, use `--once` or `--text-watch` as the fallback proof/debug path
- because it is optional and adapter-only, it is not part of the mechanics critical path for dispatch, completion, or recovery

Useful smoke/debug variants:
- single render for proofs/tests: `python3 -m agentrunner tui --project picv_spike --once`
- fixture-driven proof path with no live mechanics reads: `python3 scripts/test_operator_tui.py`
- explicit bounded rebuild fallback: `python3 -m agentrunner tui --project picv_spike --rebuild-missing --write-rebuild`

This keeps the TUI as an optional fourth operator surface after the shared data layer, the text CLI, and the localhost JSON API.

For downstream MQTT dashboard/broker integration, see `agentrunner/docs/OPERATOR_MQTT_BROADCAST.md`.
That contract is intentionally disabled by default and keeps MQTT as a read-only broadcast of canonical operator state rather than a control plane.
The regression proof for this surface is intentionally hermetic: `python3 scripts/test_operator_mqtt.py` injects a fake/stub publisher callable, so normal local runs and CI do not require `mosquitto_pub`, a reachable broker, or any external network.

Response shape on success (`200`):
- `project` — requested project id
- `artifactPath` — canonical snapshot file path
- `notes` — non-fatal loader notes
- `snapshot` — the canonical operator-status artifact payload

Minimum nested `snapshot` contract fields mirror `operator_status.json`:
- `status`
- `current`
- `queue`
- `initiative`
- `lastCompleted`
- `warnings`
- `reconciliation`
- `updatedAt`

Common error responses:
- `400 missing_project`
- `400 invalid_project`
- `404 snapshot_unavailable`
- `404 not_found`
- `405 method_not_allowed`

Reconciliation visibility rules for operator/debug output:
- `reconciliation:` should show the final decision plus the winning source/rule/precedence (`winner=source=..., rule=..., p...`)
- `operator hierarchy:` should show the named policy/version plus the explicit precedence order
- the live-repo clean-tail override is intentionally narrow: it only demotes a stale blocked artifact when live repo truth is present, fresh, clean, has a visible HEAD, and proves the repo is aligned with the expected branch policy
- if those conditions are not met, the blocked artifact still wins and operator output should make that obvious

## Tick tailer helper

For a compact recent-history view of tick activity, use:

```bash
python3 agentrunner/scripts/tick_tailer.py --project agentrunner
```

This helper is intentionally complementary to the routed status command and to `status.py`:
- `python3 -m agentrunner status` answers the present-tense operator question: what is running, queued, or blocked right now?
- `status.py` is the explicit rebuild/debug path for regenerating the status artifact.
- `tick_tailer.py` answers the recent-history question: what just happened over the last few validated ticks?

Useful variants:
- latest 25 valid tick records: `python3 agentrunner/scripts/tick_tailer.py --project agentrunner -n 25`
- stream newly appended valid records without replaying the initial snapshot twice: `python3 agentrunner/scripts/tick_tailer.py --project agentrunner --follow`

## Initiative enqueue helper

Use the routed top-level CLI for operator-facing initiative kickoff; keep the direct script path as a compatibility/lower-level option.

```bash
python3 -m agentrunner brief \
  --project agentrunner \
  --initiative-id agentrunner-enqueue-cli \
  --branch feature/agentrunner/enqueue-cli \
  --base master \
  --manager-brief-path /path/to/brief.json
```

Compatibility / lower-level equivalent:

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
python3 -m agentrunner brief \
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
Do **not** add items by editing `queue.json` directly. The authoritative enqueue path is the queue-event ledger via the routed `brief` command (or `enqueue_initiative.py` as the lower-level compatibility helper), after which mechanics rebuilds `queue.json` as a convenience view.

Duplicate handling is intentionally conservative:
- if the same initiative is already active, pending, or has initiative-local kickoff artifacts, the helper returns a `noop` summary instead of enqueueing a second kickoff
- if `state.json` already points at a different active initiative, preflight fails rather than silently changing focus

Lightweight proof / operator test recipe:
1. Prepare a disposable project state dir under `~/.agentrunner/projects/<scratch-project>/`.
2. Run `python3 -m agentrunner brief` once with a valid brief and confirm the summary reports `status: "ok"` plus `<initiativeId>-manager` as the kickoff item.
3. Run the same command again with the same `initiativeId` and confirm the summary reports `status: "noop"` with an “already active/pending/exists” style message.
4. Optionally run once with `--poll-after-enqueue` to confirm the helper also reports the reliability poll summary without requiring any direct `queue.json` edits.
