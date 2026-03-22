# TODO

## Current priority order

### 1) Mechanics cleanup
- [ ] Implement deterministic reset policy for `extraDevTurnsUsed`
- [ ] Document reset policy in `agentrunner` docs
- [ ] Optionally add a small status/audit command for queue + current run + last ticks

### 2) Project isolation
- [ ] Create `/home/openclaw/projects/picv_spike/`
- [ ] Move/copy current `picv_spike` into that repo
- [ ] Initialize/clean git state there
- [ ] Keep OpenClaw workspace repo out of the execution path

### 3) First real run with agentrunner
- [ ] Create `/home/openclaw/.agentrunner/projects/picv_spike/`
- [ ] Seed queue with a small real task
- [ ] Run Dev → Review → maybe extra Dev → Review
- [ ] Observe before enabling longer unattended cycles

### 4) Merge primitive
- [ ] Exercise Merger role on a dummy or low-risk real branch
- [ ] Confirm merge bookkeeping lands cleanly in ticks/logs
