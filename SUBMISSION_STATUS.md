# Submission Status

Audit date: 2026-06-23 (America/Los_Angeles)

| Requirement | Status | Evidence | Missing Action |
|---|---|---|---|
| Public repository accessible | Complete | Anonymous `curl -I https://github.com/SreytouchLang/AI-Engineering-Challenge` returned `HTTP/2 200` on 2026-06-24 UTC. | None for repository visibility itself. Public artifact publication is still pending below. |
| 10 real calls | Incomplete | `artifacts/call_metadata/` contains 24 local call JSON files (`call-001` through `call-024`), but audited metadata samples (`call-001`, `call-012`, `call-013`, and `call-024`) all show `"mode": "dry_run"` and `"provider_call_id": null`. No live-call metadata was found. | After explicit approval, place and validate at least 10 provider-confirmed live calls. |
| MP3/OGG for every real call | Incomplete | `artifacts/recordings/` contains 12 local mixed MP3s (`call-013` through `call-024`) plus agent/patient WAV channel files. No verified live-call recording set exists. The generated recording files are ignored by `.gitignore`, so they are not public in GitHub. | Capture MP3 or OGG for every selected live call and intentionally publish those artifacts. |
| Transcript with both speakers for every real call | Incomplete | `artifacts/transcripts/` contains 24 local `.txt` and 24 local `.json` transcripts, but they correspond to dry runs and are ignored by `.gitignore`. No real-call transcript set is verified or public. | Generate timestamped transcripts for selected live calls, verify both speakers, and publish the selected transcript set. |
| Bug report cites approved live-call findings | Incomplete | `BUG_REPORT.md` contains two issues from `call-022` and `call-024`; both audited calls are dry runs, and both entries still say `Human Review: pending`. | Replace provisional dry-run findings with human-approved live-call findings only. |
| Recordings were manually checked for natural conversation quality | Incomplete | No committed manual review workflow or reviewer sign-off file exists yet. | Create the manual listening checklist, review each selected call end to end, and record reviewer name, date, notes, and decision. |
| Submission form information is ready | Incomplete | README Loom entries are `TBD`, the originating number is not populated in a submission document, and no final selected-call roster exists. | Fill `SUBMISSION_FORM_READY.md` after final call selection, public artifact publication, and Loom upload. |

## Current Repository Structure

- Application code lives under `app/` with `agent/`, `analysis/`, `experiments/`, `review/`, `storage/`, `telephony/`, and `voice/`.
- Scenario definitions live under `scenarios/` and currently cover 12 challenge-style flows.
- Operational scripts live under `scripts/`.
- Tests live under `tests/`.
- Experiment outputs live under `experiments/shorter_patient_turns/`.
- Repository docs currently include `README.md`, `ARCHITECTURE.md`, `SCENARIOS.md`, `ITERATION_LOG.md`, `LOOM_SCRIPT.md`, and `BUG_REPORT.md`.
- Local generated artifacts live under `artifacts/` with `call_metadata/`, `recordings/`, `transcripts/`, `evaluations/`, `validation/`, and `quality/`.

## Existing Calls And Artifacts

- 24 local call IDs exist: `call-001` through `call-024`.
- The 24 calls are two local passes across the 12 scenario set:
  - Pass 1: `call-001` through `call-012`
  - Pass 2: `call-013` through `call-024`
- Each pass covers the same 12 scenario IDs: `simple_scheduling`, `reschedule_visit`, `cancel_appointment`, `medication_refill`, `office_hours_location`, `insurance_verification`, `weekend_scheduling`, `ambiguous_concern`, `interruption_barge_in`, `context_change_mid_call`, `urgent_symptom_escalation`, and `repetition_recovery`.
- Local artifact counts:
  - 24 call metadata JSON files
  - 24 evaluation JSON files
  - 24 transcript `.txt` files
  - 24 transcript `.json` files
  - 12 mixed MP3 recordings
  - 24 channel WAV recordings
  - 12 validation JSON files and 12 validation Markdown files
  - 12 quality JSON files and 12 quality Markdown files
- Real-call evidence found during this audit: none verified.
- Audited metadata samples show:
  - `"provider_call_id": null`
  - `"mode": "dry_run"`
  - `"submission_ready": false` where that field exists

## Existing Evaluations And Bug Reports

- Structured evaluation files exist locally for all 24 call IDs under `artifacts/evaluations/`.
- Transcript-validation and voice-quality reports exist locally for `call-013` through `call-024`.
- `BUG_REPORT.md` currently contains two provisional findings:
  - `BUG-001` on `call-022`
  - `BUG-002` on `call-024`
- Neither finding is submission-ready because both rely on dry-run calls and both still show `Human Review: pending`.

## Missing Artifacts

- No provider-confirmed live-call metadata
- No verified live-call recordings
- No verified live-call transcripts
- No committed/public call artifacts for the current bug-report links
- No final selected-call list
- No manual call-review checklist with completed reviewer fields
- No submission-form readiness document yet
- No public Loom URLs yet

## Broken Links And Placeholder Content

- `README.md` still lists both Loom links as `TBD`.
- `BUG_REPORT.md` links to `artifacts/...` files that are ignored by Git.
- Public repository root access is working, but public artifact access is not. Example: anonymous `curl -I` to `https://raw.githubusercontent.com/SreytouchLang/AI-Engineering-Challenge/main/artifacts/transcripts/call-022.txt` returned `HTTP/2 404`.
- `BUG_REPORT.md` itself is public, so the current public repo exposes issue writeups whose linked evidence files are missing from GitHub.

## Uncommitted Secrets And Sensitive Data Audit

- `.env` is not tracked. `git ls-files '.env*'` returned only `.env.example`.
- `.env.example` contains placeholders only and no populated credentials.
- A quick secret-pattern sweep found no apparent committed live API keys, tokens, or private keys.
- One fake `sk-...` token appears in `tests/test_number_guard.py` as intentional test data.
- Sampled call transcripts use fictional patient information.

## Generated Files That Should Not Be Public

- Local cache and build leftovers are present under `.pytest_cache/`, `__pycache__/`, and `tmp/`; these are correctly ignored.
- Current generated call artifacts are also ignored by `.gitignore`. That is appropriate for dry-run churn, but it also means the current public repo does not actually include the evidence files referenced by the bug report.

## Exact Remaining Actions

1. Decide how selected submission artifacts will become public: commit them directly, use Git LFS, or publish them from another durable public location and update links accordingly.
2. Add the Phase 2 validation workflow for distinguishing provider-confirmed live calls from local dry runs on every future call ID.
3. After explicit approval, place and verify at least 10 real calls against the authorized number using the single configured originating number.
4. For every selected live call, keep metadata, recording, transcript, validation output, and evaluation output together under the same stable call ID.
5. Create the manual listening review workflow and collect completed reviewer sign-off before selecting final calls.
6. Rebuild `BUG_REPORT.md` from approved live-call findings only.
7. Populate the submission-form fields after the repository contains public evidence links and final Loom URLs.
