# Single-Item Proof Run

This document captures the first narrow Phase 4 proof run used to validate the end-to-end single-item Developer mechanics path.

## Goal
Prove the following path in isolation:
- dispatch
- artifact emission
- artifact validation
- tick append
- queue unlock
- operator summary emission

without involving Reviewer/Developer chaining.

## Run details
- Project: `picv_spike`
- Queue item id: `picv-dev-proof-001`
- Role: `developer`
- Branch: `feature/picv_spike/replay-mode`
- Run id: `132bf812-cbcc-47cb-b911-377bc246d7ff`
- Session key: `hook:agentrunner:picv_spike:picv-dev-proof-001`
- Completion status: `ok`

## Task shape
A deliberately tiny docs-only change in `NOTES.md`:
- minimal risk
- committed on the target branch
- enough to exercise the full mechanics path without turning the task itself into the interesting variable

## Result artifact
Result path:
- `/home/openclaw/.agentrunner/projects/picv_spike/results/picv-dev-proof-001.json`

Observed result summary:
- "Minimal docs-only proof update in NOTES.md committed on feature/picv_spike/replay-mode; requested diff and check.sh passed."

Observed commit:
- `967909824f35caa906783a657fc30df920c0202e`

Observed checks:
- `git diff -- NOTES.md`
- `./check.sh`

## Queue/tick evidence
Observed queue events:
- `ENQUEUE` → `DEQUEUE` → `DONE`

Observed tick:
- appended with queue item id `picv-dev-proof-001`
- status `ok`
- validated result artifact embedded in the tick record

## Acceptance outcome
This run satisfied the narrow proof criteria:
- hook run started cleanly
- result artifact appeared
- result artifact passed mechanics validation
- `ticks.ndjson` updated correctly
- queue unlocked cleanly
- operator-facing summary path executed via normal mechanics flow

## Notes
This proof intentionally did **not** test Reviewer→Developer artifact consumption.
That belongs to the next chained proof stage.
