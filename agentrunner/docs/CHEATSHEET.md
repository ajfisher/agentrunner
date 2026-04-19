# AgentRunner Operator CLI Cheat Sheet

## Base command

```bash
cd /home/openclaw/projects/agentrunner
python3 agentrunner/scripts/operator_cli.py
```

Use it in one of two ways:
- by **project name**
- by explicit **state dir**

---

## Quick current-state view

### Status by project

```bash
python3 agentrunner/scripts/operator_cli.py status --project agentrunner
```

### Status by explicit state dir

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

```bash
python3 agentrunner/scripts/operator_cli.py queue --project agentrunner
```

or

```bash
python3 agentrunner/scripts/operator_cli.py queue --state-dir /home/openclaw/.agentrunner/projects/agentrunner
```

Use this for:
- what is queued next?
- how many items are waiting?
- what roles are coming up?

---

## Initiative view

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

```bash
python3 agentrunner/scripts/operator_cli.py watch --project agentrunner
```

### Bounded watch

```bash
python3 agentrunner/scripts/operator_cli.py watch --project agentrunner --count 5 --interval 1
```

Use this for:
- seeing progression over time
- checking whether the poller is moving things
- light live monitoring without tailing raw files

Handy version:

```bash
python3 agentrunner/scripts/operator_cli.py watch --project agentrunner --count 10 --interval 2
```

---

## Related tools

### Recent event history

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

---

### Status helper

```bash
python3 agentrunner/scripts/status.py --state-dir /home/openclaw/.agentrunner/projects/agentrunner
```

This is the thinner status helper sitting over the canonical status artifact.

---

### Enqueue a new initiative

```bash
python3 agentrunner/scripts/enqueue_initiative.py \
  --project agentrunner \
  --initiative-id my-new-thing \
  --branch feature/agentrunner/my-new-thing \
  --base master \
  --manager-brief-path /path/to/brief.json \
  --poll-after-enqueue
```

Use this for:
- starting new autonomous work the right way
- avoiding fake `queue.json` hacks

---

## Mental model

Use:
- `operator_cli.py status` → current state
- `operator_cli.py queue` → upcoming work
- `operator_cli.py initiatives` → phase/initiative context
- `operator_cli.py watch` → repeated snapshots
- `tick_tailer.py` → recent history / event stream

So:
- **status = present**
- **tick tailer = recent past**

---

## Current limitation

This is not yet installed as a top-level command like:

```bash
agentrunner status
```

Right now the real entrypoint is still:

```bash
python3 agentrunner/scripts/operator_cli.py ...
```
