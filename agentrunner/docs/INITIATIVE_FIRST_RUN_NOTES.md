# First Initiative-Bundle Run Notes

> Historical proof note: this document records the first live initiative-bundle run before the repo standardized on `main` as the steady-state base branch. Keep the `master` wording here as evidence from that earlier run, not as current operator guidance.

Initiative: `agentrunner-status-helper`

## Outcome
- End-to-end initiative run completed and merged.
- Final merge commit: `3558818` (feature branch fast-forwarded into `master` during the earlier pre-migration run).

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

## Migration note for current operators
- This historical run merged into `master` because it predated the repo-wide base-branch normalization.
- Current operator docs/examples should use `main` for new initiative kickoff, status review, and merge-oriented workflow checks.
- For a bounded modern proof, use the scratch-state recipe in `README.md` / `agentrunner/docs/CHEATSHEET.md`; it exercises `brief`, `status`, `queue`, and `initiatives` end-to-end with `--base main`.
