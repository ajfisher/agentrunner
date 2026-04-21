# Optional local operator web UI contract

This document defines the **bounded browser-facing surface** for AgentRunner operator visibility.

## Status

The operator web UI is **optional**, **read-only**, and **local-first**.
It is not required for dispatch, completion, queue advancement, or recovery.

Mechanics-owned truth remains:
- `state.json`
- `queue.json`
- `queue_events.ndjson`
- `ticks.ndjson`
- result/handoff artifacts

The canonical operator-facing derivative remains:
- `operator_status.json`

The web UI is therefore **downstream of the canonical operator snapshot contract**, not a control plane.

## Chosen launch / attach path

For the first bounded web slice, AgentRunner does **not** introduce a separate `python3 -m agentrunner web` server/runtime.

Instead, the browser-facing path attaches to the **existing local read-only API entrypoint**:

```bash
python3 -m agentrunner api --host 127.0.0.1 --port 8765
```

Then a browser-based UI may consume:

- `GET /v1/operator/snapshot?project=<project>`
- `HEAD /v1/operator/snapshot?project=<project>`
- `GET /operator?project=<project>` as the thin HTML renderer over that same local snapshot contract

Today that HTML surface is intentionally simple:
- loopback-bound by default because it rides on the same local API server
- auto-refreshing in-browser on a short timer (currently 5s) by polling the canonical snapshot endpoint again
- explicitly read-only, with no control or mutation affordances added in the page layer
- organized as a single-page watch surface so an operator can read now / next up / recent completion without tabbing across separate browser views

This keeps the launch path explicit and narrow:
- reuse the existing routed API entrypoint
- keep the HTTP surface loopback-bound by default
- make the browser refresh model obvious: local polling against the canonical snapshot, not websocket state or a second runtime
- avoid implying queue/state mutation capabilities
- avoid implying public hosting by default
- avoid creating a second mechanics/runtime authority just for a browser view

## Contract boundaries

The web UI must:
- read from the canonical operator snapshot contract
- remain localhost-oriented by default
- use a local read-only polling model for refreshes rather than inventing a second push/runtime authority
- remain safe to ignore/remove without affecting mechanics
- preserve the same named snapshot fields other operator adapters use

The web UI must **not**:
- mutate queue/state/ticks/results
- enqueue work
- approve/reject/retry items
- become the source of truth for operator status
- assume internet/public exposure by default

If remote access is wanted later, place an explicit authenticated transport or proxy in front of the local API rather than broadening the raw API/UI into a public service by default.

## Required snapshot fields

Any browser-facing UI should treat the nested snapshot payload as the contract and rely on these required fields:
- `status`
- `current`
- `queue`
- `initiative`
- `lastCompleted`
- `warnings`
- `reconciliation`
- `updatedAt`

Those fields are shared with the text CLI, local API, local TUI, and optional MQTT adapter so all operator surfaces stay aligned.

## Intended watch-surface cues

The browser page should read like a grouped watch surface rather than a pile of raw fields.
A good operator scan order is:
- **now** — current status + current item summary
- **next up** — queue depth and next queued ids/items
- **recent completion** — the last completed queue item and summary
- **operator cues** — warnings, reconciliation, and freshness / closure hints

Three cues matter enough to make explicit in the browser copy and layout:
- **waiting** means the system is not actively executing a queue item right this second, but the operator should still read queue, recent completion, and closure context before assuming the run is done.
- **blocked** means the visible state is conflicted or otherwise needs intervention; this should read as an operator-visible problem state, not a harmless quiet gap.
- **handoff-safe** means the surface can be safely treated as truly idle/settled for handoff purposes; absence of handoff-safe means a quiet surface may still be mid-closure or awaiting the next bounded follow-on.

The point of these cues is to stop the common false read of "looks quiet, must be finished".
A watch surface should help the operator distinguish quiet-but-waiting, genuinely blocked, and truly handoff-safe idle.

## Where the web UI sits in the operator stack

Keep future UI work aligned to this adapter order:

1. **CLI** (`python3 -m agentrunner status|queue|initiatives|watch`)  
   canonical human/operator entrypoint for read-only status views
2. **Localhost API** (`python3 -m agentrunner api --host 127.0.0.1 --port 8765`)  
   tiny machine-facing JSON/HTML adapter over the canonical snapshot contract
3. **Web UI** (`GET /operator?project=<project>`)  
   optional browser renderer attached to that existing localhost API path
4. **TUI** (`python3 -m agentrunner tui --project <project>`)  
   optional local terminal adapter over the same read model
5. **MQTT broadcast** (documented separately, disabled by default)  
   optional downstream publish path for the same canonical operator snapshot

Important consequence:
- the web UI is **not** parallel authority with the CLI/API/TUI/MQTT surfaces
- it is one more adapter over the same `operator_status.json` → `operator_data.py` contract
- if the CLI, API, TUI, MQTT, and browser view disagree, fix the shared snapshot/read-model contract rather than teaching the web UI its own runtime truth

## Recommended shape for the first browser surface

A minimal browser UI is expected to be a thin renderer over the existing local API response, for example:
- project / status header
- current item summary
- queue depth + next items
- initiative summary
- last completed item
- warnings
- reconciliation summary
- updated timestamp

That is intentionally a visibility surface, not an action surface.

## Local refresh / smoke expectations

The intended first-run/operator proof is deliberately small and local:

1. Start the loopback-only API surface:
   - `python3 -m agentrunner api --host 127.0.0.1 --port 8765`
2. Open the browser page:
   - `http://127.0.0.1:8765/operator?project=<project>`
3. Confirm the page clearly presents current status, queue, initiative, warnings, reconciliation, and update recency.
4. Wait one polling interval and confirm the refresh banner/status text updates, proving the browser view is auto-refreshing against the same canonical snapshot contract.
5. Optionally cross-check the raw JSON contract:
   - `curl 'http://127.0.0.1:8765/v1/operator/snapshot?project=<project>'`

That smoke path is intentionally local-first and read-only:
- no browser-side write actions are expected or required
- no live mechanics mutation is needed to validate the presentation/refresh loop
- the browser proof is successful if the HTML surface refreshes itself from the canonical snapshot and continues to mirror the same named fields as the JSON endpoint

For fixture-only proofs without a running API server, render static HTML and inspect the resulting file:
- `python3 agentrunner/scripts/operator_web.py --smoke-sample > /tmp/operator.html`
- open `/tmp/operator.html` locally to validate the refreshed status presentation layout in isolation
