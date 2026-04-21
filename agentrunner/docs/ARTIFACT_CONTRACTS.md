# Artifact Contracts

This document defines the mechanics-facing artifact contracts used by `agentrunner`.

These artifacts are the deterministic boundary between:
- the **cognition layer** (agent turns)
- the **mechanics layer** (`invoker.py`, queue/tick bookkeeping)

File presence alone is **not** considered success.
An artifact must both:
1. exist
2. match the expected contract shape

## Canonical helper interface
Workers should write artifacts via:
- `agentrunner/scripts/emit_result.py`
- `agentrunner/scripts/emit_handoff.py`

There is no legacy `write_*` helper contract.

## Result artifact contract
A result artifact is written to the `RESULT_PATH` supplied by mechanics.

### Common required fields
All result artifacts must include:
- `status` — string
- `role` — string, one of:
  - `developer`
  - `reviewer`
  - `manager`
  - `merger`
  - `architect`
- `summary` — non-empty string
- `checks` — list
- `writtenAt` — ISO-8601 timestamp string

### Accepted statuses
Current accepted values:
- `ok`
- `blocked`
- `error`
- `completed`

### `checks` shape
`checks` must be a list of objects.
Each check object must contain:
- `name` — non-empty string
- `status` — non-empty string

Other check fields may be present, but mechanics currently only requires the above.

## Developer result contract
Developer result artifacts must include everything in the common contract, plus:
- `commit` — required key
  - may be a string SHA/ref
  - may be `null` when explicitly no commit was made

Optional but supported:
- `requestExtraDevTurn` — boolean
- `requestReason` — string/null
- `operatorSummary` — string
- `findings` — list (usually empty for Developer)

### Minimal valid example
```json
{
  "status": "ok",
  "role": "developer",
  "summary": "Updated docs and reran checks.",
  "commit": "abc1234",
  "checks": [
    {"name": "./check.sh", "status": "ok"}
  ],
  "writtenAt": "2026-04-01T15:00:00+11:00"
}
```

## Reviewer result contract
Reviewer result artifacts must include everything in the common contract, plus:
- `approved` — boolean
- `findings` — list
  - may be empty when approved / no findings
  - when present, items should be objects

Optional but supported:
- `requestExtraDevTurn` — boolean
- `requestReason` — string/null
- `operatorSummary` — string

### Finding shape
Mechanics currently requires each finding to be an object.
Recommended fields include:
- `id`
- `title`
- `detail` or `body`
- `acceptance` or `acceptanceCriteria`
- `severity`

Important:
- `findings` must be a **flat list of objects**
- not `[[]]`
- not `[{"findings": [...]}]`
- when using `emit_result.py`, pass one `--finding-json` flag per finding object

`emit_result.py` now defensively flattens accidental nested finding arrays / single-key `{ "findings": [...] }` wrappers, but prompts and workers should still emit the flat shape directly.

### Minimal valid example
```json
{
  "status": "blocked",
  "role": "reviewer",
  "summary": "One follow-up fix is still needed.",
  "approved": false,
  "checks": [],
  "findings": [
    {
      "title": "README lacks replay usage",
      "detail": "The new CLI path is not documented.",
      "acceptance": "Add a replay example and dependency note."
    }
  ],
  "writtenAt": "2026-04-01T15:00:00+11:00"
}
```

## Merger result contract
Merger result artifacts must include everything in the common contract, plus:
- `merged` — boolean
- `commit` — required key
  - should be the new target-branch HEAD on successful merge
  - may be `null` if merge did not happen

Recommended checks include:
- branch diff/stat check
- repo cleanliness / branch-state check
- read-only mergeability evidence (for example `git merge-base --is-ancestor <base> <branch>`)
- actual merge command outcome (for example `git merge --ff-only ...`) only after approval/readiness is already established

Important:
- approval evidence should be explicit in queue/context where possible (for example `constraints.approvedByReviewer=true` plus an approval source reference)
- treat `git merge --ff-only ...` as the actual side-effecting merge action, not as a harmless preflight check
- if `merged` is `false`, repo state should remain unchanged

### Blocked merger closure-blocker contract
When a Merger result is `status=blocked` and `merged=false`, it should classify the closure blocker explicitly via `mergeBlocker`.

Required fields:
- `mergeBlocker.classification` — `repairable` or `terminal`
- `mergeBlocker.kind` — stable machine-readable blocker kind

Optional but recommended fields:
- `mergeBlocker.detail` — concise human-readable explanation
- `mergeBlocker.passback` — required for repairable blockers in MVP
- `mergeBlocker.stopConditions` — required for ambiguous terminal blockers in MVP

