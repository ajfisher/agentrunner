# State + Queue

Runtime state lives in `/home/openclaw/.agentrunner/projects/<project>/`.

Files:
- `state.json` – lock + current run info
- `queue.json` – materialized runnable queue
- `queue_events.ndjson` – append-only ledger of queue mutations
- `ticks.ndjson` – append-only ground truth of completed runs
- `results/<queueItemId>.json` – deterministic completion/result artifact written by workers
- `operator_status.json` – canonical operator-facing status summary derived from the runtime truth files above

## Optional GitHub-backed workflow mirroring (Phase 1)

Phase 1 adds an **optional mirror seam** for GitHub issue/PR visibility without changing local mechanics authority.

Authority rules:
- local queue/state/ticks/results remain the only scheduling and completion authority
- GitHub is an optional mirror / projection surface for operators and collaborators
- a missing, stale, or failed GitHub sync must not rewrite `queue.json`, `queue_events.ndjson`, `ticks.ndjson`, or result artifacts
- any GitHub degradation should be recorded as state, not silently treated as queue truth

Project-level configuration location:
- repo/owner settings live in the repo-controlled `pyproject.toml` under `[tool.agentrunner.github]`
- this keeps stable GitHub coordinates with the project source, rather than burying them in ephemeral runtime state
- Phase 1 expected fields are:
  - `enabled` — boolean toggle for GitHub mirroring
  - `owner` — GitHub owner/org slug
  - `repo` — GitHub repository name
  - `baseUrl` — optional GitHub API/base URL override for enterprise/self-hosted setups

Initiative-local persistence location:
- persisted GitHub linkage and sync health live under `initiatives/<initiativeId>/state.json` in a compact `githubMirror` block
- this is initiative-local on purpose: issue/PR linkage belongs to the initiative timeline, not the global queue authority
- Phase 1 expected persisted fields are:
  - `issue` — optional linked issue summary (`number`, `id`, `url`, `state`)
  - `pullRequest` — optional linked PR summary (`number`, `id`, `url`, `state`, `headRef`, `baseRef`)
  - `lastSyncAt` — last successful mirror timestamp
  - `degradedSync` — optional degradation record when mirror writes/reads fail non-fatally
    - recommended fields: `status`, `reason`, `firstSeenAt`, `lastSeenAt`, `lastAttemptAt`, `summary`

Boundary rule:
- `state.json.initiative` may summarize that mirrored state for operator convenience, but the durable issue/PR linkage and degraded-sync record live in initiative-local state
- operator surfaces may reflect degraded GitHub sync as warnings, but they must continue to derive execution truth from local mechanics files first

## `state.json.initiative` pointer contract

When present, `state.json.initiative` is the project's **active initiative pointer**.
It is intentionally a compact pointer to the initiative operators should inspect right now, not a full archival record of every initiative outcome.

Interpretation rules:
- present pointer = this initiative is still the active context for execution, recovery, or operator attention
- absent pointer = no initiative is currently active in main project state
- richer per-initiative details should live under `initiatives/<initiativeId>/...`, with the main-state pointer linking or summarizing as needed

Closure semantics:
- after **successful closure** (for example an initiative completes and merge/closure succeeds), clear `state.json.initiative`
- after **blocked or error closure**, mechanics may intentionally retain `state.json.initiative` so operators can still see which initiative needs recovery work
- a retained pointer after blocked/error closure should be surfaced as blocked/stale context, not mistaken for healthy forward progress
- once an initiative has reached a terminal-success phase (`completed` / `closed`), later stray queue items carrying that initiative metadata must not reactivate the main-state pointer or restart phase advancement for that initiative

## Initiative status message contract

Initiative-local state may also persist a compact `statusMessage` block under
`initiatives/<initiativeId>/state.json`.
This is the mechanics-owned persistence seam for a single updatable ops/status
message per initiative.

Contract:
- `contract` — `{ "name": "agentrunner.initiative-status-message", "version": 1 }`
- `adapter` — normalized provider/adaptor id such as `discord`
- `target` — adapter-specific routing target metadata (for example channel/thread ids)
- `handle` — normalized returned message handle for later updates; the shared shape is intentionally compact:
  - `id` — provider message id / durable handle
  - `channelId` — provider channel/container id when applicable
  - `threadId` — provider thread id when applicable
  - `provider` — provider/adaptor id when returned by the adapter
  - `url` — optional message permalink
