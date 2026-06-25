# Voice Simulator Bug Report

Generated: 2026-06-25

Findings from the free two-AI voice simulator. Each conversation was synthesized to real audio and transcribed; listen at the cited timestamp in the matching recording to reproduce.

Calls evaluated: 12 | Total findings: 2

## [HIGH] Agent repeated incorrect patient identity after a correction

- **Call:** call-012 at 00:08.0
- **Category:** context retention
- **Recording:** artifacts/recordings/call-012-mixed.mp3
- **What happened:** Maria, what day works best for you?
- **Expected:** Retain the corrected identity information for the rest of the call.
- **Why it matters:** Identity errors undermine trust and can create workflow mistakes.

## [MEDIUM] Call ended without a clear final confirmation

- **Call:** call-010 at 00:33.2
- **Category:** workflow
- **Recording:** artifacts/recordings/call-010-mixed.mp3
- **What happened:** Just confirming, the visit is now knee pain on Wednesday, July 16 at 2:00 PM.
- **Expected:** Summarize the final outcome before ending the call.
- **Why it matters:** The patient may leave unsure whether the requested action was completed.

