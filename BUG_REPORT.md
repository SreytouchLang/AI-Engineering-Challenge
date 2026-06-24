# Bug Report

## Executive Summary

- Calls completed: 12
- Scenarios tested: 12
- High-severity issues: 1
- Medium-severity issues: 1
- Low-severity issues: 0
- Most important finding: Call ended without a clear final confirmation


## BUG-001: Call ended without a clear final confirmation

**Severity:** Medium  
**Category:** workflow  
**Call:** `call-022`  
**Scenario:** `context_change_mid_call`  
**Transcript:** [call-022.txt](artifacts/transcripts/call-022.txt)  
**Recording:** [call-022-mixed.mp3](artifacts/recordings/call-022-mixed.mp3)  
**Timestamp:** 00:28.6  
**Human Review:** pending  

### What happened

Just confirming, the visit is now knee pain on Wednesday, July 16 at 2:00 PM.

### Why it matters

The patient may leave unsure whether the requested action was completed.

### Expected behavior

Summarize the final outcome before ending the call.

### Evidence

Just confirming, the visit is now knee pain on Wednesday, July 16 at 2:00 PM.

### Reproduction steps

1. Run the scenario associated with this call.
2. Listen at the cited timestamp and compare it against the transcript.
3. Confirm whether the agent repeats the same behavior.

## BUG-002: Agent repeated incorrect patient identity after a correction

**Severity:** High  
**Category:** context retention  
**Call:** `call-024`  
**Scenario:** `repetition_recovery`  
**Transcript:** [call-024.txt](artifacts/transcripts/call-024.txt)  
**Recording:** [call-024-mixed.mp3](artifacts/recordings/call-024-mixed.mp3)  
**Timestamp:** 00:06.5  
**Human Review:** pending  

### What happened

Maria, what day works best for you?

### Why it matters

Identity errors undermine trust and can create workflow mistakes.

### Expected behavior

Retain the corrected identity information for the rest of the call.

### Evidence

Maria, what day works best for you?

### Reproduction steps

1. Run the scenario associated with this call.
2. Listen at the cited timestamp and compare it against the transcript.
3. Confirm whether the agent repeats the same behavior.
