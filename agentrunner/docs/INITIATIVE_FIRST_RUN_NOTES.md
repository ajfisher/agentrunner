# First Initiative-Bundle Run Notes

Initiative: `agentrunner-status-helper`

## Outcome
- End-to-end initiative run completed and merged.
- Final merge commit: `3558818` (feature branch fast-forwarded into `master`).

## What worked
- Manager brief artifact generation (`brief.json`)
- Architect plan artifact generation (`plan.json`) with bounded subtasks
- Coordinator transitions for:
  - Manager -> Architect
  - Architect -> first subtask
  - Reviewer-approved subtask -> next subtask / Manager closure review
  - Manager decision -> Merger / Architect-replan
- Merger closure path with explicit ff-only constraints

## Seams found during live run (and patched)
1. Missing completion context in `state.lastCompleted`
   - Coordinator needed `queueItem` and `resultPath` to advance deterministically.
   - Patch: persist `queueItem`, `resultPath`, `handoffPath` into `lastCompleted`.

2. Missing transition: Developer complete -> Reviewer for initiative subtasks
   - Subtask execution stalled after Developer completion.
   - Patch: coordinator now enqueues a reviewer item for the same `subtaskId`.

## Operational takeaway
- The phase model is viable in practice, but robust unattended operation needs periodic invoker polling (or equivalent scheduler) so stale runs are surfaced and progressed without manual nudges.

## Next
- Add reliability polling/heartbeat for active project state dirs.
- Run a second initiative bundle confidence test with minimal intervention.
