# Chained Proof Run Notes

This note captures the first constrained Phase 5 chained proof against `picv_spike`.

## What worked
- Reviewer emitted a valid blocked result with structured follow-up intent.
- Reviewer emitted a valid handoff artifact.
- Mechanics inserted an artifact-driven follow-up Developer item.
- The inserted Developer item received deterministic reviewer artifact paths:
  - `SOURCE_RESULT_PATH`
  - `SOURCE_HANDOFF_PATH`
  - `REVIEW_FINDINGS_PATH`
- The inserted Developer item produced a coherent docs-only fix tied to the reviewer finding.
- Queue events, handoff artifacts, review-findings artifacts, and ticks all stayed coherent.
- Validation correctly blocked the final review when the artifact shape was malformed.

## What the proof exposed
### 1) Queue design smell for chained proofs
For this proof, a generic Developer queue item was pre-seeded **and** the Reviewer generated a real handoff-driven follow-up item.
That caused two Developer turns to run:
- the inserted artifact-driven follow-up
- then the pre-seeded generic Developer item

Conclusion:
- for future chained proofs, do **not** pre-seed a generic Developer item when the Reviewer is expected to generate the real follow-up work item.

### 2) Reviewer findings shape can still go malformed
The final review semantically looked like approval, but emitted malformed findings shape (`findings[0]` was not an object).
Mechanics validation correctly blocked the run.

Conclusion:
- tighten Reviewer prompt guidance for flat finding objects
- add helper-side defensive flattening/coercion where safe

## Practical follow-up
- Prefer `Reviewer -> generated follow-up Developer -> Reviewer` as the canonical chained proof pattern.
- Avoid queueing a second generic Developer step unless you are explicitly testing non-handoff fallback behavior.
