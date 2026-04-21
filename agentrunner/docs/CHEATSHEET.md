# AgentRunner Operator CLI Cheat Sheet

## Canonical MVP command map

Preferred operator path:

```bash
cd /home/openclaw/projects/agentrunner
python3 -m agentrunner <command> [...args]
```

Implemented routed commands today:
- `python3 -m agentrunner brief`
- `python3 -m agentrunner status`
- `python3 -m agentrunner queue`
- `python3 -m agentrunner initiatives`
- `python3 -m agentrunner watch`

Compatibility note:
- the old script entrypoints still work and remain the implementation surface underneath the router
- a bare `agentrunner ...` console-script shim may be available in some packaged installs later, but checkout-based/operator docs should assume `python3 -m agentrunner ...` unless explicitly packaged

Delegation contract:
- `brief` is a thin adapter over `agentrunner/scripts/enqueue_initiative.py`
- `status`, `queue`, `initiatives`, and `watch` are thin adapters over `agentrunner/scripts/operator_cli.py`
- arguments after the top-level command are passed through unchanged
- if you prefer a visual separator, `python3 -m agentrunner <command> -- ...` is accepted; the router strips the lone separator before delegation
- exit codes come from the underlying script, not a rewritten router policy

## Base command

```bash
cd /home/openclaw/projects/agentrunner
python3 -m agentrunner status
```

Use it in one of two ways:
- by **project name**
- by explicit **state dir**

---

## Quick current-state view

### Status by project

Preferred:

```bash
python3 -m agentrunner status --project agentrunner
```

Compatibility / direct script form:

```bash
python3 agentrunner/scripts/operator_cli.py status --project agentrunner
```

### Status by explicit state dir

Preferred:

```bash
python3 -m agentrunner status --state-dir /home/openclaw/.agentrunner/projects/agentrunner
```

Compatibility / direct script form:

```bash
python3 agentrunner/scripts/operator_cli.py status --state-dir /home/openclaw/.agentrunner/projects/agentrunner
```

Use this for:
- is it idle / active / blocked?
- what just completed?
- what initiative is active?
- are there warnings?

---

## Queue view

Preferred:

```bash
python3 -m agentrunner queue --project agentrunner
```

Compatibility / direct script form:

```bash
python3 agentrunner/scripts/operator_cli.py queue --project agentrunner
```

or by explicit state dir:

```bash
python3 -m agentrunner queue --state-dir /home/openclaw/.agentrunner/projects/agentrunner
python3 agentrunner/scripts/operator_cli.py queue --state-dir /home/openclaw/.agentrunner/projects/agentrunner
```

Use this for:
- what is queued next?
- how many items are waiting?
- what roles are coming up?

---

## Initiative view

Preferred:

```bash
python3 -m agentrunner initiatives --project agentrunner
```

Compatibility / direct script form:

```bash
python3 agentrunner/scripts/operator_cli.py initiatives --project agentrunner
```

Use this for:
- which initiative is/was active?
- what phase is it in?
- branch / base context

---

## Watch mode

### Continuous-ish watch

Preferred:

```bash
python3 -m agentrunner watch --project agentrunner
```

Compatibility / direct script form:

```bash
python3 agentrunner/scripts/operator_cli.py watch --project agentrunner
```

### Bounded watch

Preferred:

```bash
python3 -m agentrunner watch --project agentrunner --count 5 --interval 1
```

Compatibility / direct script form:

```bash
python3 agentrunner/scripts/operator_cli.py watch --project agentrunner --count 5 --interval 1
```

Use this for:
- seeing progression over time
- checking whether the poller is moving things
- light live monitoring without tailing raw files

Handy direct-script variant:

```bash
python3 agentrunner/scripts/operator_cli.py watch --project agentrunner --count 10 --interval 2
```

---

## Initiative status message smoke check

```bash
python3 scripts/smoke_initiative_status_messages.py
```

Use this when you want a tiny fixture-driven proof that the initiative status-message adapter still:
- creates the first message
- updates the same message in place
- finalizes the same handle
- tolerates delivery failure without losing the persisted handle

See also:
- `agentrunner/docs/INITIATIVE_STATUS_MESSAGES.md`
- `scripts/test_initiative_status_discord_adapter.py`
- `scripts/test_initiative_status_lifecycle_wiring.py`

## Related tools

### Recent event history (`tick_tailer.py`)

If you want the timeline rather than the current state:

```bash
python3 agentrunner/scripts/tick_tailer.py --project agentrunner -n 10
```

Follow new events:

```bash
python3 agentrunner/scripts/tick_tailer.py --project agentrunner -n 5 --follow
```

Use this for:
- what just happened?
- did reviewer block something?
- did merger fire?
- was a dev follow-up inserted?

Important distinction:
- `python3 -m agentrunner status|queue|initiatives|watch` = top-level operator views
- `tick_tailer.py` = validated recent-history helper
- `tick_tailer.py` does **not** replace the current-state artifact/views

---

### Status rebuild/debug helper (`status.py`)

```bash
python3 agentrunner/scripts/status.py --state-dir /home/openclaw/.agentrunner/projects/agentrunner
```

Use this when you explicitly want the lower-level rebuild/debug path sitting under the canonical status artifact.
It is **not** the preferred day-to-day operator command.

---

### Enqueue a new initiative

Preferred:

```bash
python3 -m agentrunner brief \
  --project agentrunner \
  --initiative-id my-new-thing \
  --branch feature/agentrunner/my-new-thing \
  --base main \
  --manager-brief-path /path/to/brief.json \
  --poll-after-enqueue
```

Compatibility / lower-level equivalent:

```bash
python3 agentrunner/scripts/enqueue_initiative.py \
  --project agentrunner \
  --initiative-id my-new-thing \
  --branch feature/agentrunner/my-new-thing \
  --base main \
  --manager-brief-path /path/to/brief.json \
  --poll-after-enqueue
```

Use this for:
- starting new autonomous work the right way
- avoiding fake `queue.json` hacks

---

## Mental model

Use:
- `python3 -m agentrunner status` → current state
- `python3 -m agentrunner queue` → upcoming work
- `python3 -m agentrunner initiatives` → phase/initiative context
- `python3 -m agentrunner watch` → repeated snapshots
- `python3 agentrunner/scripts/status.py` → rebuild/debug helper
- `python3 agentrunner/scripts/tick_tailer.py` → recent history / event stream

So:
- **top-level routed CLI = normal operator path**
- **status.py = rebuild/debug helper**
- **tick tailer = recent past**

---

## Current limitation

The routed command tree exists today at the Python-module level:

```bash
python3 -m agentrunner status
```

Do not assume a bare `agentrunner` console script exists unless the environment explicitly installed one.
If/when that shim is packaged everywhere, it should match the same routing contract documented here.
