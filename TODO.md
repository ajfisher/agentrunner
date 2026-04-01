# TODO

## Current reality
Completed already:
- [x] `picv_spike` moved to `/home/openclaw/projects/picv_spike/`
- [x] Runtime state scaffold exists at `/home/openclaw/.agentrunner/projects/picv_spike/`
- [x] First real single-Dev run on `picv_spike` completed
- [x] Hooks-based dispatch (`/hooks/agent`) is working
- [x] Result-file completion/unlock path is working
- [x] Extra Dev turn insertion works
- [x] Reviewer-triggered follow-up now starts being shaped as a proper Developer item
- [x] Structured result artifacts, handoff artifacts, queue events, and ticks all exist in the live `picv_spike` runtime state

## Current diagnosis
The next bottleneck is **not** queue movement or basic dispatch. The mechanics layer is far enough along that the main risk is now **soft completion contracts**:
- result artifacts are treated mostly as presence checks rather than strongly validated contracts
- developer follow-up turns still rely too much on prose/history instead of deterministic artifact consumption
- broad chained runs can look “mostly successful” even when finalization semantics are still wobbly

## Current priority order

### 1) Singular completion contract (Phase 1)
Goal: there should be exactly one blessed way for workers to emit result + handoff artifacts.

- [x] Choose the canonical helper pair and standardize on it everywhere
  - canonical: `emit_result.py` + `emit_handoff.py`
- [x] Update `invoker.py` so `RESULT_HELPER` / `HANDOFF_HELPER` point at the canonical helpers
- [x] Update prompts/examples/docs so they reference the same helper names everywhere practical in the current repo surface
- [x] Remove the old `write_result.py` / `write_handoff.py` helpers so the contract is forward-only
- [x] Confirm there is no remaining contract drift between prompts, invoker wiring, docs, and helper files for the active mechanics path

### 2) Validate artifacts at the mechanics boundary (Phase 2)
Goal: the mechanics layer should accept only valid completion artifacts, not merely existing files.

- [x] Add result-artifact validation inside `invoker.py` before marking `DONE`
- [x] Require role-appropriate fields in result artifacts
  - reviewer: `approved`, `findings` (always present, even if `[]`)
  - developer: explicit `summary`, `checks`, `commit` (nullable but explicit)
  - all roles: stable `status`, `role` or normalized equivalent, valid `writtenAt`
- [x] If a result artifact is malformed, mark the run as a mechanics-level failure / blocked state with a concise reason in ticks + operator summary
- [x] Add handoff-artifact validation when reviewer follow-up work is requested
- [x] If follow-up is requested but handoff is missing/malformed, treat that as a blocked mechanics failure rather than silently continuing
- [x] Document the artifact contracts and failure modes

### 3) Deterministic developer consumption of reviewer output (Phase 3)
Goal: follow-up dev turns should consume structured reviewer artifacts directly, not infer intent from chat prose/history.

- [x] Pass explicit prior-review artifact path(s) into developer turns when available
- [x] Improve developer prompt so it explicitly reads structured reviewer findings / handoff artifacts first
- [x] Decide whether to materialize a stable project-local findings artifact (e.g. `review_findings.json`)
  - implemented as per-run state artifacts under `review_findings/<queueItemId>.json`
- [x] Ensure reviewer → developer follow-up items remain cleanly developer-shaped in all cases
- [ ] Verify developer summaries/checks clearly map back to reviewer findings addressed

### 4) Narrow proof: single-item harness test (Phase 4)
Goal: prove dispatch → artifact emission → validation → tick append → unlock in isolation.

- [ ] Run one **single Developer item** against `picv_spike` with a tiny bounded goal
- [ ] Prefer a low-cognition task (docs-only, no-op confirmation, or similarly boring proof)
- [ ] Acceptance criteria:
  - hook run starts cleanly
  - result artifact appears
  - artifact passes validation
  - `ticks.ndjson` is updated correctly
  - operator summary is concise and correct
  - queue unlocks cleanly
- [ ] Capture the run as the canonical proof for the completion/finalization path

### 5) Small chained proof after the single-item pass (Phase 5)
Goal: prove one minimal handoff cycle only after the completion contract is trustworthy.

Phase 4 single-item proof is now complete; Phase 5 is the next live proof target.

- [ ] Run a small `Reviewer → Developer` or `Reviewer → Developer → Reviewer` test after Phase 4 passes
- [ ] Verify reviewer emits structured findings cleanly
- [ ] Verify handoff artifact is valid and consumed by Developer deterministically
- [ ] Confirm result artifacts, queue events, and `ticks.ndjson` remain in sync across the sequence
- [ ] Prefer a narrow PiCV test case over a broad “real work” run

### 6) Docs + architecture hygiene
- [x] Update docs to reflect that `/hooks/agent` + result files is the primary dispatch/completion path
- [x] Document deterministic session-key scheme (`hook:agentrunner:<project>:<queueItemId>`)
- [ ] Add a concise lifecycle diagram: queue item → invoker → hook run → validated result file → tick append → unlock
- [x] Add implementation notes capturing the phased hardening plan and rationale

### 7) Merge primitive
- [ ] Exercise Merger role on a dummy or low-risk real branch
- [ ] Confirm merge bookkeeping lands cleanly in ticks/logs

### 8) Optional niceties
- [ ] Add a small audit/status helper for queue events + result files + last ticks in one view
- [ ] Consider a project-specific adapter layer for custom checks/context beyond queue item fields

### 9) Operator UX cleanup
- [x] Remove raw JSON from Discord-visible outputs
- [x] Prefix Discord messages with role/persona (`Developer ›`, `Reviewer ›`, etc.)
- [x] Tighten operator summaries to short bullets instead of long mixed prose+machine payloads

## Execution note
Recommended working order:
1. singular helper contract
2. mechanics-side artifact validation
3. deterministic developer consumption of reviewer artifacts
4. single-item proof run
5. small chained proof
6. broader autonomy / merger work later

Do **not** jump straight into bigger chained autonomy runs until the completion/finalization contract is mechanically trustworthy.
