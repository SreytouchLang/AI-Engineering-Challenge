PYTHON ?= python3

.PHONY: install test serve dry-run call suite analyze report replay experiment preflight validate-scenarios validate-recordings validate-transcripts live-progress rank-calls submission-check

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest

serve:
	$(PYTHON) -m uvicorn app.main:app --reload

dry-run:
	$(PYTHON) scripts/run_call.py --dry-run --scenario $(SCENARIO)

call:
	ENABLE_REAL_CALLS=true $(PYTHON) scripts/run_call.py --scenario $(SCENARIO) --confirm-live-call=$(CONFIRM_REAL_CALL)

suite:
	$(PYTHON) scripts/run_suite.py

analyze:
	$(PYTHON) scripts/analyze_call.py --call-id $(CALL_ID)

report:
	$(PYTHON) scripts/build_report.py --review

replay:
	$(PYTHON) scripts/replay_call.py --call-id $(CALL_ID)

experiment:
	$(PYTHON) scripts/run_experiment.py --config $(CONFIG)

preflight:
	$(PYTHON) scripts/preflight_live_call.py --scenario $(SCENARIO)

validate-scenarios:
	$(PYTHON) scripts/validate_scenarios.py

validate-recordings:
	$(PYTHON) scripts/validate_recordings.py

validate-transcripts:
	$(PYTHON) scripts/validate_transcripts.py

live-progress:
	$(PYTHON) scripts/summarize_live_calls.py

rank-calls:
	$(PYTHON) scripts/rank_calls.py

submission-check:
	$(PYTHON) scripts/submission_check.py
