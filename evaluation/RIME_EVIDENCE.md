# RIME_EVIDENCE.md
================

Evidence document for the **Continuum** Rime Hackathon submission.
This file documents the hard voice engineering claim, the acceptance test procedure, measured results, reproducible fixtures, and explicit limitations per the Rime Hackathon Problem Statement (§ 13 & § 15).

---

## 1. Hard Voice Claim

Continuum delivers a spoken, private recap into the user's earpiece **during the ring window** — before they answer a returning call — using **Rime TTS** as the sole spoken output on a **separate, private LiveKit audio track** that the caller never hears.

This directly addresses two core hackathon hard-problem paths:
1. **Interruption and Recovery**: Detects abrupt call drops and reconnects, synthesizes thread memory, and delivers a whispered recap before the call is answered.
2. **Conversation Continuity During Tool Work**: The Fact-Freshness Checker re-verifies time-sensitive facts against live enterprise data before speaking them, flagging any overnight or mid-conversation price changes.

---

## 2. Rime Production Configuration

All spoken output in the judged recap path uses Rime TTS:

| Parameter | Shipped / Production Value |
|-----------|----------------------------|
| **Model** | `coda` (expressive default) / `mist_v2` / `mist_v3` |
| **Speakers** | `sol` (default catalog reference) · `eyre` (English recap) · `nadi` (Hinglish/Hindi recap) |
| **Language** | `en` (English) / `hi` (Latin-script Romanized Hinglish) |
| **Endpoint** | `https://users.rime.ai/v1/rime-tts` (regional endpoints nearest to deployment) |
| **Transport** | LiveKit Agents Rime streaming plugin (`livekit-plugins-rime`) + Direct HTTP Chunked Audio (`dashboard/server.py`) |
| **Audio Format** | `pcm_24000` (LiveKit audio frame pipeline) / `audio/mp3` (browser whisper audio) |
| **Speed / Prosody** | `timeScaleFactor: 0.78` – `0.85` (accelerates conversational filler while maintaining clarity) |
| **Number / Fact Normalization** | `inlineSpeedAlpha` applied to prices and quantities |
| **Alphanumeric Code Wrapping** | `spell(...)` applied to ticket IDs, SKUs, and account numbers |

> **Catalog Hygiene**: Speaker IDs are validated against Rime's live production catalog (`https://users.rime.ai/data/voices/all-v2.json`) rather than hardcoded lists.

---

## 3. Acceptance Tests & Measured Results

Every claim is backed by automated, reproducible evaluation tests in `evaluation/`:

| # | Acceptance Test | Test Procedure | Pass Criterion | Measured Result | Status | Artifact File |
|---|-----------------|----------------|----------------|-----------------|--------|---------------|
| **1** | **Pre-Answer Latency** | Disconnect call, trigger reconnect, measure time from `CallState.RINGING` to first audio byte on private track | $\le 5.0\text{ s}$ ($\approx 2$ rings) | **< 0.01 s** (mock) / **1.14 s** (live pipeline) | **PASS** | `evaluation/artifacts/latency_result.json` |
| **2** | **Zero Impact on Caller (Dual-Track Isolation)** | Synthesize recap to `private_track_id`; inspect `caller_facing_track_id` for audio energy and byte leakage | 0 bytes leaked; strict track separation; exception on violation | **0 bytes leaked** (`TrackFencingViolationError` enforced) | **PASS** | `evaluation/artifacts/caller_audio_inspection.json` |
| **3** | **Context Fencing** | Run simultaneous threads (Contact Z and Contact Y); inspect Z's recap for Y keywords | 0 keyword leakage between threads | **0 keyword leaks** | **PASS** | `evaluation/artifacts/context_fencing.json` |
| **4** | **Fact Freshness Catch** | Seed call price at $400; update live enterprise API to $420; generate recap | Status = `CHANGED`; speaks old and new value early | **"Heads up — Unit price was $400, it's now $420"** | **PASS** | `evaluation/artifacts/freshness_catch.json` |
| **5** | **Interruptibility (Barge-In)** | User triggers mic / speaks during active recap playback | TTS stops promptly ($\le 500\text{ ms}$); no zombie audio | **0.09 ms stop latency** | **PASS** | `evaluation/artifacts/interruptibility.json` |
| **6** | **Fallback Whisper & Ducking** | Direct answer with zero ring window; user triggers mid-call catchup | Private track whisper; caller audio ducked 25%, recap boosted 125% | **Ducking active; 0 caller track leak** | **PASS** | `evaluation/artifacts/fallback_whisper.json` |

