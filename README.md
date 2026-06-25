# Pretty Good AI Voice Tester

Repository: https://github.com/SreytouchLang/AI-Engineering-Challenge

This repository implements a Python voice-bot assessment harness for Pretty Good AI's authorized challenge number, `+1-805-439-8008`. The current build is intentionally split into two layers:

1. A fully runnable local dry-run path that validates scenarios, simulates natural patient conversations, writes transcripts and metadata, and generates structured evaluations and bug reports.
2. A guarded live-call path that uses Twilio bidirectional media streams plus OpenAI-based STT, text generation, and TTS. Live calling is disabled by default and requires both `ENABLE_REAL_CALLS=true` and an explicit confirmation flag.

Phase 2 enhancements now added on top of the original scaffold:

- adaptive patient action planning instead of fixed turn scripts
- cancellable chunked playback for more realistic turn-taking
- explicit barge-in and overlap tracking
- dual-channel recording artifacts (`patient`, `agent`, and `mixed`)
- transcript validation gates and voice-quality scorecards
- evidence-linked bug objects plus a local FastAPI review UI
- replay mode and a dry-run A/B experiment harness

## Two-AI Voice Simulator (Free, No Phone Needed)

The fastest way to see this project work end-to-end, with **no telephony, no API keys, and no cost**. A simulated patient talks to a simulated clinic agent; the whole conversation is synthesized into real, listenable audio with the built-in macOS `say` voice engine, transcribed with matching timestamps, scored, and turned into a bug report.

Requirements: macOS (for the `say` command) and `ffmpeg` on `PATH` (`brew install ffmpeg`).

Run the full 12-scenario suite (produces 12 spoken calls):

```bash
make voice-suite
```

Or run a single scenario:

```bash
make voice-sim SCENARIO=scenarios/07_weekend_request.yaml
```

Each run writes, per call:

- a real mixed MP3 conversation in `artifacts/recordings/<call-id>-mixed.mp3` (plus per-speaker WAVs)
- a two-speaker transcript re-timed to the audio in `artifacts/transcripts/<call-id>.txt`
- a structured evaluation in `artifacts/evaluations/<call-id>.json`
- an aggregate, severity-sorted [VOICE_SIM_BUG_REPORT.md](VOICE_SIM_BUG_REPORT.md)

This path uses two distinct voices (patient vs. agent) and natural sequential turn-taking, so the recordings sound like a genuine phone conversation. It is fully self-contained and does not place or simulate any real telephone call.

## Architecture Summary

The live architecture uses Twilio to place and record the outbound call, then hands the audio to a FastAPI WebSocket endpoint using bidirectional media streams. Incoming office audio is segmented locally with a small VAD-style turn manager, transcribed with OpenAI STT, passed through a patient-state controller, and synthesized back into phone-ready mu-law audio for Twilio playback. Recordings, transcripts, evaluations, and metadata are stored as first-class artifacts so the bug-report step is traceable to exact calls.

I chose request-based STT/TTS over a more complex speech-to-speech bridge because it keeps the repo much easier to debug and test inside a take-home while still supporting natural short-turn conversations. Inference: with short one-to-two-sentence patient replies, the expected post-turn latency should land around 1.2 to 2.2 seconds in a typical deployment, and 10 to 15 calls should usually stay within the challenge's sub-$20 budget target depending on call length, retranscription retries, and telephony rates.

## Prerequisites

- Python 3.11 or newer
- `ffmpeg` available on `PATH` for audio conversion
- A public HTTPS tunnel or deployment for Twilio webhooks during live calls
- A Twilio account with one outbound voice number
- OpenAI API access for the LLM, STT, and TTS paths

## Account And Provider Setup

1. Create the challenge product account at `pgai.us/athena`.
2. Provision one Twilio number for all outbound assessment calls.
3. Configure a public webhook base URL, for example with `ngrok http 8000`.
4. Use the same OpenAI key for `LLM_API_KEY`, `STT_API_KEY`, and `TTS_API_KEY` if you are using OpenAI for all three services.

## Environment Variables

Copy `.env.example` to `.env` and fill in placeholders only:

```bash
ENABLE_REAL_CALLS=false
AUTHORIZED_DESTINATION=+18054398008
TELEPHONY_ACCOUNT_ID=
TELEPHONY_AUTH_TOKEN=
TELEPHONY_FROM_NUMBER=
LLM_API_KEY=
STT_API_KEY=
TTS_API_KEY=
PUBLIC_BASE_URL=
MAX_CALL_DURATION_SECONDS=180
MAX_CALLS_PER_RUN=1
MONTHLY_COST_LIMIT_USD=20
```

## Local Webhook Or Tunnel Setup

Run the API server locally:

```bash
make serve
```

Expose it publicly with a tunnel such as:

```bash
ngrok http 8000
```

Then set `PUBLIC_BASE_URL` to the public HTTPS origin.

## Installation

```bash
make install
```

## Dry-Run Instructions

Run a single text-only simulated call:

```bash
make dry-run SCENARIO=scenarios/01_simple_scheduling.yaml
```

This writes a transcript and metadata under `artifacts/` without dialing a phone number.

## One-Call Instructions

Run the explicit live-call preflight first:

```bash
python scripts/preflight_live_call.py --scenario scenarios/01_simple_scheduling.yaml
```

If the preflight is ready and you explicitly want to dial, place one call at a time with the live gate enabled:

```bash
ENABLE_REAL_CALLS=true python scripts/run_call.py \
  --scenario scenarios/01_simple_scheduling.yaml \
  --confirm-live-call=true
```

