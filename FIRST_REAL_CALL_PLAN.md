# First Real Call Plan

Audit date: 2026-06-24 (America/Los_Angeles)

Scenario:

- `scenarios/01_simple_scheduling.yaml`

Exact command:

```bash
ENABLE_REAL_CALLS=true \
python scripts/run_call.py \
  --scenario scenarios/01_simple_scheduling.yaml \
  --confirm-live-call=true
```

Expected call ID:

- `call-025` if no new call metadata or artifacts are created before approval
- Rerun preflight immediately before dialing because the next unique call id can change

Expected cost:

- `$1.25` based on the current `expected_cost_per_call_usd` setting

Maximum duration:

- `180` seconds

Expected artifacts after a successful smoke call:

- `artifacts/call_metadata/call-025.json`
- `artifacts/recordings/call-025-provider-original.mp3`
- `artifacts/recordings/call-025.mp3`
- `artifacts/recordings/call-025-patient.wav`
- `artifacts/recordings/call-025-agent.wav`
- `artifacts/recordings/call-025-mixed.mp3`
- `artifacts/transcripts/call-025.txt`
- `artifacts/transcripts/call-025.json`
- `artifacts/evaluations/call-025.json`
- `artifacts/quality/call-025-quality.json`
- `artifacts/quality/call-025-quality.md`
- `artifacts/validation/call-025-recording-validation.json`
- `artifacts/validation/call-025-recording-validation.md`
- `artifacts/validation/call-025-validation.json`
- `artifacts/validation/call-025-validation.md`

Success criteria:

- Preflight returns `Ready: True`
- The dialed destination remains locked to `+1-805-439-8008`
- Twilio returns a provider call id and the call reaches a terminal provider status
- A downloadable provider recording is retrieved and validated as a non-silent MP3 or OGG
- A two-speaker transcript is generated and passes transcript validation
- Evaluation and quality artifacts are generated without fabricating any review results
- `LIVE_CALL_PROGRESS.md` updates with one provider-confirmed call ready for manual listening

Abort criteria:

- Preflight is not fully ready
- The destination number differs from `+1-805-439-8008`
- The originating number is unset or differs from the approved single Twilio number
- Credentials, webhook reachability, or WebSocket derivation fail
- The call fails before a provider call id or terminal status is recorded
- Recording download, recording validation, or transcript validation fails
- Actual provider behavior suggests the voice quality is too poor to continue batching calls

Post-call validation commands:

```bash
python scripts/fetch_recording.py --call-id call-025
python scripts/transcribe_call.py --call-id call-025
python scripts/analyze_call.py --call-id call-025
python scripts/validate_recordings.py
python scripts/validate_transcripts.py
python scripts/summarize_live_calls.py
python scripts/rank_calls.py || true
make submission-check
```

Approval gate:

- Do not run the live command above until the user explicitly approves the first real smoke call after reviewing the latest preflight output.
