# Operator MQTT broadcast contract (MVP)

This document defines the **smallest explicit contract** for an optional MQTT broadcast of operator-visible status.

Status of this surface:
- **optional**
- **disabled by default**
- **read-only**
- **downstream-only integration**

The MQTT adapter is intentionally not part of the mechanics authority. It exists to let local dashboards, wall displays, or other ambient subscribers consume the already-canonical operator snapshot.

## Non-goals / authority boundary

The MQTT path is **not**:
- a control plane
- a queue mutation path
- an alternate source of truth
- an approval or dispatch surface

Canonical authority remains:
- mechanics-owned runtime files under `~/.agentrunner/projects/<project>/`
- especially `operator_status.json` for operator-facing summarized state

The MQTT adapter must only **broadcast derived state outward** from that canonical operator snapshot.
Subscribers may cache or display the payload, but they must not treat MQTT as the system of record.

## Enable / disable contract

MVP configuration shape:

```json
{
  "operatorMqtt": {
    "enabled": false,
    "broker": {
      "host": "mqtt.example.internal",
      "port": 1883,
      "usernameEnv": "AGENTRUNNER_OPERATOR_MQTT_USERNAME",
      "passwordEnv": "AGENTRUNNER_OPERATOR_MQTT_PASSWORD"
    },
    "topicPrefix": "agentrunner/operator",
    "qos": 1,
    "retain": true
  }
}
```

Contract notes:
- `enabled` defaults to **`false`**. If omitted or false, no MQTT client is created and no publish attempts occur.
- `broker.host` and `broker.port` identify the downstream broker.
- `broker.usernameEnv` / `broker.passwordEnv` name environment variables used to resolve credentials at runtime. Secrets must not be hard-coded into repo config examples.
- `topicPrefix` defaults to `agentrunner/operator` when omitted.
- `qos` defaults to **`1`** for conservative at-least-once delivery in the MVP.
- `retain` defaults to **`true`** so newly connected dashboards receive the latest snapshot immediately.

MVP intentionally keeps the config small. Any future TLS, client-cert, multiple-topic, or per-project override support should extend this contract rather than replace it silently.

## Topic contract

For project `<project>`, the canonical snapshot topic is:

`<topicPrefix>/<project>/snapshot`

Example:

`agentrunner/operator/agentrunner/snapshot`

MVP topic rules:
- one retained snapshot topic per project
- payload is the latest operator-visible state for that project
- no command/request topics
- no control replies
- no inbound subscription behavior required for correctness

## Publish trigger policy

The MQTT adapter publishes only when the **canonical operator snapshot changes** in an operator-visible way.

MVP publish moments:
- after `operator_status.json` is refreshed and the resulting snapshot differs from the last successfully published snapshot
- after startup/reconnect, the adapter may republish the current snapshot to restore the retained broker state

This means the adapter tracks the canonical operator snapshot, not raw queue/tick file churn.
The publish trigger is therefore tied to the derived operator view operators care about, not every mechanics append event.

The adapter should **not** publish on a blind fixed interval in the MVP.
If the canonical snapshot did not change, the adapter should remain quiet.

## Delivery semantics (MVP)

Conservative MVP delivery semantics:
- **QoS 1** (`qos: 1`)
- **retained** (`retain: true`)
- publish is best-effort and downstream-only
- MQTT publish failure must **not** block mechanics progression or change queue/state authority

Interpretation:
- at-least-once is preferred over at-most-once for an operator status snapshot
- retained delivery is preferred so ambient displays can come online late and still show current state
- duplicate deliveries are acceptable; consumers should treat each payload as a full-state snapshot, not as a once-only event

If publishing fails:
- the canonical mechanics/artifact flow still wins
- local operator CLI/API behavior must remain correct without MQTT
- a later successful publish may replace stale retained state

## Payload envelope contract

The MQTT payload is a JSON object with a small envelope around the canonical snapshot:

```json
{
  "contract": {
    "name": "agentrunner.operator-mqtt-snapshot",
    "version": 1
  },
  "project": "agentrunner",
  "publishedAt": "2026-04-20T08:30:00+10:00",
  "source": {
    "kind": "operator_status.json",
    "path": "~/.agentrunner/projects/agentrunner/operator_status.json"
  },
  "snapshot": {
    "status": "idle-pending",
    "current": null,
    "queue": {"depth": 1, "nextIds": ["example-item"]},
    "initiative": {"initiativeId": "example-initiative", "phase": "developer"},
    "lastCompleted": null,
    "warnings": [],
    "reconciliation": {
      "decision": "idle-pending"
    },
    "updatedAt": "2026-04-20T08:29:58+10:00"
  }
}
```

Envelope rules:
- `contract.name` is `agentrunner.operator-mqtt-snapshot`
- `contract.version` is `1`
- `project` is the project id that owns the canonical snapshot
- `publishedAt` is the MQTT adapter publish timestamp
- `source` identifies the canonical derivative artifact being broadcast
- `snapshot` contains the canonical operator snapshot payload

Snapshot rules:
- `snapshot` should mirror the current `operator_status.json` contract rather than inventing a second status schema
- consumers should rely on the nested `snapshot` fields documented in `STATE_AND_QUEUE.md`
- additions should be backward-compatible; breaking schema changes require a contract version bump

## Operator-visible semantics

The operator MQTT payload is a **full-state snapshot**, not a command stream and not a delta log.
Consumers should render the newest retained message as the current project view.

Recommended consumer behavior:
- treat MQTT as a cache/feed for display integration
- tolerate duplicate publishes
- replace previous state wholesale when a newer snapshot arrives
- fall back to CLI/API/artifact inspection when troubleshooting authority questions

## Why this contract is intentionally narrow

This MVP keeps the adapter boring:
- disabled unless explicitly enabled
- downstream-only broadcast
- one project snapshot topic
- one canonical payload shape derived from `operator_status.json`
- conservative QoS/retain defaults suitable for operator dashboards

That gives later tests a clear contract to lock before code lands, without turning MQTT into a second operator brain or a write surface.
