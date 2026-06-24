# Loom Script

## Main Walkthrough

### 0:00–0:30 — Problem and result

- Explain that the system calls only the authorized assessment line as a fictional patient.
- State that the repo already supports dry-run simulation, transcript generation, structured evaluation, and a guarded live-call path.
- If real calls exist by recording time, name the strongest selected call immediately and say why it was chosen.

### 0:30–1:20 — Architecture

- Show `app/telephony/`, `app/voice/`, `app/agent/`, and `app/analysis/`.
- Explain the call loop: Twilio stream -> local turn detection -> STT -> patient state controller -> TTS -> artifact storage.
- Call out why evaluation is offline instead of inside the live loop.

### 1:20–2:20 — Conversation quality

- Prefer the strongest real selected call here once it exists.
- If real calls are still pending, say that explicitly and use a dry-run clip only as an implementation preview rather than submission evidence.
- Open the resulting transcript and point out short patient responses, corrections, and scenario-driven behavior.

### 2:20–3:20 — Bugs found

- Show how `scripts/analyze_call.py` produces structured issues.
- Open `BUG_REPORT.md` and explain that real-call findings remain pending until live evidence exists.

### 3:20–4:10 — Iteration

- Show the mid-call context-change scenario and the regression test that protects it.
- Explain the original bug: after the patient changed the requested day and reason, the office simulator skipped the revised confirmation branch.
- Show the patched branch-relative indexing in `app/agent/dry_run.py`.

### 4:10–5:00 — Code quality and run command

- Show the number guard in `app/safety.py`.
- Show the live-call preflight gate in `scripts/preflight_live_call.py` and the final interactive confirmation in `scripts/run_call.py`.
- End with current limitations: live credentials, manually verified recordings, and Loom URLs are still required until they are actually produced.

## AI Debugging Recording

Prefer a real approved live-call bug here once one exists. Until then, use the already-fixed context-change regression only as a rehearsal script and say clearly that it is not a live-call submission finding.

### Reproduction

```bash
pytest tests/test_dry_run.py -k context_change
```

### Suggested flow

1. Reproduce the failing context-change test.
2. Open `tests/test_dry_run.py` and `app/agent/dry_run.py`.
3. Ask the AI to explain why the updated confirmation branch never runs.
4. Review the branch-indexing hypothesis together.
5. Ask for the smallest safe fix.
6. Apply the fix.
7. Re-run the focused test.
8. Re-run the broader dry-run tests.
9. Explain why the regression test now proves the stale-state bug is fixed.

### Prompt 1 — Investigate

“Here is the failing `context_change` dry-run test and the related office-simulator code in `app/agent/dry_run.py`. Please identify the most likely root cause. Do not change the code yet. Explain the event sequence and point to the specific lines that may be wrong.”

### Prompt 2 — Design the fix

“Propose the smallest change that fixes this context-change branch bug without affecting the other scenario flows. Include any regression tests we should add.”

### Prompt 3 — Implement

“Apply the minimal fix and add the regression test. Preserve the current architecture and avoid unrelated refactoring.”

### Prompt 4 — Verify

“The focused tests now pass. Review whether they genuinely prove that the updated appointment day and visit reason are retained, rather than only checking a mocked implementation detail.”
