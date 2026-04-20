# Demo Quickstart Walkthrough

This quickstart gives operators a short proof path for the current AgentRunner visibility surfaces, including the refreshed browser status presentation.

## Goal

Show the intended operator flow without introducing a second runtime authority:
- canonical status remains `operator_status.json`
- the local API exposes that snapshot read-only
- the browser view at `/operator?project=<project>` is a thin HTML layer over the same snapshot
- the browser page auto-refreshes locally by polling that same read-only snapshot endpoint

## Browser quickstart (intended attach path)

Start the local read-only API:

```bash
python3 -m agentrunner api --host 127.0.0.1 --port 8765
```

Open the browser UI for a project:

```text
http://127.0.0.1:8765/operator?project=<project>
```

What to verify:
- the page renders the same operator snapshot sections the other adapters use (`status`, `current`, `queue`, `initiative`, `lastCompleted`, `warnings`, `reconciliation`, `updatedAt`)
- the page makes the auto-refresh behavior visible rather than silently changing underneath the operator
- after one polling interval, the refresh-status line updates and the page continues to reflect the latest local snapshot
- the page remains read-only; there are no enqueue/retry/approve/write controls

## JSON cross-check

Confirm the browser is attached to the same canonical snapshot contract:

```bash
curl 'http://127.0.0.1:8765/v1/operator/snapshot?project=<project>'
```

Expected shape:
- top-level envelope with `project`, `artifactPath`, `notes`, and `snapshot`
- nested `snapshot` with the shared required operator fields

## Fixture / no-server smoke path

For layout/presentation checks without a running API server or live mechanics files:

```bash
python3 agentrunner/scripts/operator_web.py --smoke-sample > /tmp/operator.html
xdg-open /tmp/operator.html
```

If `xdg-open` is unavailable on the host, open `/tmp/operator.html` manually in a browser.

This proof path is useful when you want to validate the refreshed status presentation in isolation from live queue/mechanics state.

## Why this is the intended model

The browser surface is intentionally conservative:
- local-first
- read-only
- polling the canonical snapshot instead of maintaining its own authority
- easy to remove or ignore without affecting mechanics

If a future remote dashboard is needed, put an authenticated transport/proxy in front of the local API instead of widening the raw browser/API surface into a public control plane.
