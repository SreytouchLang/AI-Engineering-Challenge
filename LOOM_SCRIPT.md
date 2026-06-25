# Loom Script

Use this as a read-aloud script for both required Loom videos. Keep each recording under five minutes.

Important honesty note:

- Do not claim that real calls exist unless they actually exist by recording time.
- Right now this repository is code-ready but still missing live-call evidence.
- If you record before real calls are completed, say clearly that any dry-run clip is an implementation preview only, not submission evidence.

## Main Walkthrough Script

### Recording goal

Show the project architecture, safeguards, artifact pipeline, tests, and current status honestly.

### Suggested spoken script

#### 0:00-0:35

“This repository is my Pretty Good AI voice-testing project. It is designed to call only the authorized challenge number, act as a fictional patient, capture artifacts, and evaluate call quality. At the moment, the code and validation pipeline are in place, but the repository is still waiting on real-call evidence, manual review, and Loom links before final submission can be marked ready.”

#### 0:35-1:20

“The core architecture is split into a few clear parts. In `app/telephony`, I handle call setup, callbacks, live-call preflight, and the media stream. In `app/voice`, I handle mu-law audio conversion, turn detection, speech-to-text, and text-to-speech. In `app/agent`, I keep the patient behavior and scenario logic. In `app/analysis`, I generate transcripts, validations, quality reports, and bug candidates. The live loop is Twilio stream to turn detection to STT to patient logic to TTS to artifact storage.”

#### 1:20-2:05

“One thing I prioritized was safety. In `app/safety.py`, the destination is hard-locked to `+1-805-439-8008`, and the system supports only one originating number. In `scripts/preflight_live_call.py`, I verify that real calls are explicitly enabled, credentials exist, the webhook is public and HTTPS, the WebSocket URL is derived correctly, the scenario is valid, the call ID is unique, recording is enabled, the duration and cost limits are safe, and the artifact directories are writable.”

#### 2:05-2:50

“For conversation quality, the patient side uses adaptive scenario planning instead of a fixed script. It can handle corrections, concise responses, interruption behavior, and scenario-specific goals. The media stream also tracks overlap, barge-in behavior, and latency metrics so I can evaluate how natural the interaction sounds once real calls are available.”

#### 2:50-3:35

“For artifacts, the project can fetch a provider recording, store the original safely, create the public recording artifact, generate a two-speaker transcript, validate both, and then build evaluation and bug-review outputs. The reporting path is intentionally strict: dry-run evidence is not treated as real-call evidence, and approved live-call bugs are required before the final bug report becomes submission-ready.”

#### 3:35-4:20

“For quality control, I can show the automated checks. The repository currently passes formatting, linting, type checking, scenario validation, and the full test suite. The test suite is now at 46 passing tests, including audio-path regression coverage, turn-taking tests, transcript validation tests, and scenario behavior tests.”

#### 4:20-5:00

“The current status is honest and simple: the code-level work is complete enough for a first approved smoke call, but the repository is still not submission-ready because it does not yet contain 10 provider-confirmed real calls, validated real-call recordings and transcripts, manual listening approvals, approved live-call bugs, Loom URLs, or final submission-form values. Those remaining steps all depend on real external evidence.”

### What to show on screen

1. `README.md`
2. `app/telephony/`
3. `app/voice/`
4. `app/agent/`
5. `app/analysis/`
6. `app/safety.py`
7. `scripts/preflight_live_call.py`
8. `LIVE_CALL_READINESS.md`
9. `SUBMISSION_GAP_REPORT.md`
10. `make submission-check` output or the generated summary docs

## AI Debugging Walkthrough Script

### Recording goal

Show a real example of using AI to diagnose and fix code, including the prompts, the reasoning, the patch, and the verification.

### Best current example in this repo

Use the `audioop` deprecation cleanup. It is real, code-based, and easy to explain:

- the old audio path depended on Python’s deprecated `audioop`
- the fix replaced it with local G.711 mu-law, PCM mixing, RMS, mono conversion, and linear resampling helpers
- regression tests were added in `tests/test_audio.py`
- the full suite still passes afterward