- `delivery` — lifecycle/persistence metadata:
  - `status` — `idle`, `active`, `finalized`, or `error`
  - `createdAt` / `updatedAt` / `finalizedAt`
  - `lastOperation` — `create`, `update`, or `finalize`
  - `lastError` — compact non-fatal adapter failure note when present
  - `providerMessageId` / `providerChannelId` / `providerThreadId`
  - `metadata` — adapter-specific delivery details that should survive later edits
- `lastEvent` — last normalized lifecycle event payload written through the shared contract
- `history[]` — short bounded audit trail of recent create/update/finalize attempts

Shared lifecycle payload contract:
- defined in `agentrunner/scripts/initiative_status.py`
- `operation` is one of `create`, `update`, `finalize`
- `lifecycleEvent` is one meaningful initiative boundary such as:
  - `initiative_activated`
  - `initiative_phase_changed`
  - `subtask_started`
  - `review_approved` / `review_blocked`
  - `remediation_queued`
  - `merge_blocked` / `merge_completed`
  - `initiative_completed` / `initiative_blocked` / `initiative_failed`
- the payload also carries a compact initiative summary, queue-item summary, optional result summary, and a short human-readable `summary`

Adapter semantics:
- `create` should emit the first status message and return the normalized handle persisted under `statusMessage.handle`
- `update` should reuse that persisted handle and mutate the existing message rather than posting a sibling message
- `finalize` should write the terminal initiative state, preserve the final handle/delivery metadata, and mark `delivery.finalizedAt`
- adapter failures must be non-fatal to initiative execution; record them in `delivery.lastError` / history instead of corrupting mechanics state

For a narrative description of the lifecycle boundaries, v1 Discord routing/config shape, and the smoke harness that exercises create/update/finalize plus failure-tolerant delivery, see `agentrunner/docs/INITIATIVE_STATUS_MESSAGES.md`.

Queue events are the source of truth; `queue.json` is a convenience view.
`operator_status.json` is also derivative: it is a blessed summary artifact for operator surfaces, not an authority for scheduling, enqueueing, or completion.

For a quick read-only operator snapshot across these files, use:
`python3 -m agentrunner status --project <project>`
(or the underlying implementation entrypoint `python3 agentrunner/scripts/operator_cli.py status --project <project>`)
This is the canonical operator CLI entrypoint. It should summarize active/idle state, a short queue view, the active initiative phase, the last completed item, and warning/result hints by consuming `operator_status.json` first.

Relationship between the operator helpers:
- `operator_cli.py` = default operator surface for readable present-tense status/queue/initiative views, now consuming named snapshot accessors from `operator_data.py` rather than peeking through the raw artifact dict ad hoc
- `operator_api.py` = tiny stdlib read-only HTTP adapter for downstream local tools that want JSON instead of terminal formatting
- `operator_tui.py` = optional local read-only terminal surface that keeps re-rendering the same canonical snapshot/read model; it is visibility-only and adds no write/control authority
- `operator_status.json` = blessed derivative artifact consumed by operator surfaces first
- `status.py` = explicit rebuild/debug helper for refreshing the artifact from mechanics truth when an operator asks for it
- `tick_tailer.py` = recent-history companion for validated tick activity, not the default current-status path

`status.py` remains the explicit manual rebuild/debug helper around the canonical artifact builder, rather than the default operator entrypoint.

## Canonical operator status artifact

Shared code contract:
- `agentrunner/scripts/operator_data.py` is the shared stdlib-only module that names the operator snapshot contract and centralizes read-only loading / bounded rebuild policy.
- The shared layer is regression-tested for three operator-critical behaviors: canonical-artifact reads, explicit missing/malformed rebuild fallback, and the minimum named accessor fields downstream adapters rely on.

Canonical location:
- `/home/openclaw/.agentrunner/projects/<project>/operator_status.json`
- equivalently: `~/.agentrunner/projects/<project>/operator_status.json`

