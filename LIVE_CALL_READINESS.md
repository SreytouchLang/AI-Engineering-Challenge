# Live Call Readiness

Audit date: 2026-06-24 (America/Los_Angeles)

Verified commands:

- `make format-check`
- `make lint`
- `make typecheck`
- `make test`
- `python scripts/preflight_live_call.py --scenario scenarios/01_simple_scheduling.yaml`

Current preflight summary:

- `call_id`: `call-025`
- `scenario`: `simple_scheduling`
- `ready`: `false`
- current blockers: `ENABLE_REAL_CALLS=false`, missing Twilio credentials, missing OpenAI credentials, missing `TELEPHONY_FROM_NUMBER`, missing `PUBLIC_BASE_URL`

| Component | Status | Evidence | Risk | Required fix |
| --------- | ------ | -------- | ---- | ------------ |
| Twilio credentials | Blocked by environment | `app/telephony/preflight.py` now checks `TELEPHONY_ACCOUNT_ID` and `TELEPHONY_AUTH_TOKEN`; current preflight reports them missing. | No live call can start. | Populate the Twilio account SID and auth token in `.env`. |
| Twilio originating number | Blocked by environment | `app/config.py` validates a single E.164 `TELEPHONY_FROM_NUMBER`; current preflight reports it missing. | Call creation will fail before dialing. | Configure exactly one Twilio voice number. |
| Authorized destination lock | Ready in code | `app/safety.py` hard-locks outbound calls to `+1-805-439-8008`; `scripts/run_call.py` and `app/telephony/client.py` use that validator. | Low; accidental dialing to another number is blocked. | None. Keep the constant unchanged. |
| Public HTTPS webhook | Blocked by environment | `app/telephony/preflight.py` requires `PUBLIC_BASE_URL`, HTTPS, and a `GET /health` response; current preflight reports it missing. | Twilio cannot reach status, recording, or media-stream callbacks. | Expose the app over HTTPS and set `PUBLIC_BASE_URL`. |
| WebSocket URL | Blocked by environment | `AppSettings.media_stream_url()` derives the `wss://.../telephony/media-stream` URL; current preflight reports it missing because the base URL is unset. | Bidirectional audio will never attach. | Set `PUBLIC_BASE_URL` to the externally reachable HTTPS origin. |
| TwiML response | Ready in code | `app/telephony/client.py` now builds TwiML with `<Connect><Stream ... /></Connect>` and URL-encoded query params. | Live behavior remains unverified until a real call runs. | No code fix pending. Verify on the first smoke call. |
| Bidirectional stream | Ready in code | `app/telephony/webhooks.py` accepts the media-stream WebSocket and routes it into `MediaStreamSessionRegistry`. | Provider-side behavior still needs one real call. | No code fix pending. Verify with the first approved call. |
| Incoming audio decoding | Ready in code | `app/telephony/media_stream.py` decodes base64 mu-law frames and stores agent PCM segments. | Unverified under real network jitter. | No code fix pending. Validate on the first call. |
| VAD | Ready in code | `app/voice/turn_manager.py` has typed turn tracking, adaptive end-of-turn silence, and passing tests in `tests/test_turn_manager.py`. | Thresholds may need tuning after listening to a real call. | Tune only after the first recording if needed. |
| STT | Code ready, env blocked | Live path uses `app/voice/stt.py`; transcript regeneration now supports channel-aware and diarized paths in `scripts/transcribe_call.py`. | Without keys, no transcription runs. Segment quality is still unverified on a real call. | Add `STT_API_KEY`; validate one real transcript end to end. |
| LLM patient response | Code ready, env blocked | `app/agent/patient_agent.py` uses adaptive planning and concise response shaping; live path depends on `LLM_API_KEY`. | Without the key, preflight blocks. Prompt quality still needs real-call tuning. | Add `LLM_API_KEY`; review the first real call for naturalness and coherence. |
| TTS | Code ready, env blocked | `app/voice/tts.py` now handles optional instructions safely and returns phone-ready mu-law. | Without the key, no patient audio can be generated. | Add `TTS_API_KEY`; verify voice clarity on the first smoke call. |
| Outgoing mu-law encoding | Ready in code | `app/voice/audio.py` converts WAV to 8 kHz mu-law and chunks outbound media for Twilio playback. | Real-call pacing still needs live verification. | No code fix pending. |
| Interruption handling | Ready in code | `app/telephony/media_stream.py` cancels playback on barge-in, tracks overlap, and logs interruption metrics; dry-run overlap test now exists. | Real interrupt timing may still need threshold tuning. | Verify with the interruption scenario after the smoke call passes. |
| Call timeout | Ready in code | `app/telephony/client.py` applies `time_limit`; preflight enforces maximum duration settings. | Wrong limits could still shorten or overrun calls if config is changed. | Keep `MAX_CALL_DURATION_SECONDS` within the current reviewed bounds. |
| Recording | Ready in code, unverified live | Call creation requests dual-channel recording; recording callbacks persist provider metadata in `app/telephony/webhooks.py`. | Provider-side recording delivery is not verified until the first real call. | Run one approved live call, confirm callback metadata, then fetch the audio. |
| Transcript | Ready in code, unverified live | Live media-stream transcripts are stored automatically, and `scripts/transcribe_call.py` can reuse or regenerate them from audio. | Transcript timing and speaker separation remain unverified on a real call. | Validate the first real transcript before batching more calls. |
| Artifact download | Ready in code, unverified live | `scripts/fetch_recording.py` waits for provider completion, downloads the recording with bounded retry, writes the original safely, copies the public MP3, and stores checksum/validation metadata. | No provider recording has been fetched yet. | Run the fetch step immediately after the first approved live call completes. |
| Cost protection | Ready in code | `app/telephony/preflight.py` and `app/safety.RunBudget` enforce `MAX_CALLS_PER_RUN`, `MONTHLY_COST_LIMIT_USD`, and `expected_cost_per_call_usd`. | Estimates could still differ from final provider billing. | Compare actual Twilio usage after the smoke call. |

Bottom line:

- The code path is now ready for a first approved smoke call.
- The remaining blockers are external and honest: credentials, a single Twilio originating number, an HTTPS webhook/tunnel, and the user's explicit approval before dialing.