### Suggested spoken script

#### 0:00-0:30

“In this debugging example, I’m showing how I used AI to improve a real technical issue in the repository. The issue was that the audio pipeline depended on Python’s deprecated `audioop` module, which is scheduled for removal in Python 3.13. I wanted to remove that dependency without breaking the live voice path.”

#### 0:30-1:05

“First, I reproduced the problem by running the tests and locating every `audioop` usage in the codebase. The warning was coming from the audio helpers and the turn manager. I also checked where those helpers were used, because replacing codec and PCM logic carelessly could break transcription, playback timing, or mixing.”

#### 1:05-1:55

“Then I prompted AI to analyze the existing audio path before changing anything. I asked it to identify what `audioop` was doing in this project, what could be replaced locally, and what would need regression tests. The important part here is that I did not blindly accept a patch. I used AI to outline the safe replacement surface first: mu-law encode and decode, PCM mixing, mono downmixing, RMS, and simple resampling.”

#### 1:55-2:45

“Next, I asked AI for the smallest safe implementation strategy. The goal was not a large refactor. The goal was to preserve the current architecture while swapping out the deprecated dependency. The resulting change stayed focused in `app/voice/audio.py` and `app/voice/turn_manager.py`, and I added dedicated tests in `tests/test_audio.py` plus updated turn-manager tests.”

#### 2:45-3:40

“After that, I reran targeted tests first, then formatting, linting, type checking, and the full test suite. The targeted audio and turn-manager tests passed, and the full suite passed too. That gave me confidence that the new helpers were compatible with the rest of the system.”

#### 3:40-4:20

“Finally, I updated the documentation to reflect the new reality. The old limitation note said the project still relied on `audioop`, which was no longer true after the fix. I replaced that with a more accurate note: the project now uses local audio helpers, but a dedicated DSP stack would still be better for a long-lived production deployment.”

#### 4:20-5:00

“The main reason I like this example is that it shows disciplined AI use. I used AI to inspect the problem, propose a minimal fix, and help shape the regression tests, but I still verified the call sites, reviewed the logic, reran the checks, and kept the change narrowly scoped.”

### What to show on screen

1. `rg -n "audioop" .`
2. `app/voice/audio.py`
3. `app/voice/turn_manager.py`
4. `tests/test_audio.py`
5. `tests/test_turn_manager.py`
6. `README.md` limitation note
7. `make test`
8. `make submission-check`

## Prompts To Reuse In The AI Debugging Video

### Prompt 1 - Investigate

“This repository’s audio path still depends on Python’s deprecated `audioop` module. Please inspect the codec and turn-detection helpers and explain exactly what `audioop` is being used for here. Do not change code yet. I want a minimal replacement plan and the main regression risks.”

### Prompt 2 - Minimal design

“Propose the smallest safe change that removes `audioop` from this repository while preserving the existing architecture. Keep the live voice flow intact. Prioritize local helper replacements for mu-law conversion, PCM mixing, mono conversion, RMS, and resampling. Also list the tests we should add or update.”

### Prompt 3 - Implement

“Apply the minimal fix. Replace the deprecated `audioop` usage with local helper functions, update the turn manager to use them, and add focused regression tests. Avoid unrelated refactoring.”

### Prompt 4 - Verify

“Now review whether the new tests are actually strong enough. Do they verify codec round-tripping, downmixing, PCM mixing saturation, turn-manager behavior, and compatibility with the existing live-call audio path? If not, suggest the smallest additional test coverage.”

## Final Recording Tips

1. Keep the browser or editor zoomed in enough to read file names and prompts clearly.
2. Pause briefly after each prompt so the viewer can read it.
3. When you say “real calls are still pending,” keep that line in if no real-call evidence exists yet.
4. Keep both videos public or unlisted but accessible by link.
5. Paste the final Loom URLs into `LOOM_RECORDING_CHECKLIST.md`, `SUBMISSION_FORM_READY.md`, and `README.md` after upload.
