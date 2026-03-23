# First real run candidates (picv_spike)

Use a **single Developer item** first, not a full cycle.
Deliver to `#agent-ops` for visibility.

## Candidate A — replay mode truth pass
- Branch: `feature/picv_spike/replay-mode`
- Goal:
  - verify whether replay mode exists in the standalone repo
  - if missing, implement `--input-video` via ffmpeg decode
  - add/verify one replay smoke in `check.sh`
- Checks:
  - `./check.sh`
  - `rg -- '--input-video|ffmpeg' motion_gate_picamera2.py check.sh`
- Why good:
  - bounded, high-signal, closes a known ambiguity from the earlier run

## Candidate B — summarizer/check consistency pass
- Branch: `fix/picv_spike/check-and-summary`
- Goal:
  - make `summarize_events.py`, `check.sh`, and related tests internally consistent
  - ensure docs match current code reality
- Checks:
  - `./check.sh`
  - `python3 -m unittest -q test_summarize_events`
- Why good:
  - less risky, mostly repo coherence, good first mechanics test

## Candidate C — H.264 preroll rung polish
- Branch: `feature/picv_spike/preroll-rung`
- Goal:
  - validate `motion_gate_preroll_h264.py`
  - ensure docs/checks cover it cleanly
- Checks:
  - `./check.sh`
  - `python3 -m py_compile motion_gate_preroll_h264.py`
- Why good:
  - tangible capability rung, but a bit more hardware-adjacent

## Recommendation
Start with **Candidate A** (replay mode truth pass).
It directly addresses a previously confusing area and is valuable without requiring a full multi-role loop.