Purpose:
- provide one blessed machine-readable summary for operator-facing adapters
- keep dashboards/CLIs/chat surfaces from reconstructing state by hand
- remain strictly derivative of mechanics-owned runtime truth

Minimum contract fields:
- `contract` — names the per-project snapshot contract (`agentrunner.operator-status-snapshot`) and version
- `project` — project id
- `status` — stable reconciled operator decision (`active`, `blocked`, `idle-clean`, `idle-pending`, or `conflicted`)
- `current` — active work summary or `null`
- `queue` — queue summary including at least `depth` and `nextIds`
- `initiative` — initiative id + current phase summary when known
- `closure` — bounded closure/handoff projection derived from the initiative phase plus operator status; this is the source of truth for closure semantics
- `lastCompleted` — most recent completed/blocked item summary when known
- `warnings` — zero or more structured warning objects
- `reconciliation` — explicit source/reason/preference breakdown for how the decision was derived; this is part of the required minimum contract, not an optional extension
- `updatedAt` — ISO-8601 timestamp for when the summary was refreshed

## Closure state taxonomy and handoff contract

Source of truth:
- `operator_status.json.closure` is the canonical operator-facing closure-semantics contract.
- It is derivative/read-only, built from mechanics truth (`state.json`, `queue.json`, ticks/results) plus initiative-local phase state.
- `status` remains the broad runtime reconciliation decision; `closure.state` is the bounded initiative/handoff projection.

Bounded closure states:
- `execution-active` — design/execution work is still in progress, or runtime work remains before closure is settled
- `closure-active` — execution is done enough that the initiative is in a closure lane, but closure is still actively being resolved
- `blocked` — operator-visible state is blocked/conflicted and the initiative is not safe to hand off
- `idle-clean` — runtime is quiet and no non-terminal initiative closure work remains

Phase → closure-state projection:
- `review-manager` → `closure-active`
- `replan-architect` → `closure-active`
- `closure-merger` → `closure-active`
- closure-follow-up execution work such as merger passback remediation / proof-hardening also projects to `closure-active` even though the initiative phase may temporarily be `execution`
- terminal success (`completed` / `closed`) may project to `idle-clean` once runtime is also quiet and unblocked

Handoff safety contract:
- `closure.quiet=true` means there is no active run and no queued backlog right now
- `closure.handoffSafe=true` is stricter: it requires `closure.state=idle-clean`, `closure.quiet=true`, and no non-terminal initiative phase still demanding closure work
- therefore **“no active queue item” is not the same as “safe to hand off / enqueue the next initiative”**
- example: a project may be quiet while the active initiative is still in `review-manager`; that is `closure-active`, not handoff-safe
- the taxonomy stays hierarchical on purpose: detailed initiative phase remains under `initiative.phase`, while operator surfaces that only need the safe bounded vocabulary should read `closure.state`

Proof-check bootstrap for reviewers in a clean checkout:
- run `./scripts/bootstrap_pytest.sh`
- then run `.venv/bin/pytest -q`
- `pyproject.toml` exposes a `dev` extra so the bootstrap installs the documented pytest dependency instead of relying on ambient global packages

Recommended `current` fields:
- `queueItemId`
- `role`
- `branch`
- `startedAt`
- `ageSeconds`

Recommended `queue` fields:
- `depth`
- `nextIds`

Recommended `initiative` fields:
- `initiativeId`
- `phase`
- `currentSubtaskId`
- `statusMessage` — compact initiative-local delivery summary when status-message persistence exists

Recommended `lastCompleted` fields:
- `queueItemId`
- `role`
- `status`
- `summary`
- `endedAt`

### Warning / stale semantics

`warnings` is the canonical place for operator-facing degradation notes.
Each warning should be a compact object so future adapters can render it without parsing prose. Recommended fields:
- `code` — stable machine-readable identifier such as `stale_run`, `malformed_ticks`, or `missing_queue`
- `severity` — `info`, `warning`, or `error`
- `summary` — short human-readable explanation
- `details` — optional extra context

A stale active run should appear as a warning with `code: "stale_run"` once the active item exceeds the mechanics stale-run timeout. This warning is derivative of runtime timestamps; it does not itself unlock or mutate the queue.

