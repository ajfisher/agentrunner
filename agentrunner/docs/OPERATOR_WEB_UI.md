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

This keeps the launch path explicit and narrow:
- reuse the existing routed API entrypoint
- keep the HTTP surface loopback-bound by default
- avoid implying queue/state mutation capabilities
- avoid implying public hosting by default
- avoid creating a second mechanics/runtime authority just for a browser view

## Contract boundaries

The web UI must:
- read from the canonical operator snapshot contract
- remain localhost-oriented by default
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
