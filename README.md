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
