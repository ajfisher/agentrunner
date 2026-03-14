# Git flow (local)

We model a standard feature flow even before GitHub:

1) Developer works on a feature branch:
   - `feature/<project>/<slug>` (or `wip/<project>` as a rolling branch)
2) Reviewer reviews that branch vs main.
3) Manager decides whether to iterate or mark ready.
4) Merger merges to main.

Key: **"shipped" == committed on a branch**. If work is only in a stash, it's not shipped.
