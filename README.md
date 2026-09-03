# Continuum

> **A voice-native conversation continuity assistant — whispered recaps that catch you up before you ever say "hello."**

Continuum is a [Rime Hackathon](https://rime.ai) submission targeting two hard-problem paths:
- **Interruption & Recovery** — detects abrupt call drops, matches the returning caller, and delivers a spoken recap before the user answers.
- **Conversation Continuity During Tool Work** — re-verifies time-sensitive facts against a live data source before speaking them, flagging any discrepancy.

---

## How It Works

```
Incoming call (Z calls back)
        │
        ▼ RINGING — ring window opens (~15–25s)
┌─────────────────────────────────────────────────┐
│  Caller hears: normal ringback tone             │
│  User hears:  "Z wanted the Q3 number.         │
│               Heads up — price is now $420."   │  ← Rime TTS on private track
└─────────────────────────────────────────────────┘
        │
        ▼ User answers — already caught up
```

The recap is delivered on a **separate, private LiveKit audio track** that the caller never hears. This adds **zero latency** to the caller's experience.

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full pipeline diagram.

```
Audio → Transcript → Memory → Recap Text → Speech → Private Track
 (A)       (B)         (C)        (C)          (D)        (A)
```

| Pair | Modules | Tech |
|------|---------|------|
| A — Transport | Call Session Manager + Private Whisper Channel | LiveKit Agents, SIP |
| B — Signal | Streaming STT + Disconnect/Reconnect Detector | Deepgram, LiveKit |
| C — Brain | Thread Memory Store + Recap Generator | SQLite/Postgres, Gemini LLM |
| D — Voice & Facts | Fact-Freshness Checker + Rime TTS Delivery | FastAPI mock API, Rime |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Realtime transport | [LiveKit Agents](https://docs.livekit.io/agents/) |
| Telephony | LiveKit SIP / Twilio SIP trunk |
| Speech-to-Text | [Deepgram](https://deepgram.com) streaming (LiveKit plugin) |
| **Text-to-Speech** | **[Rime](https://rime.ai) — Coda / Mist v2 / Mist v3** |
| LLM | Gemini 2.0 Flash (fast) + Gemini 2.5 Pro (strong reasoning) |
| Memory | SQLite (hackathon) / Postgres (production) |
| Mock data API | FastAPI |
| Frontend | React dashboard |
| Language | Python 3.11+ |

> Rime is the **only** spoken output provider in the judged path. No other TTS library is used.

---

## Rime Integration

| Parameter | Value |
|-----------|-------|
| Model | `coda` (expressive default) / `mist_v2` / `mist_v3` |
| Speaker | `sol` (see live catalog at submission time) |
| Endpoint | Regional — nearest to LiveKit deployment |
| `timeScaleFactor` | `0.85` — speeds up connective filler in the recap |
| `inlineSpeedAlpha` | Applied to numbers/facts for clarity |
| `spell()` | Wraps ticket IDs, account numbers, confirmation codes |

**Voices are verified against the live catalog** (`users.rime.ai/data/voices/all-v2.json`) at build time, not hard-coded from a stale list.

---

## Setup

### Prerequisites

- Python 3.11+
- A [Rime API key](https://rime.ai)
- A [LiveKit Cloud](https://cloud.livekit.io) account (or self-hosted LiveKit)
- A [Deepgram](https://deepgram.com) API key

### Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/raunakprajapatii/Continuum.git
cd Continuum

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and fill in your API keys

# 4. Start the mock freshness API (separate terminal)
python -m mocks.mock_freshness

# 5. Run with mocks (no external services needed)
USE_MOCKS=true python -m modules.transport.main

# 6. Run evaluation tests
USE_MOCKS=true pytest evaluation/ -v
```

### Environment Variables

See [`.env.example`](.env.example) for all required and optional variables.

Key variables:

| Variable | Description |
|----------|-------------|
| `RIME_API_KEY` | **Required.** Your Rime API key. |
| `LIVEKIT_URL` | LiveKit Cloud WebSocket URL. |
| `LIVEKIT_API_KEY` | LiveKit API key. |
| `LIVEKIT_API_SECRET` | LiveKit API secret. |
| `DEEPGRAM_API_KEY` | Deepgram streaming STT key. |
| `USE_MOCKS` | `true` to run without external services (local dev). |

---

## Repository Structure

```
continuum/
├── shared/
│   ├── schemas/          # Typed Pydantic contracts between pairs (owned by all)
│   └── config/           # Environment-driven settings
├── modules/
│   ├── transport/        # Pair A — LiveKit session + private whisper channel
│   ├── signal/           # Pair B — Streaming STT + disconnect/reconnect detector
│   ├── brain/            # Pair C — Thread memory store + recap generator
│   └── voice/            # Pair D — Fact-freshness checker + Rime TTS delivery
├── mocks/                # Stub implementations for local development
├── evaluation/           # Acceptance tests + RIME_EVIDENCE.md
├── docs/
│   └── ARCHITECTURE.md   # Full pipeline diagram and module breakdown
├── AGENTS.md             # Antigravity agent guardrails
├── CODEOWNERS            # PR review assignments
├── .env.example          # Environment variable template (no credentials)
├── requirements.txt
└── pyproject.toml
```

---

## Running the Evaluation Tests

```bash
# All tests (mocks only)
USE_MOCKS=true pytest evaluation/ -v

# Freshness catch test only (no mocks needed — runs purely on schemas)
pytest evaluation/test_freshness_catch.py -v

# To demonstrate the stale-fact scenario:
# 1. Start the mock API: python -m mocks.mock_freshness
# 2. Change the price:   curl -X POST http://localhost:8001/facts/price_usd -d '{"value":"$420"}'
# 3. Run the test:       pytest evaluation/test_freshness_catch.py -v
```

See [`evaluation/RIME_EVIDENCE.md`](evaluation/RIME_EVIDENCE.md) for acceptance test results and evidence clips.

---

## Known Limitations

- **Consent & privacy:** Recording third-party calls without disclosure is a legal concern in many jurisdictions. This demo uses synthetic/de-identified scripts only. A production version would require a recorded-line disclosure, opt-out mechanism, and data retention limits.
- **SIP telephony setup:** The fiddliest part of the stack. If LiveKit SIP setup is incomplete for the demo, the system falls back to a browser-simulated ring state (disclosed as a limitation in RIME_EVIDENCE.md).
- **Ring window duration:** Varies by carrier (typically 15–25 seconds). The system front-loads the headline sentence so even a 5-second window delivers value.
- **Speaker diarization:** Deepgram streaming diarization is not perfect on overlapping speech; the system tags ambiguous turns as `UNKNOWN`.
- **Fallback TTS:** There is no silent Rime fallback. If Rime is unavailable, the system surfaces an error rather than substituting another TTS provider, per hackathon rules.

---

## Third-Party Services

| Service | Purpose | Required |
|---------|---------|----------|
| [Rime](https://rime.ai) | Text-to-speech (sole spoken output) | Yes |
| [LiveKit](https://livekit.io) | Realtime audio transport, multi-track rooms | Yes |
| [Deepgram](https://deepgram.com) | Streaming speech-to-text | Yes (or AssemblyAI) |
| [Google Gemini](https://ai.google.dev) | LLM for recap generation + freshness reasoning | Yes (or Anthropic Claude) |

---

## Hackathon Submission

- **Demo:** 4–5 minute recording (see submission checklist)
- **Evidence:** [`evaluation/RIME_EVIDENCE.md`](evaluation/RIME_EVIDENCE.md)
- **Checklist:** Blueprint § 15 (Submission Checklist)

Built for the **Rime Hackathon** — Interruption & Recovery · Conversation Continuity paths.
