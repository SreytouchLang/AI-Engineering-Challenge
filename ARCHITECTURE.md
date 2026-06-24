# Architecture

The system is designed around a narrow, testable voice loop rather than a large orchestration layer. Twilio places the outbound call to the locked assessment number, records the call, and forwards live audio to FastAPI over a bidirectional media stream. The server detects end-of-turn boundaries locally, sends each office turn through STT, runs the patient controller with compact state plus recent context, synthesizes a short patient reply, and returns phone-ready mu-law audio to Twilio. Every step writes artifacts so recordings, transcripts, metadata, and evaluations stay tied to the same call id.

Evaluation is intentionally separate from the live conversation path. The patient agent focuses only on sounding consistent and goal-directed during the call, while the offline evaluator consumes finished transcripts later to score workflow, factual consistency, safety, and user experience. That separation keeps the live loop faster, reduces prompt complexity, and makes bug reporting auditable because every reported issue points back to a saved transcript and call artifact.

## Tradeoffs

- Request-based STT and TTS are simpler to debug than a full speech-to-speech bridge, but they trade some latency for operational clarity.
- Local turn detection keeps interruption logic deterministic, but it still needs real-call tuning against actual phone audio conditions.
- The dry-run simulator makes the repo runnable without credentials, but it is only a harness for development and not a substitute for live challenge evidence.

