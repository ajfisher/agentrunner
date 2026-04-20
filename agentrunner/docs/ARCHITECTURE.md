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

And it MUST write the same JSON object to the provided result file path using the canonical helper path exposed by mechanics:
- result artifacts: `emit_result.py`
- handoff artifacts: `emit_handoff.py`

There is no legacy `write_*` helper contract anymore. New runs should treat `emit_*` as the only valid artifact helper interface.

Mechanics-side validation now distinguishes between:
- file exists
- file contains valid artifact JSON
- file contains malformed / under-specified artifact JSON

Current baseline validation:
- all roles: `status`, `role` (or mechanics-normalized equivalent), `summary`, `checks`, `writtenAt`
- developer: explicit `commit` key (nullable allowed)
- reviewer: boolean `approved` and list `findings`
- reviewer follow-up requests: valid handoff artifact required

For follow-up Developer work, mechanics now also passes explicit reviewer artifact paths when available:
- `SOURCE_RESULT_PATH`
- `SOURCE_HANDOFF_PATH`
- `REVIEW_FINDINGS_PATH`

This reduces reliance on prose/history and gives Developer turns a deterministic place to read Reviewer intent first.

See also: `agentrunner/docs/ARTIFACT_CONTRACTS.md`

## Operator CLI surface

Operator-facing docs should treat the routed top-level CLI as the preferred path:

- `python3 -m agentrunner brief`
- `python3 -m agentrunner status`
- `python3 -m agentrunner queue`
- `python3 -m agentrunner initiatives`
- `python3 -m agentrunner watch`

Those commands are thin routers over lower-level script implementations:
- `brief` delegates to `agentrunner/scripts/enqueue_initiative.py`
- `status|queue|initiatives|watch` delegate to `agentrunner/scripts/operator_cli.py`

Compatibility and limitation notes:
- checkout-based docs should assume `python3 -m agentrunner ...` as the real implemented operator command form today
- a bare `agentrunner ...` console-script shim may be packaged in some environments later, but it is not the architectural baseline to assume everywhere yet
- `status.py` and `tick_tailer.py` are intentionally lower-level rebuild/debug/history helpers, not alternate primary operator surfaces
- `api` is the optional machine-facing localhost JSON adapter over the canonical operator snapshot; it is read-only and should not be treated as an internet-facing control plane
- any future browser-facing operator UI should attach to that existing local API surface first (`python3 -m agentrunner api --host 127.0.0.1 --port 8765`) instead of implying a separate control-plane web runtime by default

## Operator adapter stack

Operator-facing surfaces should all sit on the same side of the contract boundary:

- mechanics-owned truth: `state.json`, `queue.json`, `queue_events.ndjson`, `ticks.ndjson`, result/handoff artifacts
- canonical derivative snapshot: `operator_status.json`
- shared read model: `agentrunner/scripts/operator_data.py`
- downstream adapters: text CLI, optional localhost API, optional local TUI, optional MQTT broadcast, and any future web/dashboard surface

Design intent:
- operator adapters read the shared snapshot/read model instead of reconstructing mechanics state ad hoc
- adapters stay read-only unless a later contract explicitly introduces a separate control plane
- the optional TUI/web/API surfaces must not become mechanics prerequisites; dispatch/completion/recovery still work without them
- UI work should preserve the same named operator fields (`status`, `current`, `queue`, `initiative`, `lastCompleted`, `warnings`, `reconciliation`, `updatedAt`) so humans and machines keep seeing the same contract through different lenses

## Initiative status message adapters

AgentRunner may also maintain one compact initiative-scoped status message through
an adapter seam.
This is an operator-facing convenience layer, not mechanics authority.

Design contract:
- the shared lifecycle/persistence contract lives in `agentrunner/scripts/initiative_status.py`
- persistence is initiative-local (`initiatives/<initiativeId>/state.json` under `statusMessage`), not in main `state.json`
- adapters implement the same three operations over that contract:
  - `create`
  - `update`
  - `finalize`
- lifecycle updates should fire only on meaningful initiative boundaries, not every minor tick
- adapters must return a normalized durable message handle so later updates can target the same message instead of forking duplicates
- delivery failures are non-fatal: initiative execution continues and the failure is recorded in initiative-local delivery metadata/history
- the first concrete adapter lives in `agentrunner/scripts/initiative_status_discord.py` and uses the existing OpenClaw `message` seam (`send` for create, `edit` for update/finalize) rather than a bespoke Discord client
- Discord routing stays configurable through compact target metadata (`channel`, `target`, optional `threadId`, optional adapter metadata) so the shared initiative-status contract remains provider-agnostic while still persisting a normalized returned handle (`id`, `channelId`, `threadId`, `provider`, optional `url`)

This keeps the core contract portable for Discord-first delivery now and Telegram/Slack-style adapters later.

For the detailed lifecycle matrix, v1 Discord target shape, and the fixture-driven smoke harness, see `agentrunner/docs/INITIATIVE_STATUS_MESSAGES.md`.

## Operator-facing Discord summaries

Human-visible Discord messages are **not** the source of truth.
Structured state lives in result/handoff JSON artifacts and `ticks.ndjson`.

Likewise, any future operator MQTT broadcast is a downstream snapshot adapter, not an authority.
The MVP contract for that surface lives in `agentrunner/docs/OPERATOR_MQTT_BROADCAST.md` and is intentionally disabled by default.

Discord output should be:
- concise
- role-prefixed (`Developer ›`, `Reviewer ›`, etc.)
- 2–5 short bullets max
- free of raw JSON payloads

This keeps operator channels readable while mechanics consumes deterministic artifacts.
