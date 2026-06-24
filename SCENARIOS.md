# Scenario Suite

The repository ships with 12 structured YAML scenarios under `scenarios/`. Each scenario defines the patient persona, desired outcome, disclosure rules, and evaluation expectations so the same data can drive dry runs, live calls, and offline analysis.

The categories cover routine scheduling, rescheduling, cancellation, medication refill, office information, insurance verification, weekend availability, ambiguous health concerns, interruption recovery, mid-call context changes, safety escalation, and correction retention. The dry-run simulator uses these files directly, and the live path loads them by `scenario_id` before a call starts.