Status semantics:
- `conflicted` — higher-precedence truth sources disagree or mechanics state is internally inconsistent (for example `running=true` without `current`, or the active item also appears in the queued backlog)
- `blocked` — the latest operator-visible state indicates a blocking condition (for example the current run is stale or the latest completed item ended blocked)
- `active` — runtime lock + active run details agree on a fresh in-flight item
- `idle-pending` — nothing is actively running, but queued work remains **or** quiet/non-terminal closure follow-up still makes handoff unsafe
- `idle-clean` — nothing is actively running and there is no queued work, closure follow-up, or blocking context visible

`reconciliation` is the explicit policy payload behind `status`. It enumerates the candidate truth sources, their precedence/freshness metadata, and the ordered machine-readable reasons for the final decision.

Current precedence order:
1. integrity conflicts between mechanics sources
2. stale active-runtime claims
3. fresh live repo/git truth that proves the repo is currently clean/aligned and should outrank a stale blocked tail artifact
4. last completed blocked result
5. fresh active-runtime claim
6. queued backlog without active work
7. quiet closure follow-up without a live queued item yet
8. idle-clean fallback

Operator-facing formatting contract:
- `reconciliation:` should show the final decision plus the winning source/rule/precedence (`winner=source=..., rule=..., p...`)
- `operator hierarchy:` should show the policy name/version plus the explicit precedence order
- this is how an operator can tell which source won, why a stale blocked artifact was demoted, and which conditions still keep a blocked result authoritative

The clean-tail override is intentionally narrow. A stale blocked completion artifact is only demoted when live repo truth is present/fresh, has a visible HEAD, is clean, and proves the repo is aligned with the expected branch policy (`branchMatchesExpected` or a clean fast-forwarded base where `branchIsBase` and `expectedBranchIsAncestorOfBase` are both true). If those conditions are not met, the blocked artifact still wins.

The reconciliation `sources` payload now explicitly includes `live_repo` alongside `runtime_state`, `live_runtime`, `queue`, `initiative`, `recent_ticks`, and `result_artifacts`. `live_repo` is a read-only git/worktree inspection with freshness/authority metadata such as repo path, inspection timestamp, current branch/HEAD, branch-alignment checks, and worktree cleanliness. This lets operator surfaces explain why current repo reality may outrank older blocked artifacts without mutating mechanics state.

Consumers should treat `operator_status.json` as the canonical operator-facing summary and treat raw files as mechanics truth for debugging, recovery, and rebuilds.

For an optional downstream MQTT broadcast of this same operator snapshot, see `agentrunner/docs/OPERATOR_MQTT_BROADCAST.md`.
That contract is disabled by default and explicitly preserves `operator_status.json` as the authority, with MQTT acting only as a read-only broadcast adapter.

## Optional local operator API contract

The optional HTTP API exists to serve the canonical operator snapshot to colocated machine-facing consumers without asking them to parse terminal output.

Intended role:
- read-only adapter over `operator_status.json`
- convenience layer for local dashboards, scripts, TUIs, browser UIs, or other automation on the same host
- not an authority for queue mutation, dispatch, completion, or artifact rebuilding

## Optional local operator web UI contract

The browser-facing operator surface is intentionally bounded.

Chosen attach path:
- launch the existing local API entrypoint with `python3 -m agentrunner api --host 127.0.0.1 --port 8765`
- attach a browser UI to `GET /v1/operator/snapshot?project=<project>` rather than introducing a separate `python3 -m agentrunner web` runtime for the first slice

Boundaries:
- optional and localhost-oriented by default
- read-only over the canonical operator snapshot/read model
- downstream of `operator_status.json` and `operator_data.py`, not a control plane
- must preserve the same required snapshot fields: `status`, `current`, `queue`, `initiative`, `lastCompleted`, `warnings`, `reconciliation`, `updatedAt`
- must not mutate queue/state/ticks/results or imply public hosting by default

See also: `agentrunner/docs/OPERATOR_WEB_UI.md`.

## Optional local operator TUI contract

The optional TUI exists for operators who want a richer local terminal view than the plain `status` / `queue` text without introducing a second authority or always-on dashboard process.

