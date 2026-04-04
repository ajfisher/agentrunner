# Git flow (local)

We model a standard feature flow even before GitHub:

1) Developer works on a feature branch:
   - `feature/<project>/<slug>` (or `wip/<project>` as a rolling branch)
2) Reviewer reviews that branch vs main.
3) Manager decides whether to iterate or mark ready.
4) Merger merges to main.

Current default merge policy for local autonomous runs:
- prefer **fast-forward only** merges
- if fast-forward is not possible, treat the merge as **blocked** unless the queue item explicitly authorizes another strategy

Key: **"shipped" == committed on a branch**. If work is only in a stash, it's not shipped.

## Default branch naming convention

For now, use:
- `feature/<project>/<slug>` for implementation work
- `fix/<project>/<slug>` for bug-fix / cleanup work

Example:
- `feature/picv_spike/replay-mode`
- `fix/picv_spike/check-sh-cleanup`

This keeps local workflow aligned with likely future GitHub usage.
