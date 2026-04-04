# Merger Proof Notes

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
- `base`
- `constraints.mergePolicy`
- `constraints.approvedByReviewer`
- optional approval source reference (e.g. prior reviewer queue item id / result path)

## Why this proof was valuable
This is exactly the kind of bug that would be easy to miss in a toy success path.
The proof showed that mechanics bookkeeping can be correct while the cognition-layer sequencing is still unsafe.