Canonical launch shape:
- `python3 -m agentrunner tui --project <project>`
- direct implementation path: `python3 -m agentrunner.scripts.operator_tui --project <project>` is acceptable for local debugging, but the top-level routed form is the canonical operator contract

Position in the operator stack:
- mechanics truth remains the runtime files under `~/.agentrunner/projects/<project>/`
- `operator_status.json` remains the blessed derivative snapshot
- `operator_data.py` remains the shared read model and accessor layer
- the TUI is one consumer of that shared contract, alongside the text CLI, localhost API, optional MQTT broadcast, and any future web/dashboard surface

Boundaries:
- local terminal only
- read-only over the canonical operator snapshot/read model (`operator_status.json` via `operator_data.py`)
- no queue/state mutation controls, approvals, retries, or enqueue affordances
- bounded runtime choice for this first slice: stdlib-only redraw loop rather than a heavyweight TUI framework/runtime commitment
- optional dependency posture: no extra TUI package is required; the intended baseline is stdlib-only Python. If interactive `curses` support is unavailable on a host, `--once` and `--text-watch` remain valid proof/debug fallbacks.
- not part of the mechanics critical path: dispatch, completion detection, and recovery must continue to work without the TUI installed or running

Expected visible sections for the first slice:
- project/status header
- current item summary
- queue depth/preview
- initiative summary
- warnings/result hints

Smoke/proof-friendly mode:
- `python3 -m agentrunner tui --project <project> --once`
- `python3 scripts/test_operator_tui.py` for fixture-driven render/launch proof coverage without live mechanics reads

The TUI should be treated as another adapter over the blessed snapshot contract, alongside the text CLI, local API, and optional MQTT broadcast. It must not bypass those contracts by performing raw mechanics-file archaeology on its own.

Usage expectations:
- prefer loopback binding (`--host 127.0.0.1`), which is also the default
- treat it as localhost-only unless an operator deliberately places a stronger authenticated transport in front of it
- keep human operator workflows on the CLI unless a consumer explicitly needs JSON over HTTP

Current endpoint contract:
- `GET /v1/operator/snapshot?project=<project>`
- `HEAD /v1/operator/snapshot?project=<project>`
- `POST|PUT|PATCH|DELETE` are rejected with `405 method_not_allowed`

Successful response shape (`200`):
- `project` — requested project id
- `artifactPath` — canonical `operator_status.json` path for that project
- `notes` — loader notes emitted while resolving the snapshot
- `snapshot` — the exact canonical operator-status artifact object

The nested `snapshot` payload should expose the same minimum contract fields documented above for `operator_status.json` (`status`, `current`, `queue`, `initiative`, `lastCompleted`, `warnings`, `reconciliation`, `updatedAt`).

Explicit error shapes:
- `400 missing_project` when no `project` query parameter is provided
- `400 invalid_project` when the project name is blank, repeated, or fails validation
- `404 snapshot_unavailable` when no canonical artifact is available for the requested project
- `404 not_found` for unknown paths
- `405 method_not_allowed` for write verbs against the read-only surface

## Queue mutations
Supported kinds:
- `ENQUEUE` / `INSERT_FRONT` (with `item`)
- `CANCEL` (with `id`)
- `DEQUEUE` (with `id`)
- `DONE` (with `id`, `status`)

`queue.json` is a materialized view rebuilt by `queue_ledger.py`.
Direct edits to `queue.json` are not authoritative and may be overwritten on the next ledger replay.

For initiative kickoff specifically, the supported operator path is `agentrunner brief` (delegating to `enqueue_initiative.py`), which:
- validates exactly one manager-brief source
- writes or consumes the canonical `initiatives/<initiativeId>/brief.json` artifact
- rejects duplicate initiative ids already present in queue, current state, or initiative-local artifacts
- appends the kickoff item through the queue-event ledger rather than mutating `queue.json` directly

Expected helper behavior:
- happy path: prints a summary with `status: "ok"`, the kickoff `queueItemId`, the canonical `managerBriefPath`, and optional reliability-poll details
- duplicate guardrails: prints `status: "noop"` when kickoff is already active/pending/existing, or fails preflight when `state.json` already points at a different active initiative

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
