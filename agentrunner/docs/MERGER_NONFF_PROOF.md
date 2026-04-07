# Merger Non-FF Proof

This note captures the constrained non-fast-forward Merger proof against `picv_spike`.

## Queue item
- Queue item id: `picv-m-nonff-001`
- Project: `picv_spike`
- Role: `merger`
- Source branch: `feature/picv_spike/ff-passback-proof`
- Target branch: `master`
- Merge policy: `ff-only`
- Approval evidence: explicit in queue constraints (`approvedByReviewer=true`)

## Why this proof mattered
The corrected ff-only success proof showed that the Merger primitive can merge safely when:
- approval is explicit
- fast-forward is possible
- the merge action is sequenced after read-only preflight checks

The next missing proof was the blocked path:
- what happens when reviewer approval is present
- but fast-forward is **not** possible

## Synthetic setup
A sacrificial non-FF scenario was created in `picv_spike`:
- base commit: `35ba580`
- feature-only proof commit: `5ce52b8` (`docs: add ff-passback proof branch note`)
- master-only proof commit: `7627f87` (`docs: add master-side ff-passback proof note`)

This produced a clean divergence where `master` was not an ancestor of `feature/picv_spike/ff-passback-proof`.

## Result
Status: `blocked`

Observed result summary:
- "Merge blocked; fast-forward only policy is enabled, but master is not an ancestor of feature/picv_spike/ff-passback-proof, so ff-only merge cannot proceed. Reviewer approval was present, and git state was left unchanged."

Observed commit field:
- `7627f878933d48a1907b7092cb7b0ea04125f4df` (current target-branch HEAD at block time)

Observed checks:
- `git status --short` → `ok`
- `git diff --stat master...feature/picv_spike/ff-passback-proof` → `ok`
- `git merge-base --is-ancestor master feature/picv_spike/ff-passback-proof` → `blocked`
- `merge-policy ff-only` → `blocked`

## Queue/tick evidence
Observed queue events:
- `ENQUEUE`
- `DEQUEUE`
- `DONE`

Observed tick:
- queue item id `picv-m-nonff-001`
- status `blocked`
- merger artifact embedded in the tick record

## Git evidence
Post-run refs stayed unchanged:
- `master` -> `7627f878933d48a1907b7092cb7b0ea04125f4df`
- `feature/picv_spike/ff-passback-proof` -> `5ce52b81f0f0f37c6a34e1f4e9d1c5ab67b73d2d`
- working tree clean

Critically:
- no side-effecting merge occurred
- blocked artifact and repo state matched

## Acceptance outcome
This proof satisfied the constrained non-FF blocked-path criteria:
- explicit approval evidence present
- ff-only policy respected
- non-fast-forward state detected via read-only preflight
- merge did not happen
- artifact outcome matched repo outcome
- queue/tick/state bookkeeping stayed coherent

## Practical follow-up
The next unresolved experiment is not merge safety itself.
It is **post-block behavior**:
- when ff-only merge is blocked by divergence,
- what role/task should bring the branch back to a mergeable state?

Current likely candidate:
- a Developer passback / rebase task, followed by re-review and a second merge attempt.

Operator-facing blocked summaries should surface that recovery path directly so the next action is obvious at handoff time.
