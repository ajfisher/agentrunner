# Initiative status message adapters

This note is the operator/developer map for the initiative-scoped status-message seam.
It explains what gets published, when it should publish, and how the first Discord adapter is wired in v1.

## Purpose

AgentRunner can keep one compact human-facing status message per initiative.
That message is an **adapter over mechanics truth**, not a second source of truth.

Authoritative state still lives in:
- `state.json`
- `queue.json`
- `queue_events.ndjson`
- `ticks.ndjson`
- result / handoff artifacts
- initiative-local `initiatives/<initiativeId>/state.json`

The status-message adapter exists to give operators one updatable message they can glance at without flooding Discord with a new post on every transition.

## Shared contract

Core lifecycle + persistence helpers live in:
- `agentrunner/scripts/initiative_status.py`
- `agentrunner/scripts/initiative_status_discord.py`

Persistence is initiative-local under:
- `initiatives/<initiativeId>/state.json`
- key: `statusMessage`

Shared operations:
- `create` — publish the first message and persist a durable handle
- `update` — edit the existing message in place
- `finalize` — write the terminal initiative state and mark delivery finalized

Normalized persisted fields:
- `adapter`
- `target`
- `handle`
- `delivery`
- `lastEvent`
- `history[]`

The persisted handle is intentionally compact:
- `id`
- `channelId`
- `threadId`
- `provider`
- optional `url`

## Lifecycle boundaries that should publish

Status-message updates should happen on **meaningful initiative boundaries**, not every low-level mechanics tick.

Current lifecycle events recognized by the shared contract:
- `initiative_activated`
- `initiative_phase_changed`
- `subtask_started`
- `review_approved`
- `review_blocked`
- `remediation_queued`
- `merge_blocked`
- `merge_completed`
- `initiative_completed`
- `initiative_blocked`
- `initiative_failed`

### Current publish guidance

| Lifecycle event | Typical operation | Why it matters |
| --- | --- | --- |
| `initiative_activated` | `create` | First visible handoff into active initiative execution |
| `initiative_phase_changed` | `update` | Reserved for explicit operator-visible phase shifts when the phase change itself matters |
| `subtask_started` | `update` | Shows which bounded unit is currently running |
| `review_approved` | `update` | Signals forward progress without posting a sibling message |
| `review_blocked` | `update` | Signals a blocker while the initiative is still live |
| `remediation_queued` | `update` | Shows that a repair loop has been scheduled |
| `merge_blocked` | `finalize` | Current terminal blocker for closure/merge in v1 |
| `merge_completed` | `finalize` | Initiative closed successfully through merge |
| `initiative_completed` | `finalize` | Terminal success even if there is no distinct merge event |
| `initiative_blocked` | `finalize` | Terminal blocked state needing operator attention |
| `initiative_failed` | `finalize` | Terminal error/failure state |

### Operation resolution rules

`resolve_status_message_operation()` follows a small deterministic policy:
- terminal lifecycle events resolve to `finalize` **when a persisted handle exists**
- terminal lifecycle events resolve to `create` if there is no prior handle yet
- non-terminal events resolve to `update` once a handle exists
- otherwise the first publish is `create`

That lets late-discovered terminal states still emit a single compact message instead of silently doing nothing.

## Discord adapter in v1

The first concrete adapter is Discord-backed and lives in:
- `agentrunner/scripts/initiative_status_discord.py`

### Transport seam

The adapter uses the existing OpenClaw `message` seam rather than a bespoke Discord client:
- `message.send` for `create`
- `message.edit` for `update`
- `message.edit` for `finalize`

So the adapter contract is:
1. render one compact human-readable message
2. send/edit it through the gateway tool seam
3. normalize the returned message handle
4. persist that handle in initiative-local state

### Target configuration

The coordinator reads compact routing metadata from:
- environment variable `AGENTRUNNER_INITIATIVE_STATUS_TARGET_JSON`
- or existing persisted `statusMessage.target`

Expected JSON shape:

```json
{
  "channel": "discord",
  "target": "channel:1477159463143084217",
  "threadId": "1477999999999999999",
  "title": "AgentRunner Initiative Status",
  "metadata": {
    "initiative": "agentrunner-status-message-adapters"
  }
}
```

Notes:
- `channel` defaults to `discord`
- `target` is the Discord routing target used by the OpenClaw `message` tool
- `threadId` is optional
- `title` is optional and defaults to `AgentRunner Initiative Status`
- `metadata` is adapter-specific durable routing context

### Message shape

The rendered Discord message intentionally stays compact and editable:
- initiative id
- lifecycle event
- current phase + subtask
- current queue item / role when useful
- result bits (`status`, `commit`, `approved`, `merged`) when present
- short summary
- blocked reason when relevant
- updated timestamp

## Failure-tolerant behavior

Delivery failure must **not** break initiative execution.

If Discord delivery fails:
- initiative work continues
- the last known handle is preserved when available
- `delivery.status` becomes `error`
- `delivery.lastError` records the compact failure note
- the attempt is appended to bounded `history[]`

This applies both to:
- thrown exceptions / transport errors
- structured failure payloads returned by the gateway seam

That behavior is deliberate: the chat surface is an operator convenience layer, not a mechanics dependency.

## Smoke harness

A small fixture-driven smoke harness lives at:
- `scripts/smoke_initiative_status_messages.py`

Run it from the repo root:

```bash
python3 scripts/smoke_initiative_status_messages.py
```

It exercises the v1 happy-path and failure-tolerant contract:
- create
- update
- finalize
- failed edit that preserves the prior handle and marks delivery `error`

## Related proof tests

The focused proof tests are:
- `scripts/test_initiative_status_discord_adapter.py`
- `scripts/test_initiative_status_lifecycle_wiring.py`

Those cover:
- target normalization
- gateway handle normalization
- single-message create/update/finalize flow
- lifecycle wiring from coordinator/invoker boundaries
- exception and structured failure persistence