#### MVP repairable blocker kinds
Only the following repairable blocker class is in-scope for MVP passback:
- `non_fast_forward` — the source branch is no longer fast-forward mergeable onto the target and needs a Developer passback/rebase before re-review + merge retry

For `classification=repairable`, emit:
- `mergeBlocker.passback.targetRole` — usually `developer`
- `mergeBlocker.passback.action` — recommended next action such as `rebase`
- `mergeBlocker.passback.reason` — concise reason for the passback
- `mergeBlocker.passback.requiresReReview` — boolean
- `mergeBlocker.passback.requiresMergeRetry` — boolean

#### MVP terminal blocker kinds
Common terminal blocker kinds include:
- `approval_missing`
- `ambiguous_readiness`
- `unexpected_git_state`
- `unsupported_merge_policy`

Terminal means the Merger should stop rather than invent a repair path.
For `kind=ambiguous_readiness`, emit `mergeBlocker.stopConditions` with concise operator-visible conditions explaining what must be clarified before another merge attempt.

### Minimal valid example
```json
{
  "status": "ok",
  "role": "merger",
  "summary": "Fast-forward merged feature/picv_spike/replay-mode into main.",
  "merged": true,
  "commit": "deadbeef1234",
  "checks": [
    {"name": "git diff --stat main...feature/picv_spike/replay-mode", "status": "ok"},
    {"name": "git merge --ff-only feature/picv_spike/replay-mode", "status": "ok"}
  ],
  "writtenAt": "2026-04-04T14:45:00+11:00"
}
```

If merge is blocked, emit a normal blocked result artifact rather than failing silently.

For ff-only blocks caused by divergence / non-fast-forward state, operator-facing summaries should include a concise recovery hint that the branch likely needs a Developer passback/rebase step before re-review + merge retry.

## Handoff artifact contract
A handoff artifact is written to `HANDOFF_PATH` when a Reviewer requests follow-up Developer work.

Canonical branch contract: use `main` as the steady-state `base` branch in new artifacts and examples. Any surviving `master` strings should only appear inside intentionally preserved historical proof notes.

## Review findings artifact
When mechanics inserts a follow-up Developer item, it may also materialize a stable review-findings artifact under the project state directory, e.g.:
- `/home/openclaw/.agentrunner/projects/<project>/review_findings/<queueItemId>.json`

This file is not the primary completion contract, but it is a deterministic convenience artifact for follow-up Developer turns.

Typical fields:
- `sourceQueueItemId`
- `sourceResultPath`
- `sourceHandoffPath`
- `requestReason`
- `findings`
- `writtenAt`

If present, Developer turns should prefer this structured artifact over prose/history when interpreting Reviewer intent.

### Required fields
A handoff artifact must include:
- `sourceQueueItemId` — non-empty string
- `sourceRole` — non-empty string
- `targetRole` — non-empty string
- `project` — non-empty string
- `goal` — non-empty string
- `checks` — list
- `findings` — list
- `contextFiles` — list
- `writtenAt` — ISO-8601 timestamp string

### Optional fields
- `repoPath`
- `branch`
- `base`
- `constraints` — object

### Minimal valid example
```json
{
  "sourceQueueItemId": "picv-r-999",
  "sourceRole": "reviewer",
  "targetRole": "developer",
  "project": "picv_spike",
  "repoPath": "/home/openclaw/projects/picv_spike",
  "branch": "feature/picv_spike/replay-mode",
  "base": "main",
  "goal": "Document replay mode in README.",
  "checks": ["./check.sh"],
  "findings": [
    {
      "title": "Replay mode is undocumented",
      "detail": "README does not mention --input-video",
      "acceptance": "Add a minimal replay example and dependency note."
    }
  ],
  "constraints": {"timeboxMin": 8},
  "contextFiles": ["README.md", "check.sh"],
  "writtenAt": "2026-04-01T15:00:00+11:00"
}
```

## Mechanics behavior on invalid artifacts
If an artifact is malformed or under-specified:
- mechanics does **not** treat it as success
- the run is marked `blocked`
- a tick is appended describing the contract failure
- operator output reports a concise validation failure

### Examples of invalid conditions
- result artifact is not valid JSON
- `summary` missing or empty
- Developer result missing `commit` key
- Reviewer result missing boolean `approved`
- Reviewer result missing `findings` list
- Reviewer requested follow-up work but no valid handoff artifact was produced
- `writtenAt` is missing or not parseable as ISO timestamp

## Normalization notes
Current mechanics behavior may normalize the expected role into the result artifact when the role is omitted, but workers should still emit `role` explicitly.

Treat normalization as a small guardrail, not a contract to lean on.

## Practical guidance
If you are updating prompts/helpers/mechanics:
- do not weaken the artifact contract casually
- prefer explicit fields over inferred meaning
- treat artifact validation as part of the scheduler boundary, not presentation logic
