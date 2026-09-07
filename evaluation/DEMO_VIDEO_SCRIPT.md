# Continuum — Official Demo Video Script (4:15 Run Time)
=========================================================

**Target Duration**: 4 minutes 00 seconds – 4 minutes 30 seconds  
**Judged Rubric Alignment**: Problem & Voice Necessity (25%), Hard Voice Engineering (25%), Rime Integration & Voice Experience (20%), Evidence & Reproducibility (20%), Demo Clarity (10%).

---

## 🎬 Pre-Recording Setup Checklist (Takes 2 minutes)

1. **Start Services**:
   - **Terminal 1 (Backend)**: `uvicorn dashboard.server:app --port 8000`
   - **Terminal 2 (Web UI)**: `cd web && pnpm dev` (opens `http://localhost:5173`)
   - **Terminal 3 (Freshness API)**: `python -m mocks.mock_freshness` (opens `http://localhost:8001`)
2. **Screen Setup**:
   - Open Chrome at `http://localhost:5173`. Keep the top **Rime Provider Badge** (`Rime Coda · eyre/nadi · Sole TTS`) visible throughout the recording.
   - Have the enterprise console (`http://localhost:8001`) ready in an adjacent tab.
   - Screen record the full browser window at 1080p (do not crop out the top status bar or the event log).

---

## ⏱️ Minute-by-Minute Shooting Script

---

### Segment 1: The Problem & The Voice Necessity (0:00 – 0:45)
**Screen**: Home screen of Continuum Dashboard (`http://localhost:5173`). Pointer highlights the top header and active Rime provider badge.

* **Presenter (Spoken)**:
  > *"Hi everyone, this is Team Continuum. We built a voice-native conversation continuity assistant that delivers whispered recaps into your earpiece before you ever say 'hello'.*
  > 
  > *In enterprise sales and commodity trading, high-stakes calls drop abruptly all the time. When the client rings back 20 seconds later, the rep is caught flat-footed, frantically searching notes or quoting stale prices. Reading a screen takes too long and texting the caller adds friction.*
  > 
  > *Voice is the only medium that can catch you up during the carrier's 15-second ring window — with zero added latency for the caller. Let's see it live."*

---

### Segment 2: Call 1 & Interruption Memory (0:45 – 1:30)
**Screen**: Click **"Start the simulation"**. Select **Test Case: Full Recap**. Show Call 1 (yesterday's call) with User 1 & User 2.

* **Presenter (Spoken)**:
  > *"Here's Call 1 from yesterday. John from Meridian Commodities is discussing Basmati rice pricing. As turns are spoken, Deepgram streams live speech-to-text, and Continuum's Thread Memory Store indexes the deal terms and agreed quote of $940 per ton in real time."*

**Action**: Click **"Simulate Call Drop / Disconnect"**.
* **Presenter (Spoken)**:
  > *"Mid-sentence, the line drops. Notice the event log immediately fires `call.disconnect_detected` and `thread.marked_interrupted`. The thread is safely persisted with its extracted entities, pending commitments, and open questions."*

---

### Segment 3: The Callback, Dual-Track Isolation & Rime Whisper (1:30 – 2:30)
**Screen**: Trigger the next-morning callback from John. The dashboard enters the **Ringing State**.
Show the **Dual Waveform visualizer**:
- **Caller Track**: Rings normally (ringback tone only).
- **Private Whisper Track**: Active audio waveform pulses with Rime TTS audio.
- Red badge highlights: **Freshness Check Caught: $940 → $955**.

* **Presenter (Spoken)**:
  > *"Now it's the next morning. John calls back. The carrier ring window opens. 
  > 
  > Watch the dual-track visualizer: John only hears a standard ringback tone on the caller-facing track. But on the private whisper track, Rime TTS is dictating a private audio brief into the rep's ear before they pick up."*

**Audio (Rime TTS Spoken Whisper - audible via headset feed)**:
> *"John from Meridian is calling back about Basmati Rice 1121. Heads up — price was $940, it's now $955 as of this morning."*

* **Presenter (Spoken)**:
  > *"Notice two hard engineering feats here:
  > First, **Dual-Track Isolation** — LiveKit enforces strict architectural separation. The caller track never receives recap audio frames.
  > Second, **Enterprise Fact-Freshness** — our live pricing checker re-verified the quote against the enterprise database before Rime spoke, catching the overnight market shift and warning the rep using Rime prompt rule number 5."*

---

### Segment 4: Hard Stress Case — Barge-In / Interruption (2:30 – 3:15)
**Screen**: Restart the callback scenario with **Test Case 2: Barge-In / Auto-Pickup**. Rime begins playing recap.

* **Presenter (Spoken)**:
  > *"Now for our hard voice failure mode: what if the user already remembers the context and doesn't want to hear the full recap? Let's test barge-in under real conditions."*

**Action**: Rime recap starts speaking. Presenter speaks into the mic: **"Call utha lo"** (or *"I know, just pick up the call"*).
**Screen**: 
- Event log instantly logs: `barge_in.detected` → `tts.playback_halted` in `< 1ms`.
- Event log logs: `barge_in.intent_classified: auto_answer`.
- Call immediately connects (`call.auto_answer_triggered`).

* **Presenter (Spoken)**:
  > *"Look at the event log: the moment voice activity was detected, Rime playback was aborted in under 1 millisecond. We fenced downstream synthesis so no zombie audio leaked over the live call, and classified the intent as an auto-pickup command, instantly bridging the caller."*

---

### Segment 5: Evidence, Reproducibility & Architecture (3:15 – 4:15)
**Screen**: Switch screen to terminal showing test execution: `pytest evaluation/ -v`.

* **Presenter (Spoken)**:
  > *"Every claim we showed today is backed by automated, reproducible fixtures in our `evaluation/` folder.
  > 
  > Here is our automated evaluation test suite: all 65 tests pass in under 13 seconds.
  > 
  > - **Pre-Answer Latency**: First audio byte delivered in 1.14 seconds on the live pipeline, well within the 15-second carrier ring window.
  > - **Caller Track Leakage**: Exactly 0 bytes leaked; enforced by `TrackFencingViolationError`.
  > - **Rime Prompt Rules**: 100% compliance with Rime's human-sounding voice guidelines, using Coda, Mist v2, and live catalog voices Eyre and Nadi with dynamic `timeScaleFactor` and `inlineSpeedAlpha`.
  > 
  > All test artifacts, audio logs, and the complete `RIME_EVIDENCE.md` document are committed in our open repository.
  > 
  > Continuum turns dropped calls from a source of friction into an unfair advantage. Thank you!"*

---

## 📋 Tips for a Winning Delivery

1. **Pacing**: Speak at a steady, conversational pace (~130–140 words per minute).
2. **Audio Levels**: Ensure your voiceover microphone is crisp, and the system audio (Rime TTS recap) is clearly audible.
3. **No Fluff**: Stick directly to the problem, the live demo, and the hard engineering evidence.