Or with `make`:

```bash
make call SCENARIO=scenarios/01_simple_scheduling.yaml CONFIRM_REAL_CALL=true
```

The live path now prints a preflight summary and still requires a final interactive confirmation before dialing.

## Scenario-Suite Instructions

Run the dry-run suite:

```bash
make suite
```

## Artifact Locations

- `artifacts/recordings/` stores MP3, OGG, or WAV recordings
- `artifacts/transcripts/` stores human-readable and JSON transcripts
- `artifacts/evaluations/` stores structured analysis output
- `artifacts/call_metadata/` stores call metadata JSON

## Test Instructions

```bash
make format-check
make lint
make typecheck
make test
```

## Analysis And Reporting

Analyze a completed call:

```bash
python scripts/analyze_call.py --call-id call-001
```

Fetch and validate the provider recording for a real call:

```bash
python scripts/fetch_recording.py --call-id call-001
```

Create or refresh the two-speaker transcript for a real call:

```bash
python scripts/transcribe_call.py --call-id call-001
```

Review issues and build the Markdown bug report:

```bash
python scripts/build_report.py --review
```

Replay a saved call without redialing:

```bash
python scripts/replay_call.py --call-id call-021
```

Run the built-in A/B experiment:

```bash
python scripts/run_experiment.py --config experiments/shorter_patient_turns/config.yaml
```

Open the local review dashboard after `make serve`:

```text
http://localhost:8000/review/
```

## Submission Prep Commands

Validate scenario completeness:

```bash
python scripts/validate_scenarios.py
```

Summarize current live-call evidence and generate the review templates:

```bash
python scripts/summarize_live_calls.py
```

Validate committed live-call recordings:

```bash
python scripts/validate_recordings.py
```

Validate committed live-call transcripts:

```bash
python scripts/validate_transcripts.py
```

Review the current code-level live-call audit before the first smoke call:

- [LIVE_CALL_READINESS.md](LIVE_CALL_READINESS.md)
- [FIRST_REAL_CALL_PLAN.md](FIRST_REAL_CALL_PLAN.md)

Rank currently selected calls:

```bash
python scripts/rank_calls.py
```

Run the final repository readiness check:

```bash
make submission-check
```

`make submission-check` is intentionally strict and exits nonzero until public Loom links, approved live-call evidence, and submission-ready call selections exist.

## Cost Controls

- The destination number is locked to `+1-805-439-8008`
- Real calls require `ENABLE_REAL_CALLS=true`
- Real calls also require `--confirm-live-call=true`
- `MAX_CALL_DURATION_SECONDS` caps a single call
- `MAX_CALLS_PER_RUN` and `MONTHLY_COST_LIMIT_USD` protect the run budget
- `make suite` uses dry-run mode only

## Safety Restrictions

- Never change `AUTHORIZED_DESTINATION`
- Never commit `.env` or live secrets
- Never claim a real call succeeded without a provider call id and artifact files
- Never treat dry-run artifacts as live-call evidence
- Use only fictional patient details

## Troubleshooting

- If live calls fail immediately, confirm `PUBLIC_BASE_URL` is publicly reachable over HTTPS.
- If the server starts but live media fails, confirm the tunnel allows WebSocket traffic.
- If transcripts are empty in the live path, check STT credentials and the mu-law stream configuration.
- If audio conversion fails, confirm `ffmpeg` is installed and on `PATH`.

## Known Limitations

- Real-call execution still requires valid provider credentials and manual verification of recordings.
- The dry-run office agent is intentionally simple and exists to exercise the patient and reporting pipeline, not to replace the real challenge line.
- The live path is production-oriented but still needs real-call iteration to tune latency, interruption thresholds, and prompt style.
- The audio path now uses local G.711 mu-law, PCM mixing, and linear resampling helpers; a more specialized DSP/codec stack would still be preferable for a long-lived production deployment.
- Dual-channel capture is requested from Twilio and also reconstructed locally, but real-call verification is still required to confirm the provider-side channels and recordings behave as expected on actual calls.

## Scope Note

This repository was built in the context of the Pretty Good AI voice challenge, whose task is to place **real phone calls** to an assessment line. Without paid telephony credentials, that live submission is not possible. The headline, fully working deliverable here is therefore the **free two-AI voice simulator** documented above: it generates real, listenable voice conversations, transcripts, and a bug report at $0. A guarded live-call path (Twilio + OpenAI) is also included but is disabled by default and is not exercised in this build.

## Project Checklist (Voice Simulator)

Every box below reflects the free, fully runnable simulator and is verified true in this build.

- [x] Public GitHub repository is accessible
- [x] Runs end-to-end with a single command (`make voice-suite`), no API keys or cost
- [x] At least 10 complete simulated voice calls are produced (12-scenario suite)
- [x] Every simulated call has a real, non-silent MP3 recording
- [x] Every simulated call has a transcript with both speakers, re-timed to the audio
- [x] Bug report is generated automatically and cites call, timestamp, and recording
- [x] Strong findings are prioritized over weak ones (severity-sorted report)
- [x] README contains setup and run instructions
- [x] `.env.example` exists and no secrets are committed
- [x] Architecture explanation is included
- [x] Iteration notes are documented honestly
- [x] All tests pass (`make test`)
- [x] Lint, format, and type checks pass
- [x] Repository uses fictional patient information only
- [x] Only the authorized assessment number is permitted in the live-call code path

### Not done (would require a paid live submission)

- [ ] Real phone calls to the PGAI assessment line (needs Twilio + OpenAI credentials)