# Iteration Log

## Initial architecture

- Selected Twilio bidirectional media streams for the telephony boundary.
- Chose FastAPI for webhook and WebSocket handling.
- Chose a split between live conversation logic and offline evaluation so reporting stays auditable.
- Chose request-based OpenAI STT and TTS instead of a more complex speech-to-speech bridge to keep the take-home implementation understandable and testable.

## First successful local milestone

- Completed a dry-run conversation pipeline that loads a YAML scenario, simulates both sides of the conversation, writes transcripts and metadata, and supports offline evaluation.
- Ran the 12-scenario dry-run suite successfully and produced fresh transcript and metadata artifacts locally.
- Added a 25-test regression suite covering guardrails, scenario loading, turn detection, transcript validation, evaluation rules, and telephony error handling.
- Added adaptive patient action planning, transcript validation, dual-channel artifact generation, replay mode, and a FastAPI review surface before any real-call execution.

## Real issues found during development

- The dry-run context-change scenario originally had a state-branch indexing bug: once the patient changed the day and visit reason, the office simulator skipped the updated confirmation step.
- The fix was to reset branch-relative indexing after the mid-call context change so the revised confirmation lines could actually execute.
- Added a regression test around the context-change flow so future edits do not reintroduce the stale-state behavior.

## Current evidence

- Dry-run artifacts and the evaluation pipeline are implemented.
- `python3 -m pytest` passes with 25 tests.
- `python3 scripts/run_suite.py` completes 12 dry-run scenarios.
- `python3 scripts/replay_call.py --call-id call-021` replays the interruption scenario and reproduces the same zero-issue evaluation with validation passing.
- Real telephony credentials, real recordings, and human-verified live-call notes are still pending.

## A/B experiment

- Ran `python3 scripts/run_experiment.py --config experiments/shorter_patient_turns/config.yaml`.
- Baseline (`prompt_v1_verbose`) average quality score: `97.67`.
- Candidate (`prompt_v2_concise`) average quality score: `99.0`.
- Baseline average patient words per turn: `12.4`.
- Candidate average patient words per turn: `7.42`.
- Result: the concise adaptive style won in dry-run mode, so the default patient behavior remains short and interruption-friendly going into live-call testing.

## Remaining limitations

- No live call artifacts have been created yet.
- Latency, interruption thresholds, and final voice style still need tuning against real recordings.
- `BUG_REPORT.md` should be treated as provisional until real-call evidence is reviewed.
