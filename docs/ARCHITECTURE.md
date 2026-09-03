# Continuum — Architecture

> Condensed from the project blueprint (§ 06 & § 07). Read this before touching any module.

## System Overview

Continuum is a voice-native conversation continuity assistant. Its core mechanic:

> **Deliver a whispered recap into the user's ear during the ring window — before they answer — so the caller experiences only normal ringback and the user is already caught up.**

---

## Pipeline

```
Telephony / SIP trunk
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│       LiveKit Agents Session                                         │
│  (realtime transport, VAD, dual audio tracks)                        │
│                                                                      │
│   caller-facing track ◄──────────────────────────── never touched   │
│   user-private track  ◄── Rime TTS recap audio ONLY                 │
└─────────────────────────────────────────────────────────────────────┘
        │                          │
        ▼                          ▼
  [Pair A: Transport]       [Pair A: Transport]
  Call Session Manager      Private Whisper Channel
        │                          ▲
        │ CallStateEvent            │ TtsRequest
        ▼                          │
  [Pair B: Signal]          [Pair D: Voice & Facts]
  Streaming STT             Rime TTS Delivery
  Disconnect/Reconnect      Fact-Freshness Checker
  Detector                          ▲
        │                          │ RecapRequest
        │ TranscriptEvent           │
        ▼                          │
  [Pair C: Brain]  ───────────────►┘
  Thread Memory Store
  Recap Generator (LLM)
```

**Data flow**: A → B → C → D → A (recap audio loops back to Transport's private track)

---

## The One Non-Negotiable Invariant

> **The caller-facing audio path and the user-private audio path must be architecturally separate tracks in the same LiveKit room — not a single mixed track.**

This is tested in `evaluation/test_zero_caller_impact.py`. A failure here is a disqualifying bug, not a performance issue.

---

## Module Responsibilities

| Module | Pair | Responsibility |
|--------|------|----------------|
| **Call Session Manager** | A – Transport | LiveKit room lifecycle, call state FSM, ring-window timing |
| **Private Whisper Channel** | A – Transport | Routes Rime audio to `private_track_id` only; rejects caller-facing routing |
| **Streaming STT** | B – Signal | Deepgram/AssemblyAI streaming; emits `TranscriptEvent` with speaker tags |
| **Disconnect/Reconnect Detector** | B – Signal | Flags abrupt drops; matches caller ID on RINGING → sets `is_reconnect=True` |
| **Thread Memory Store** | C – Brain | SQLite/Postgres persistence of `ThreadSummary` per `caller_id` |
| **Recap Generator** | C – Brain | LLM prompt → Rime-formatted spoken text; emits `RecapRequest` |
| **Fact-Freshness Checker** | D – Voice & Facts | Re-verifies `TimeSensitiveFact` values against mock/live API |
| **Rime TTS Delivery** | D – Voice & Facts | Calls Rime API with correct model/voice/speed params; emits `TtsRequest` |

---

## Pair Boundaries & Shared Contracts

Every message that crosses a pair boundary is a **typed Pydantic schema** in `/shared/schemas/`. No verbal agreements — the schema file is the contract.

| Schema | From → To |
|--------|-----------|
| `CallStateEvent` | Transport → Signal |
| `TranscriptEvent` | Signal → Brain |
| `ThreadSummary` | Brain internal state |
| `RecapRequest` | Brain → Voice & Facts |
| `FreshnessResult` | Internal to Voice & Facts |
| `TtsRequest` | Voice & Facts → Transport |

**No solo merges to `/shared/schemas/`** — a silent change there breaks every other pair's mocks.

---

## Key Scenarios

| Scenario | Trigger | Outcome |
|----------|---------|---------|
| **A** — Normal call | Call ends with closing turn | Short "last touchpoint" note only |
| **B** — Reconnect (minutes) | RINGING + `is_reconnect=True` | Pre-answer whispered recap during ring window |
| **C** — Reconnect (next day, stale fact) | Same as B + freshness check detects change | Recap includes freshness flag: "Heads up — X is now Y" |
| **D** — Instant connect (no ring buffer) | CONNECTED with no ring window | Live whisper channel: user invokes mid-call |

---

## Tech Stack Summary

| Layer | Tech |
|-------|------|
| Realtime transport | LiveKit Agents + LiveKit Cloud |
| Telephony | LiveKit SIP / Twilio SIP trunk → LiveKit |
| STT | Deepgram or AssemblyAI (LiveKit plugin) |
| TTS | **Rime only** (Coda / Mist v2 / Mist v3 via LiveKit Rime plugin) |
| LLM | Gemini (fast model for TL;DR, strong model for freshness diff) |
| Memory | SQLite (hackathon) / Postgres (production) |
| Mock data API | FastAPI (see `/mocks/mock_freshness.py`) |
| Frontend | React dashboard (latency graphs, call log) |
| Evaluation | Python scripts + saved WAV clips → `RIME_EVIDENCE.md` |

---

## Environment Configuration

All secrets live in `.env` (never committed). Copy `.env.example` and fill in credentials. Toggle `USE_MOCKS=true` for local development without external services.

See `shared/config/settings.py` for the full schema.
