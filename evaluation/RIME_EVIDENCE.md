# RIME_EVIDENCE.md
# ----------------
# Evidence document for the Rime Hackathon submission.
# Per blueprint § 13 and submission checklist § 15, this file must contain:
#   - The hard voice claim
#   - Acceptance test procedure, result, and limitations for each test
#   - A repeatable script / fixture
#
# Fill in each section as tests are completed. Sections marked [TODO] are
# stubs to be completed during the build sprints.

---

# Hard Voice Claim

Continuum delivers a spoken, private recap into the user's earpiece **during the ring window** — before they answer a returning call — using **Rime TTS** as the sole spoken output on a **separate LiveKit audio track** that the caller never hears.

This directly addresses two hackathon hard-problem paths:
1. **Interruption and Recovery** — the system detects abrupt call drops and reconnects.
2. **Conversation Continuity During Tool Work** — the Fact-Freshness Checker re-verifies time-sensitive facts via a live data source before speaking them.

---

# Rime Configuration

| Parameter | Value |
|-----------|-------|
| Model | `coda` (default) / `mist_v2` (per-word speed control) / `mist_v3` (spell() grouping) |
| Speaker | `sol` (verify against live catalog before submission) |
| Language | `en` |
| Endpoint | Regional endpoint closest to LiveKit deployment |
| Transport | LiveKit Rime plugin (streaming) |
| Audio format | Default Rime streaming format via LiveKit |
| `timeScaleFactor` | `0.85` for connective filler |
| `inlineSpeedAlpha` | Applied to numbers/facts (e.g. `[four hundred twenty dollars]`) |
| `spell()` | Applied to ticket IDs, account numbers, confirmation codes |

---

# Acceptance Tests

## Test 1 — Pre-Answer Latency

**Procedure:** Force-disconnect a live call mid-sentence; force Z to call back; measure time from first ring event to first audible Rime TTS word on the private track.

**Pass criterion:** Recap begins within the first 1–2 rings (≤ 5 seconds).

**Result:** [TODO — complete in Day 4 sprint]

**Artifact:** `evaluation/artifacts/latency_result.json`

**Limitations:** [TODO]

---

## Test 2 — Zero Impact on Caller Audio

**Procedure:** Record the audio Z actually hears during the entire reconnect + recap window. Inspect for any recap audio content.

**Pass criterion:** Z's audio is indistinguishable from an ordinary ringback-then-answer call; no recap audio detected on the caller-facing track.

**Result:** [TODO — complete in Day 4 sprint]

**Artifact:** `evaluation/artifacts/caller_audio_inspection.json`

**Limitations:** [TODO]

---

## Test 3 — Context Fencing

**Procedure:** Run two simulated threads (Z and a second contact Y) in parallel. Trigger a recap for Z. Inspect recap text for any content from Y's thread.

**Pass criterion:** Zero cross-thread keyword leakage.

**Result:** [TODO — complete in Day 4 sprint]

**Artifact:** `evaluation/artifacts/context_fencing.json`

**Limitations:** [TODO]

---

## Test 4 — Freshness Catch ✅ (mock-runnable)

**Procedure:** Thread Memory Store holds `price_usd = $400`. Mock API updated to return `$420`. Trigger freshness check. Verify recap flags the discrepancy.

**Pass criterion:** Spoken recap states both the old value ($400) and the new value ($420) correctly. `FreshnessStatus.CHANGED` detected.

**Result:** PASS (mock run — `evaluation/artifacts/freshness_catch.json`)

**Repeatable script:**
```bash
USE_MOCKS=true pytest evaluation/test_freshness_catch.py -v
```

**Limitations:** Mock API only; full test with live data source pending Pair D implementation.

---

## Test 5 — Interruptibility

**Procedure:** Stream a recap to the private track. Simulate user voice activity (barge-in) at t+2s. Measure time from VAD trigger to audio silence.

**Pass criterion:** Audio stops within 500ms; no orphaned audio continues.

**Result:** [TODO — complete in Day 4 sprint]

**Artifact:** `evaluation/artifacts/interruptibility.json`

**Limitations:** [TODO]

---

## Test 6 — Fallback Whisper Channel

**Procedure:** Simulate instant-connect call (no ring buffer). User invokes assistant mid-call. Verify whisper is on private track only.

**Pass criterion:** Rime audio audible only on user-private track; no audible artifact on caller-facing track.

**Result:** [TODO — complete in Day 4 sprint]

**Artifact:** `evaluation/artifacts/fallback_whisper.json`

**Limitations:** [TODO]

---

# Repeatable Fixture

```bash
# 1. Copy env and fill in credentials
cp .env.example .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the mock freshness API
python -m mocks.mock_freshness &

# 4. Run all evaluation tests (mocks only)
USE_MOCKS=true pytest evaluation/ -v

# 5. To trigger the "changed value" fixture for freshness demo:
curl -X POST http://localhost:8001/facts/price_usd \
     -H "Content-Type: application/json" \
     -d '{"value": "$420"}'
```
