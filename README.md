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

## Layout
- `agentrunner/scripts/` – invoker + utilities
- `agentrunner/prompts/` – role prompt templates
- `agentrunner/schemas/` – JSON Schemas
- `agentrunner/docs/` – architecture + how-to

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
