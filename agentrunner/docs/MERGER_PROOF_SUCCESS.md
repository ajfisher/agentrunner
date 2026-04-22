# Merger Proof Success

> Historical proof note: this captures a successful ff-only Merger rerun from the earlier `master`-based branch contract. The branch names and command strings below are preserved as recorded evidence from that run, not as current operator guidance. For live work, use `main` as the steady-state base branch.

This note captures the corrected ff-only Merger proof rerun against `picv_spike`.

## Queue item
- Queue item id: `picv-m-002`
- Project: `picv_spike`
- Role: `merger`
- Source branch: `feature/picv_spike/replay-mode`
- Target branch: `master`

## Why this rerun mattered
The first merger proof exposed an unsafe sequencing bug:
- the merge command was treated like a preflight check
- the result artifact reported `blocked`
- repo state and artifact state diverged

This rerun used the hardened Merger contract:
- explicit reviewer approval in queue constraints
- read-only mergeability preflight
- actual `git merge --ff-only ...` only as the final side effect

## Result
Status: `ok`

Observed result summary:
- "Fast-forward merged feature/picv_spike/replay-mode into master after approval and checks passed."

Observed commit:
- `35ba58041c78c29c2b0305099623489fd64f77db`

## Checks recorded
- `reviewer-approval-evidence`
- `git status --short`
- `git diff --stat master...feature/picv_spike/replay-mode`
- `./check.sh`
- `git merge-base --is-ancestor master feature/picv_spike/replay-mode`
- `git merge --ff-only feature/picv_spike/replay-mode`

## Queue/tick evidence
Observed queue events:
- `ENQUEUE`
- `DEQUEUE`
- `DONE`

Observed tick:
- queue item id `picv-m-002`
- status `ok`
- merger artifact embedded in the tick record

## Git evidence
Post-run refs aligned with the artifact:
- `master` -> `35ba58041c78c29c2b0305099623489fd64f77db`
- `feature/picv_spike/replay-mode` -> `35ba58041c78c29c2b0305099623489fd64f77db`
- working tree clean

## Acceptance outcome
This rerun satisfied the constrained Merger proof criteria:
- explicit approval gate respected
- fast-forward-only policy respected
- artifact outcome matched repo outcome
- queue/tick/state bookkeeping stayed coherent

## Practical follow-up
- The Merger primitive is now proven in constrained ff-only form.
- Future merge tests should keep approval evidence explicit in the queue item.
- A later experiment can cover non-fast-forward handling / rebase passback behavior if needed.
