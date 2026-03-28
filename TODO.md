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

## Current priority order

### 1) Handoff semantics + result schema
- [ ] Tighten reviewer result schema so `findings[]` is consistently emitted and used
- [ ] Ensure reviewer → developer follow-up items are cleanly developer-shaped in all cases
- [ ] Decide whether reviewer findings should also be written into a project-local artifact (e.g. `review_findings.json`)
- [ ] Improve developer prompt so it explicitly consumes structured reviewer findings rather than relying on prose/history

### 2) Docs + architecture hygiene
- [ ] Update docs to reflect that `/hooks/agent` + result files is now the primary dispatch/completion path
- [ ] Document deterministic session-key scheme (`hook:agentrunner:<project>:<queueItemId>`)
- [ ] Document result-file contract and expected JSON shapes by role
- [ ] Add a concise lifecycle diagram: queue item → invoker → hook run → result file → tick append → unlock

### 3) Validation passes
- [ ] Run another clean `Review → Dev → Review` test to verify the new follow-up shaping
- [ ] Verify a reviewer finding becomes a clean developer item with the right goal/checks/context
- [ ] Confirm result files and `ticks.ndjson` stay in sync across the sequence

### 4) Merge primitive
- [ ] Exercise Merger role on a dummy or low-risk real branch
- [ ] Confirm merge bookkeeping lands cleanly in ticks/logs

### 5) Optional niceties
- [ ] Add a small audit/status helper for queue events + result files + last ticks in one view
- [ ] Consider a project-specific adapter layer for custom checks/context beyond queue item fields
