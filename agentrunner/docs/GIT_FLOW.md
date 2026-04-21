# Git flow (local)

We model a standard feature flow even before GitHub:

1) Developer works on a feature branch:
   - `feature/<project>/<slug>` (or `wip/<project>` as a rolling branch)
2) Reviewer reviews that branch vs main.
3) Manager decides whether to iterate or mark ready.
4) Merger merges to main.

Canonical base-branch contract: `main` is the steady-state base branch for new work, examples, queue items, and artifact payloads. Any remaining `master` mentions are legacy/historical-only and should stay confined to proof notes that describe past runs.

Bounded audit status:
- active contract/default surfaces now use `main`
- sample/example payloads now use `main`
- intentionally retained legacy references live only in `MERGER_PROOF_NOTES.md`, `INITIATIVE_FIRST_RUN_NOTES.md`, `MERGER_PROOF_SUCCESS.md`, and `MERGER_NONFF_PROOF.md`

Current default merge policy for local autonomous runs:
- prefer **fast-forward only** merges
- if fast-forward is not possible, treat the merge as **blocked** unless the queue item explicitly authorizes another strategy
- require explicit reviewer approval evidence before a Merger turn performs any state-changing merge action
- treat ancestry / merge-base checks as preflight; treat `git merge --ff-only ...` as the actual merge step

Key: **"shipped" == committed on a branch**. If work is only in a stash, it's not shipped.

## Default branch naming convention

For now, use:
- `feature/<project>/<slug>` for implementation work
- `fix/<project>/<slug>` for bug-fix / cleanup work

Example:
- `feature/picv_spike/replay-mode`
- `fix/picv_spike/check-sh-cleanup`

This keeps local workflow aligned with likely future GitHub usage.
