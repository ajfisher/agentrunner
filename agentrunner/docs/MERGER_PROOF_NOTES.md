# Merger Proof Notes

> Historical proof note: this page explains lessons learned from the original `master`-era merger proofs. The remaining `master` wording is preserved because it refers to what happened in that earlier run; it should not be read as the live base-branch contract.

## First merger proof: key failure mode
The first ff-only merger proof against `picv_spike` exposed a sequencing bug:

- the Merger result artifact reported `blocked`
- but the repo state had already changed and `master` advanced to the feature tip

That means the merge action occurred before the final blocked/allowed decision was safely resolved.

## Core lesson
Treating `git merge --ff-only <branch>` as a "check" is unsafe.
It is the real side-effecting merge action when run on the target branch.

## Hardening rules derived from this proof
- require explicit reviewer approval evidence for Merger turns
- perform read-only checks first (`git diff`, `git status`, `git merge-base --is-ancestor`, etc.)
- only run `git merge --ff-only <branch>` after merge readiness is already established
- if a Merger result artifact says `merged: false`, repo state should remain unchanged
- if repo state changed, the result artifact must report `merged: true`

## Practical queue-item guidance
Prefer queue items that include:
- `branch`
- `base` (`main` for current/live work; preserved `master` only in historical proof payloads)
- `constraints.mergePolicy`
- `constraints.approvedByReviewer`
- optional approval source reference (e.g. prior reviewer queue item id / result path)

## Regression coverage added after the first proof
The merger-remediation pass now has focused regression scripts covering the supported repairable taxonomy and its guardrails:
- repairable `non_fast_forward` blockers routing a bounded Developer remediation item
- repairable `target_branch_missing` blockers routing a bounded Developer base-branch normalization passback
- a remediation fix returning through the normal Reviewer lane and re-queuing `closure-merger`
- unsafe / ambiguous blockers outside that repairable taxonomy halting remediation instead of silently looping another passback

See:
- `scripts/test_merger_passback_remediation_routing.py`
- `scripts/test_merger_passback_review_to_closure_retry.py`
- `scripts/test_merger_passback_unsafe_blocker_halt.py`

## Why this proof was valuable
This is exactly the kind of bug that would be easy to miss in a toy success path.
The proof showed that mechanics bookkeeping can be correct while the cognition-layer sequencing is still unsafe.
