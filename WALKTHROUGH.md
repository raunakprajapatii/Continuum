# Continuum — Complete Project & Transport Branch Walkthrough

Welcome to **Continuum**! This document is designed for new developers and team members working on the project for the first time. It walks you through what Continuum is, why it is built this way, how each module works, and how the **Transport (Pair A)** branch delivers the core voice innovation.

---

## Table of Contents
1. [The Problem: Why Continuum Exists](#1-the-problem-why-continuum-exists)
2. [The Core Innovation: Recap Before Pickup](#2-the-core-innovation-recap-before-pickup)
3. [Architecture & The 4-Pair Pipeline](#3-architecture--the-4-pair-pipeline)
4. [The Non-Negotiable Invariant: Dual-Track Audio Isolation](#4-the-non-negotiable-invariant-dual-track-audio-isolation)
5. [Deep Dive: Pair A (Transport Branch)](#5-deep-dive-pair-a-transport-branch)
   - [Call Session Manager & FSM](#call-session-manager--fsm)
   - [Private Whisper Channel](#private-whisper-channel)
   - [Priority Audio Ducking Controller](#priority-audio-ducking-controller)
   - [Transport Engine & CLI Demo](#transport-engine--cli-demo)
6. [The 4 Key Scenarios Explained](#6-the-4-key-scenarios-explained)
7. [Developer Quickstart & Testing Guide](#7-developer-quickstart--testing-guide)
8. [Acceptance Test Suite & Evidence](#8-acceptance-test-suite--evidence)

---

## 1. The Problem: Why Continuum Exists

Professionals (sales reps, account managers, lawyers, doctors on call, dispatchers) constantly juggle multiple high-stakes calls. When they get pulled off Call A by an emergency and Call A reconnects later (after 5 minutes or the next morning), two problems occur:
1. **The "Where Were We?" Delay**: Reconstructing context wastes time and signals disorganization.
2. **Dead Air**: Asking an assistant aloud *"catch me up"* after answering makes the other person sit through awkward silence.
3. **Stale Information**: A price, inventory count, or ticket status discussed yesterday may have changed overnight. Repeating stale data causes costly mistakes.
4. **Hands & Eyes Busy**: Looking at a notes app or CRM dashboard while picking up the phone is cumbersome. The user needs to **hear** the recap, not read it.

---

## 2. The Core Innovation: Recap Before Pickup

Continuum solves this with a simple yet powerful mechanic:

> **When an interrupted contact calls back, Continuum recognizes the caller and uses the 15–25 second ringing window to privately whisper a fast, accurate recap into the user's earpiece BEFORE they answer.**

```
Caller (Z) Dials                       User's Phone & Headset
      │                                          │
      ▼                                          ▼
   RINGING  ────────────────────────►  Phone Rings + Ring Window Opens
(Caller hears normal ringback)                   │
                                                 ├─► Continuum recognizes caller ID
                                                 ├─► Fact-freshness check runs
                                                 └─► Rime TTS whispers private recap:
                                                     "Z wanted the Q3 number;
                                                      heads up — price is now $420."
                                                         │
   CONNECTED ◄───────────────────────  User Answers Phone
(Caller experiences zero added delay)            │
                                       (User is already 100% caught up!)
```

- **Zero Added Latency to Caller**: The caller hears standard ringback.
- **Fact Freshness**: Before speaking a number or quote, Continuum checks the live database/tool.
- **Private Channel**: The caller never hears the assistant.

---

## 3. Architecture & The 4-Pair Pipeline

The system is organized into **4 paired teams** forming a continuous data loop:

$$\text{Audio} \xrightarrow{\text{Pair A}} \text{Transcript} \xrightarrow{\text{Pair B}} \text{Memory} \xrightarrow{\text{Pair C}} \text{Recap Text} \xrightarrow{\text{Pair D}} \text{Speech} \xrightarrow{\text{Pair A}} \text{Private Track}$$

```
Telephony / SIP Trunk
         │
         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        LiveKit Agents Session                          │
│                                                                        │
│   Caller-Facing Track  ◄──────────────────────── Never touched         │
│   User-Private Track   ◄─── Rime TTS recap audio ONLY                  │
└────────────────────────────────────────────────────────────────────────┘
         │                                   │
         ▼                                   ▲
   [Pair A: Transport]                 [Pair A: Transport]
   Call Session Manager                Private Whisper Channel
         │                                   ▲
         │ CallStateEvent                    │ TtsRequest
         ▼                                   │
   [Pair B: Signal]                    [Pair D: Voice & Facts]
   Streaming STT                       Rime TTS Delivery
   Disconnect/Reconnect Detector       Fact-Freshness Checker
         │                                   ▲
         │ TranscriptEvent                   │ RecapRequest
         ▼                                   │
   [Pair C: Brain] ──────────────────────────┘
   Thread Memory Store + Recap Generator
```

### Module Responsibilities:
- **Pair A — Transport** (`modules/transport/`): Manages LiveKit room lifecycle, call states, and ensures private whisper audio routes exclusively to the user's earpiece.
- **Pair B — Signal** (`modules/signal/`): Streams STT audio with Deepgram, detects abrupt hangups, and flags incoming reconnects.
- **Pair C — Brain** (`modules/brain/`): Stores structured facts (open items, commitments, numbers) in SQLite and uses Gemini LLM to draft short, spoken-style recaps.
- **Pair D — Voice & Facts** (`modules/voice/`): Queries live APIs to verify numbers and invokes Rime TTS with speed and phonetic formatting (`spell()`).

---

## 4. The Non-Negotiable Invariant: Dual-Track Audio Isolation

> **The caller-facing audio track and user-private audio track MUST be architecturally separate LiveKit tracks. They can NEVER be mixed.**

Why this matters:
- If recap audio ever leaks onto the caller's track, client confidentiality is breached and the submission is disqualified.
- Continuum guarantees this at the code level: `PrivateWhisperChannel` rejects any attempt to route recap audio to the caller track by raising `TrackFencingViolationError`.

---

## 5. Deep Dive: Pair A (Transport Branch)

The files you are working on live in `modules/transport/`:

### Call Session Manager & FSM (`session_manager.py`)
`CallSessionManager` governs call state transitions:
```
  [IDLE]
    │  ▲
    │  │ (hangup)
    ▼  │
 [RINGING] ───► [COMPLETED] (caller hung up before answer)
    │
    ▼ (user answers)
[CONNECTED]
    │
    ├─► [DISCONNECTED] (abrupt drop mid-call -> marked as INTERRUPTED)
    └─► [COMPLETED]    (normal call finish with goodbyes)
```
- **Ring Window Tracking**: When `RINGING` begins, a high-resolution timestamp is logged.
- **Caller Matching**: Checks the caller's phone number or SIP URI. If they hung up abruptly previously, `is_reconnect = True` is set and the previous thread is retrieved.
- **Event Distribution**: Publishes typed `CallStateEvent` objects to subscribers asynchronously.

### Private Whisper Channel (`whisper_channel.py`)
`PrivateWhisperChannel` receives `TtsRequest` objects from Pair D and plays the audio:
- **Track Fencing**: Checks `tts_request.private_track_id == settings.private_track_id`. If anyone passes the caller-facing track, it halts execution immediately.
- **Barge-In Interruptibility**: If the user speaks during recap (*"skip, I remember"*), `interrupt()` halts queued Rime audio in **under 500 ms** (measured at $0.09\text{ ms}$).

### Priority Audio Ducking Controller (`audio_ducking.py`)
*Feature built specifically for instant answers and mid-call catch-up:*
- **The Challenge**: What if the user answers the phone immediately, or the pre-answer recap didn't start in time?
- **The Solution**: When the call connects, the user can trigger **Priority Catch-Up**:
  1. Caller audio volume in the user's headset is **ducked down to 25%**.
  2. The assistant's summary voice is **boosted up to 125%**.
  3. The caller is **not muted** and still speaks normally; this balance only happens inside the user's headset.
  4. When the recap ends, caller volume smoothly restores back to 100%.

### Transport Engine & CLI Demo (`engine.py` & `main.py`)
`TransportEngine` brings the session manager and whisper channel together.
You can run the interactive CLI demo right now from your terminal:
```bash
USE_MOCKS=true python -m modules.transport.main --scenario reconnect --ducking
```

---

## 6. The 4 Key Scenarios Explained

### Scenario A — Normal Call
- Call connects, conversation completes with a normal closing (*"Thanks, bye"*).
- Call state transitions `CONNECTED` $\rightarrow$ `COMPLETED`. No interrupted thread is stored.

### Scenario B — Fast Reconnect (Mid-Call Disconnect)
- Call drops abruptly mid-sentence (e.g. elevator, tunnel).
- Session Manager marks the thread `is_interrupted = True`.
- Contact calls back 2 minutes later.
- During `RINGING`, Continuum recognizes the caller ID, generates a 1-sentence TL;DR, and whispers it into the user's earpiece before the phone is answered.

### Scenario C — Reconnect Next Day with Stale Fact
- Yesterday, User and Contact discussed a unit price of **$400**.
- Today, Contact calls back.
- During ringback, the Fact-Freshness Checker queries the mock API and discovers the price changed to **$420**.
- Recap whispers: *"Z wanted the Q3 number. Heads up — unit price was $400, it's now $420 as of this morning."*

### Scenario D — Instant Connect & Mid-Call Fallback Whisper
- User answers immediately with zero ring buffer.
- During the live call, user taps *"Catch Me Up"*.
- Caller voice ducks to 25%, recap voice boosts to 125% on the private track, and audio levels restore immediately upon completion.

---

## 7. Developer Quickstart & Testing Guide

### Prerequisites
- Python 3.11+
- Git branch: `Transport`

### Running the Tests
All unit and acceptance tests run with zero external services required in mock mode:
```powershell
# Run Transport unit tests
pytest tests/test_transport.py -v

# Run Hackathon acceptance evaluation suite
USE_MOCKS=true pytest evaluation/ -v

# Run the complete test suite (14/14 tests)
pytest -v
```

### Running the Live Transport CLI
```powershell
# Simulate Reconnect with Audio Ducking
USE_MOCKS=true python -m modules.transport.main --scenario reconnect --ducking

# Simulate Instant Connect Fallback
USE_MOCKS=true python -m modules.transport.main --scenario instant_connect
```

---

## 8. Acceptance Test Suite & Evidence

The acceptance tests in `evaluation/` satisfy the **Evidence & Reproducibility** judging criteria:

| Acceptance Test | Script | Measured Result | Status |
|-----------------|--------|-----------------|--------|
| **Pre-Answer Latency** | `test_pre_answer_latency.py` | $< 0.01\text{ s}$ ($\le 5.0\text{ s}$ threshold) | **PASS** |
| **Zero Impact on Caller** | `test_zero_caller_impact.py` | 0 bytes leaked to caller track | **PASS** |
| **Context Fencing** | `test_context_fencing.py` | 0 keyword leaks between threads | **PASS** |
| **Freshness Catch** | `test_freshness_catch.py` | Detected price update ($400 $\rightarrow$ $420) | **PASS** |
| **Interruptibility** | `test_interruptibility.py` | $0.09\text{ ms}$ barge-in stop latency | **PASS** |
| **Fallback Whisper** | `test_fallback_whisper.py` | Private track + priority ducking verified | **PASS** |

Each test automatically generates a verified JSON artifact in `evaluation/artifacts/`.