---

## 4. Test Procedures & Logs

### Test 1 — Pre-Answer Latency (`evaluation/test_pre_answer_latency.py`)
- **Procedure**: Simulates call disconnection followed by an incoming callback from the matched contact. Times the transition from `RINGING` state to the generation of the first TTS chunk.
- **Result**: Average latency well below the typical 15–25 second carrier ring window.

### Test 2 — Dual-Track Invariant (`evaluation/test_zero_caller_impact.py`)
- **Procedure**: Verifies that Rime audio frames are routed exclusively to `settings.private_track_id`. Tests that any simulated attempt to mix or cross-route recap audio into the caller track raises a fatal `TrackFencingViolationError`.
- **Result**: 0 bytes leaked onto caller-facing track. Caller hears only standard ringback tone.

### Test 3 — Context Fencing (`evaluation/test_context_fencing.py`)
- **Procedure**: Injects concurrent active call records for Contact Z (copper / basmati contracts) and Contact Y (unrelated medical consultation). Validates that thread extraction preserves strict caller entity separation.
- **Result**: Exact match on contact ID and zero topic cross-contamination.

### Test 4 — Freshness Catch (`evaluation/test_freshness_catch.py`)
- **Procedure**: Contact discussed price at $400 yesterday. Overnight market shift updates enterprise catalog to $420. Recap text generator queries live freshness service before audio synthesis.
- **Result**: `FreshnessStatus.CHANGED` correctly flagged. Synthesizes warning conforming to Rime Prompt Rule 5: *"Heads up — Unit price was $400, it's now $420 as of this morning."*

### Test 5 — Barge-In / Interruption (`evaluation/test_interruptibility.py`)
- **Procedure**: Plays Rime audio stream while injecting user barge-in event (*"call utha lo"* / *"stop, I remember"*). Measures time to abort audio buffer and fence downstream synthesis.
- **Result**: Playback halted in `< 1ms` in simulation, immediate teardown of active stream.

### Test 6 — Mid-Call Whisper & Priority Ducking (`evaluation/test_fallback_whisper.py`)
- **Procedure**: When a call is picked up immediately without a ring window, user can whisper a status query. Validates that LiveKit priority ducking attenuates the incoming caller audio to 25% while playing the recap at 125% on the private channel only.
- **Result**: Dual-track isolation maintained; caller is unaware of whispered briefing.

---

## 5. Known Limitations & Disclosures

1. **Carrier Ring Windows**: Carrier ring durations vary between 15 and 25 seconds before voicemail. If a user answers within 2 seconds, Continuum gracefully switches to mid-call whisper with caller audio ducking.
2. **Telephony SIP Setup**: LiveKit SIP trunks depend on carrier network connectivity. When SIP trunking is unavailable in local/test environments, Continuum provides browser-simulated WebRTC ring states.
3. **Consent and Wiretapping Disclosures**: Continuous call summarization in production environments requires two-party consent or audible recording notifications in compliance with jurisdiction-specific telecom regulations.
4. **Speech Diarization Overlap**: High ambient crosstalk during the initial call can introduce uncertainty in turn attribution. Ambiguous turns are classified as `speaker: UNKNOWN` and deprioritized in the recap headline.
5. **No Silent TTS Fallback**: Per hackathon rules, if Rime is unavailable or unconfigured, Continuum raises an explicit observable error rather than silently substituting browser `speechSynthesis` or other engines.

---

## 6. Reproducible Execution Commands

All tests and fixtures can be executed locally without live API keys using the built-in mocks, or with live keys using the production pipeline:

```bash
# 1. Run all 65 acceptance and unit tests (100% PASS)
USE_MOCKS=true pytest evaluation/ -v

# 2. Run the specific hard-voice acceptance tests
pytest evaluation/test_pre_answer_latency.py -v
pytest evaluation/test_zero_caller_impact.py -v
pytest evaluation/test_context_fencing.py -v
pytest evaluation/test_freshness_catch.py -v
pytest evaluation/test_interruptibility.py -v
pytest evaluation/test_fallback_whisper.py -v

# 3. Run the interactive Transport CLI scenario
USE_MOCKS=true python -m modules.transport.main --scenario reconnect --ducking

# 4. Run the full live interactive web simulation
# Terminal 1:
USE_MOCKS=false uvicorn dashboard.server:app --port 8000
# Terminal 2:
cd web && pnpm dev
```
