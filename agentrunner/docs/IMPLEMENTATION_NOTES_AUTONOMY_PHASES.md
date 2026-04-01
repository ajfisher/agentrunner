# Implementation Notes: Autonomy Hardening Phases

## Scope
These notes capture the current agreed approach for the next stage of `agentrunner`, using the live `picv_spike` setup as the proving ground.

Relevant paths:
- AgentRunner repo: `/home/openclaw/projects/agentrunner`
- AgentRunner runtime state: `/home/openclaw/.agentrunner/projects/picv_spike`
- PiCV project repo: `/home/openclaw/projects/picv_spike`
- Current PiCV branch used in recent runs: `feature/picv_spike/replay-mode`

## Current observation
The system is past the “nothing works” stage.

It already has:
- queue events
- ticks
- result artifacts
- handoff artifacts
- hook-based dispatch
- operator summaries

That is useful progress, but it changes the risk profile.

The main risk now is **apparent success despite soft mechanics contracts**.
A broad chained run can look mostly successful while still hiding ambiguity in:
- which helper contract is canonical
- what counts as a valid completion artifact
- how follow-up Developer turns consume Reviewer output

## Why this plan exists
The next step should not be “run a bigger autonomy sequence and hope the weak spots reveal themselves.”

Instead, the next work should harden the mechanics around completion/finalization so that:
- valid runs are mechanically recognizable
- invalid runs fail loudly and legibly
- follow-up turns consume deterministic artifacts instead of conversational residue

## Phase 1 — Singular completion contract
Goal: there should be one blessed way for workers to emit result + handoff artifacts.

### Problem
The repo briefly had two competing helper name pairs for the same artifact contract.
That created drift between helper names, prompts, and mechanics wiring.

Phase 1 resolves this by making:
- `emit_result.py`
- `emit_handoff.py`

the only forward contract.

### Required changes
- Pick one canonical helper pair.
  - Preferred: `emit_result.py` and `emit_handoff.py`
- Update `invoker.py` so `RESULT_HELPER` and `HANDOFF_HELPER` reference the canonical pair.
- Update prompts, examples, docs, and any inline command examples to use the same names.
- Remove the non-canonical helper pair once references are gone so the contract stays unambiguous.

### Acceptance signal
There is no ambiguity anywhere in the repo about which helper command a worker is expected to run.

## Phase 2 — Validate artifacts at the mechanics boundary
Goal: the mechanics layer should validate output shape, not just file existence.

### Problem
A result file appearing is not the same as a run completing correctly.
If the invoker only checks presence, malformed or under-specified artifacts can be treated as success.

### Required changes
Add mechanics-side validation in `invoker.py` before marking a queue item `DONE`.

Suggested baseline contract:
- all roles:
  - `status`
  - `role` or normalized/inferred equivalent
  - `writtenAt`
- developer:
  - `summary`
  - `checks`
  - `commit` (nullable but explicit)
- reviewer:
  - `approved`
  - `findings` (always present, even if empty)
  - `summary`
- if reviewer requests follow-up:
  - valid handoff artifact must also exist

### Failure behavior
If result or handoff artifacts are malformed:
- do **not** silently continue
- append a tick that records a mechanics-level failure / blocked state
- send a concise operator summary saying the artifact contract failed
- leave a clear reason for debugging

### Acceptance signal
The mechanics layer distinguishes between:
- file appeared
- valid artifact
- invalid artifact

This acceptance signal is now present in the mechanics path; next work should build on it rather than re-arguing whether file presence is sufficient.

## Phase 3 — Deterministic Developer consumption of Reviewer output
Goal: Developer follow-up turns should consume Reviewer outputs directly and predictably.

### Problem
Even with better prompts, relying on history/prose leaves too much room for drift.
The handoff relationship should be explicit and file-backed where possible.

### Required changes
- Pass explicit prior-review artifact path(s) into Developer turns when available.
- Make the Developer prompt say, plainly, that structured findings / handoff artifacts should be read first.
- Consider writing a stable project-local artifact such as `review_findings.json` if that simplifies deterministic consumption.
- Ensure follow-up Developer queue items stay developer-shaped rather than becoming prose-mutants from reviewer summaries.

### Acceptance signal
A Developer follow-up can explain exactly which structured Reviewer findings it consumed and what it did with them.

The remaining proof obligation is to run a narrow validation pass and confirm the emitted Developer summary/checks visibly map back to those findings in practice.

## Phase 4 — Single-item harness proof
Goal: isolate the completion/finalization path and prove it on one tiny run.

### Why this comes before broader chaining
A narrow proof removes ambiguity.
If it fails, the problem is in:
- dispatch
- artifact emission
- validation
- tick append
- unlock

—not in queue choreography.

### Test shape
Run one single Developer item against `picv_spike` with a very bounded task.
Prefer something deliberately boring, for example:
- docs-only update
- no-op confirmation task
- tiny verification task with explicit checks

### Success criteria
- hook run starts
- result artifact appears
- artifact passes validation
- `ticks.ndjson` records the run correctly
- operator summary is concise and correct
- queue unlocks cleanly

### Output
Capture this as the canonical proof of the completion/finalization path.

## Phase 5 — Small chained proof
Goal: only after Phase 4 passes, prove one minimal handoff loop.

### Suggested test
Run either:
- `Reviewer → Developer`
or
- `Reviewer → Developer → Reviewer`

Use a narrow PiCV task, not a broad “real work” branch effort.

### Success criteria
- Reviewer emits structured findings
- handoff artifact validates
- Developer consumes handoff deterministically
- Developer emits valid result
- queue events, results, and ticks all stay coherent

## Recommended implementation order
1. singular helper contract
2. mechanics-side artifact validation
3. deterministic Developer consumption of Reviewer artifacts
4. single-item proof run
5. small chained proof
6. broader autonomy / merge flow only after the above is stable

## Practical note
At this stage, the danger is not only hard failure.
It is **plausible-looking success with fuzzy contracts**.

So the right move is intentionally boring:
- reduce ambiguity
- validate aggressively
- prove the narrow path first
- scale up only once the mechanics are crisp
only hard failure.
It is **plausible-looking success with fuzzy contracts**.

So the right move is intentionally boring:
- reduce ambiguity
- validate aggressively
- prove the narrow path first
- scale up only once the mechanics are crisp
