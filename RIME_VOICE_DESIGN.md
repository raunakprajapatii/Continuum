# Continuum: Optimal Voice Pipeline & TTS Design Specification

> **Architectural Design Specification for Continuum Voice & Facts (Pair D)**  
> Synthesized from official Rime AI documentation ([RIME_RESEARCH.md](file:///Users/pratikprajapati/Continuum/RIME_RESEARCH.md)) and Continuum system architecture ([ARCHITECTURE.md](file:///Users/pratikprajapati/Continuum/docs/ARCHITECTURE.md)).

---

## 1. Executive Summary & Design Philosophy

Continuum is a voice-native telephony continuity system. When a call abruptly drops and reconnects, an AI-generated recap is streamed privately into the agent's earpiece during the ring window—**before** the agent answers. The customer hears only standard ringback and never detects the recap.

### 1.1 The "Colleague Whisper" Experience

The voice is **not** an IVR assistant talking to an external customer. It is an **expert briefing delivered privately to a busy professional** wearing headphones.

```
       ┌────────────────────────────────────────────────────────────┐
       │                   The Target Persona                       │
       │                                                            │
       │   A calm, composed, highly competent colleague leaning     │
       │   over the agent's shoulder to whisper:                    │
       │   "Heads up — she was asking about the refund on item 4."   │
       └────────────────────────────────────────────────────────────┘
```

### 1.2 Core Experience Tenets

| Dimension | Target Experience (What to do) | Anti-Pattern (What to avoid) |
| :--- | :--- | :--- |
| **Tone** | Calm, reassuring, warm, collegial | Chirpy, excited, overly synthetic, or monotone robotic |
| **Delivery** | Steady, unhurried conversational cadence | Breathless, rushed sprint or plodding IVR announcements |
| **Acoustic Texture** | Soft, grounded, low-fatigue headphone tuning | Harsh sibilance, piercing highs, sudden volume shifts |
| **Cognitive Load** | Lead with immediate headline; max 1 key next action | Dense info dumps, reading transcript logs, nested clauses |
| **Fact Freshness** | Explicit flag early: *"Heads up — [old] is now [new]"* | Silent overwrites or burying updates at the end |
| **Prosody Control** | Natural punctuation-driven breathing (commas, ellipses) | SSML tags, unnatural mechanical pause gaps |

---

## 2. Phase 1 — Voice Personality & Behavioral Specification

### 2.1 Vocal Persona Profile

- **Name / Persona Archetype:** *"The Composed Colleague"*
- **Vocal Age & Demographic:** 30–50 years old, warm American standard English.
- **Speaking Pitch & Resonance:** Medium-to-low register with rich chest resonance; minimizes auditory fatigue over 8-hour headset shifts.
- **Speaking Rate:** 140–150 words per minute (WPM). Under urgency, slightly compressed (~160 WPM), but never exceeding comfortable comprehension.

### 2.2 Rhythm, Breathing, and Pause Patterns

Rime Coda synthesizes speech directly from text and punctuation without SSML tags:

1. **Sentence Length Constraint:**
   - **Hard upper limit:** **18 words** per sentence.
   - **Optimal target:** **8 to 14 words** per sentence.
   - *Why:* Any sentence exceeding 20 words sounds breathless and creates anxiety in the listener.
2. **Punctuation as Prosody Cues:**
   - **Commas (`,`):** Short tactical pauses (~180–220ms) with a subtle upward inflection that maintains attention.
   - **Periods (`.`):** Definite sentence completion pause (~450–550ms) with a natural downward pitch drop.
   - **Ellipses (`...`):** Thoughtful, conversational transition (~500–650ms). Used when pivoting from headline to details: *"So... she's calling about order 402."*
   - **Exclamation Marks (`!`):** Strictly forbidden in standard recaps. They induce artificial excitement and raise listener cortisol.
   - **Hyphens (`-`):** Never used within numbers or codes (causes stutters); used as em-dashes (` — `) for conversational parentheticals.

### 2.3 Conversational Phrases & Disfluency Framework

- **Authorized Disfluencies:**
  - *"So,"* (conversational starter, frames the context)
  - *"Yeah,"* (natural affirmation)
  - *"Heads up —"* (immediate priority alert)
  - *"Right now,"* (temporal anchor)
  - *"One sec,"* (brief orienting phrase)
- **Hard Disfluency Invariant:**
  - **No stacking:** Maximum **one** conversational filler per utterance. Stacking (e.g., *"Um, yeah, so"*) sounds like an engine malfunction.
  - **No preamble filler:** Never start with *"Here is your recap"*, *"Let me catch you up"*, or *"I'm going to tell you"*.

### 2.4 Information Delivery Protocols

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Recap Structure Template                        │
│                                                                        │
│  [1. Immediate Headline]      (What is this call about? ≤ 15 words)    │
│  [2. Freshness Flag]          (If any fact changed while disconnected) │
│  [3. Critical Anchor / ID]    (Account #, tracking, price - spelled)   │
│  [4. Interruption State]      (If disconnected mid-thought)            │
│  [5. Single Next Action]      ("Your move: confirm the refund.")       │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Introducing Changed Facts (Freshness Protocol):**
   - Must be delivered in sentence 2 (immediately after the headline).
   - Standard phrasing: `"Heads up — the flight was delayed by 2 hours, now departing at 6:15 PM."`
2. **Communicating Uncertainty:**
   - Plain, transparent language: `"It's unclear whether she already rebooted the router."`
   - Never fabricate or guess unstated details.
3. **Communicating Interrupted Turns:**
   - Explicitly quote the truncated thought: `"She was cut off while saying: 'Wait, don't cancel that'."`
4. **Maximum Recap Duration:**
   - **Standard ring window budget:** 3 to 6 seconds total speech (~12 to 25 words total).
   - **Extended budget (long ring):** Maximum 10 seconds (~40 words).

---

## 3. Phase 2 — Model, Voice, & Parameter Evaluation

Based on the official Rime documentation research, here is the technical configuration matrix for Continuum:

### 3.1 Recommended Configuration

| Parameter | Recommended Choice | Rationale & Tradeoffs |
| :--- | :--- | :--- |
| **Model** | **`coda`** | **Voice Quality & Realism:** Coda scored highest in Rime's human evaluations for natural prosody, breathing, and artifact-free conversational speech. Sub-100ms model latency (P50 96ms) comfortably satisfies our telephony budget. |
| **Fallback / Fast Model** | **`mistv3`** | If ring window is < 2.0s, switch to `mistv3` for ultra-fast TTFA (37ms P50). |
| **Voice / Speaker** | **`eyre`** (Coda) | Description: *"A warm, friendly American voice; calm and easy to listen to."* Age 30–50. Perfectly matches the "Composed Colleague" archetype. Low fatigue for agent headphones. |
| **Alternative Speaker (Male)**| **`masonry`** (Coda) | Description: *"A confident, low Southern voice; authoritative without being loud."* Excellent alternative if agent prefers male pitch. |
| **Speed (`timeScaleFactor`)** | **`0.92`** (Coda) | Values < 1.0 produce slightly faster speech on Coda. `0.92` provides crisp delivery without feeling rushed or unnatural. |
| **Audio Format** | **`audio/mpeg`** (or **`audio/webm;codecs=opus`**) | High-quality 24kHz stream for LiveKit WebRTC earpiece track. (For SIP trunking, `audio/PCMU` at 8kHz). |
| **Transport** | **HTTP Chunk Streaming (`/v1/rime-tts`)** | For server-side pre-generated recaps (recap text built upfront from thread summary), HTTP chunked streaming provides simple connection lifecycle and immediate byte streaming to LiveKit. |
| **Realtime Transport** | **WebSocket (`/ws3`)** | If streaming token-by-token from an LLM in the future, `/ws3` provides word-level timestamps and interruption handling (`clear`). |

### 3.2 Evaluation of Existing Code vs Rime Documentation

A careful audit of our current implementation against the documentation reveals four key alignment opportunities:

1. **Model Selection on `spell(...)`:**
   - *Current code:* Automatically forced `model = RimeModel.MIST_V2` if `spell(` was in the text.
   - *Rime Docs truth:* `coda` accepts all text naturally; `mistv3` supports `spell(...)` with 3-character acoustic grouping. `mistv2` is only required for inline bracket phonemes. `coda` should be preserved as the primary model.
2. **Speed Multiplier Semantics:**
   - *Current code:* Inverted speed on `mistv2` using `1.0 / tsf`.
   - *Rime Docs truth:* On Coda and Mist v3, `timeScaleFactor < 1.0` is faster, while `speedAlpha > 1.0` is faster. On Mist v2, `speedAlpha < 1.0` is faster. We should explicitly standardize on `timeScaleFactor` across Coda/Mist v3.
3. **Speaker Selection:**
   - *Current settings:* Defaulted to `"sol"` or `"astra"`.
   - *Rime Docs truth:* `"astra"` is energetic and bright (often too hyper for an agent headset). `"eyre"` is explicitly documented as calm, friendly, and easy to listen to.
4. **Text Normalization:**
   - *Current code:* Handled bare IDs by regex wrapping.
   - *Rime Docs truth:* Rime natively handles currency, full dates, times, and phone numbers. Pre-normalization is only needed for known gaps (bare MM/DD, bare hours, unformatted numbers, and explicit `spell(...)` on codes).

---

## 4. Phase 3 — LLM Prompting Layer Design

When Brain (Pair C) uses an LLM to generate spoken recap text from raw thread memory, the prompt must enforce oral composition rules.

### 4.1 Production System Prompt: The Spoken Ear Generator

```markdown
You are Continuum's Voice Recap Generator.
Your job is to convert raw customer thread memory and recent fact updates into a 
private, spoken audio briefing for a professional telephone agent.

This text will be read aloud through the agent's headphones using Rime TTS.
Write strictly for the ear, not the eye.

CORE RULES:

1. STRUCTURE:
   - Sentence 1: The One-Sentence Headline. State who is calling and the exact topic.
     Never start with greetings, pleasantries, or preamble (NO "Here is your recap", NO "Let me update you").
   - Sentence 2 (if facts changed): The Freshness Alert.
     Format: "Heads up — [old value] is now [new value]."
   - Sentence 3 (optional): Key anchor or context.
     Mention the specific order, product, or reason.
   - Sentence 4 (if call dropped mid-sentence): Interruption Context.
     Format: "She was cut off saying: '[exact fragment]'."
   - Final Sentence: Single Next Action.
     Format: "Your move: [concrete action]." or "Next step: [action]."

2. BREATH & SENTENCE LENGTH:
   - Hard maximum: 18 words per sentence.
   - Target length: 8 to 14 words per sentence.
   - Split compound ideas with periods, not conjunctions.

3. PROSODY VIA PUNCTUATION ONLY:
   - Use commas (,) for natural speaking pauses.
   - Use periods (.) for falling pitch at sentence ends.
   - Use ellipses (...) sparingly for thoughtful transitions.
   - NEVER output SSML tags (<break>, <prosody>, <voice>).
   - NEVER use exclamation marks (!).

4. CONVERSATIONAL ANCHORS & DISFLUENCY:
   - Use natural spoken contractions ("she's", "they've", "didn't", "we're").
   - Allowed conversational anchors: "So,", "Yeah,", "Heads up —", "Right now,".
   - NEVER stack fillers (NO "Um, yeah, so"). Maximum ONE filler in the entire recap.

5. IDENTIFIERS & NUMBER NORMALIZATION:
   - Wrap tracking numbers, confirmation codes, SKUs, and alphanumeric IDs in spell(...).
     Example: spell(ABC123XYZ), spell(TKT4901).
   - Standard phone numbers and currency ($45.50) pass through normally.
   - Expand bare dates without years: 04/21 -> "April 21st".
   - Expand bare hours: 3pm -> "3:00pm".
   - Remove hyphens from IDs before wrapping: "AB-12" -> "spell(AB12)".

6. INVARIANTS:
   - Total word count must not exceed 45 words.
   - Never invent details not present in the thread memory.
   - Output ONLY the spoken text. No metadata, no quotation marks around output.
```

---

## 5. Phase 4 — Curated Scenarios: Robotic vs Continuum

Here are 20 real-world scenarios contrasting typical robotic LLM output against Continuum's optimized whisper recap:

| # | Domain / Situation | Structured Memory Context | Bad Robotic Recap (Anti-Pattern) | Optimized Continuum Recap |
| :- | :--- | :--- | :--- | :--- |
| **1** | **E-Commerce Return** | Customer Sarah calls back after dropped call; wants to return damaged coffee maker order #88219. | *"Hello agent. The customer on the line is Sarah and she is calling regarding order number 88219 which was a coffee maker that arrived damaged and she desires to process a return for it."* | *"Sarah is calling back about returning a damaged coffee maker. The order is spell(88219). Your move: initiate the return label."* |
| **2** | **Airline Booking (Changed Price)** | Call dropped while pricing flight SFO→JFK; fare increased from $320 to $410 overnight. | *"The customer disconnected while discussing flight pricing. Please note that the fare has increased from $320 to $410 since the previous call occurred."* | *"David is booking SFO to JFK. Heads up — the fare jumped from $320 to $410. Next step: confirm if he still wants the seat."* |
| **3** | **Medical Scheduling** | Patient Maria disconnected while scheduling annual exam; doctor Dr. Chen booked up until Oct 14. | *"Maria was in the middle of scheduling her yearly physical appointment with Dr. Chen but Dr. Chen has no availability until October 14th."* | *"Maria needs her annual physical with Dr. Chen. Heads up — Dr. Chen is booked until October 14th. Your move: offer the 14th."* |
| **4** | **Banking Fraud Alert** | Customer noticed $850 unauthorized charge at Best Buy on card ending 4412; call dropped mid-verification. | *"The caller is reporting fraudulent activity of $850 at Best Buy on credit card ending in 4412 and the identity verification process was incomplete."* | *"Jordan is reporting an $850 fraud charge at Best Buy. Card ends in spell(4412). She was cut off during verification. Your move: finish security questions."* |
| **5** | **Tech Support (Fiber Outage)** | Fiber optic internet down; ticket INC-9901 created; outage resolved 10 mins ago. | *"Customer is calling regarding internet downtime for ticket INC-9901. Our diagnostic system indicates the regional outage was resolved 10 minutes ago."* | *"Alex is following up on internet downtime. The ticket is spell(INC9901). Heads up — the neighborhood outage cleared 10 minutes ago. Your move: ask him to check the router light."* |
| **6** | **SaaS Sales Negotiation** | Renewal discussion; customer demanded 15% discount on 50 seats; dropped mid-offer. | *"We were negotiating with Enterprise buyer Mark regarding renewing 50 seats with a requested 15 percent price reduction before the line dropped."* | *"Mark is negotiating renewal pricing on 50 seats. He requested a 15% discount. He was cut off saying: 'If you can do 15, we sign today'. Your move: present the 10% counter."* |
| **7** | **Auto Insurance Claim** | Collision claim CLM-7712; deductible dispute; customer was angry when call disconnected. | *"The customer disconnected while in an agitated emotional state regarding the $500 deductible applied to collision claim CLM-7712."* | *"Marcus is disputing the $500 deductible on claim spell(CLM7712). He was frustrated when the call dropped. Your move: explain the comprehensive waiver."* |
| **8** | **Hotel Reservation (Sold Out)** | Customer wants ocean-view suite at Sunset Bay; last suite booked by another caller during drop. | *"The customer wishes to reserve an ocean suite at Sunset Bay hotel but our inventory system indicates that the last suite was just reserved."* | *"Elena wants the ocean-view suite at Sunset Bay. Heads up — that suite just sold out. Your move: offer the terrace suite with a $50 credit."* |
| **9** | **Pharmacy Refill** | Refill Rx 449210 for Lisinopril; doctor hasn't authorized refill yet. | *"Customer needs prescription refill for Lisinopril prescription number 449210 however the prescribing physician has not provided authorization yet."* | *"Robert is calling for a Lisinopril refill on prescription spell(449210). Doctor authorization is still pending. Your move: offer a three-day emergency bridge."* |
| **10** | **Utilities Disconnect** | Power shutoff notice sent in error; account 9021-X; customer was reading notice date. | *"The caller received an erroneous power termination notice for account 9021-X and was reading the date on the letter when disconnected."* | *"Claire received a shutoff notice sent in error on account spell(9021X). She was cut off reading the date. Your move: confirm her power stays on."* |
| **11** | **B2B Logistics (Delayed Truck)** | Delivery of pallet shipment tracking 1Z-9988; truck held at weigh station; delivery moved from 2pm to 5pm. | *"Shipment tracking 1Z-9988 delivery has been delayed due to weigh station hold and the ETA is revised from 2:00 PM to 5:00 PM."* | *"Tom is tracking pallet shipment spell(1Z9988). Heads up — the truck was delayed, new arrival is 5:00pm. Next step: confirm receiving dock hours."* |
| **12** | **Retail Store Pickup** | Order pickup for jacket SKU-411; customer arrived at North branch, but jacket is at Downtown store. | *"Customer is attempting pickup for jacket SKU 411 at the North branch location but inventory records show the item is located at Downtown."* | *"Sam is at the North branch for jacket SKU spell(411). Heads up — the jacket is actually at Downtown. Your move: offer free courier delivery."* |
| **13** | **Mortgage Application** | Pre-approval rate lock expiring tomorrow; missing W2 documentation; dropped mid-sentence. | *"The applicant's rate lock expires tomorrow and their application is currently blocked due to missing W2 tax documentation."* | *"Rachel is finalizing her mortgage rate lock before tomorrow's deadline. We still need her 2025 W-2. She was cut off saying: 'I just uploaded the file'. Your move: check the portal inbox."* |
| **14** | **Credit Card Activation** | New card activation; automated system rejected SSN match; agent needed to manually verify. | *"Caller attempted automated card activation but failed automated verification checks and requires live agent manual identity authentication."* | *"Carlos is trying to activate his new platinum card. The automated system failed to verify him. Your move: verify his billing zip code."* |
| **15** | **Telecom eSIM Transfer** | Transferring line from iPhone 13 to 16; IMEI spell(354921); dropped when old phone lost signal. | *"Customer was performing an eSIM migration to a new device with IMEI 354921 and disconnected because the primary cellular connection deactivated."* | *"Nina is transferring her eSIM to a new phone. IMEI is spell(354921). The old phone lost signal during the transfer. Your move: confirm the new eSIM profile is active."* |
| **16** | **Very Short Call (Dropped in 5s)** | Customer said "Hi, I need help with my water bill—" and dropped immediately. | *"The previous call session lasted 5 seconds and the customer stated an inquiry regarding their municipal water billing statement before dropping."* | *"Quick disconnect. Caller started asking about their water bill. Your move: pick up with 'Hi, looks like we got cut off about your bill'."* |
| **17** | **Long Multi-Issue Call** | 20-minute support call covering 3 bugs; bug 1 & 2 resolved; bug 3 (SSO redirect loop) still open. | *"We completed troubleshooting of bugs 1 and 2 during the previous 20 minute session but the single sign-on redirect loop issue remains unresolved."* | *"Long call with Priya. Bugs 1 and 2 are fixed. Only open item is the SSO redirect loop. Your move: ask for her Okta domain."* |
| **18** | **VIP Wealth Advisory** | Client Arthur; portfolio review; wire transfer of $250,000 to escrow was pending verbal confirmation. | *"High net worth client Arthur disconnected during discussion of executing an outgoing wire transfer of $250,000 intended for escrow funding."* | *"Arthur is confirming a $250,000 wire to escrow. We were one step away from verbal authorization. Your move: read the wire verification disclosure."* |
| **19** | **Gym Membership Cancellation** | Customer demanding immediate cancellation; retention offer of 50% discount for 3 months not yet presented. | *"Customer wishes to terminate gym membership contract and agent was about to present promotional retention offer of 50% discount for three months."* | *"Maya wants to cancel her membership. She was cut off before any retention offer. Your move: offer the 50% discount for three months."* |
| **20** | **Appliance Warranty Service** | Dishwasher repair dispatch; technician window changed from morning to afternoon (1:00pm to 4:00pm). | *"Customer is calling regarding dishwasher service appointment dispatch which has experienced scheduling modifications from morning to afternoon."* | *"Ken is calling about his dishwasher service visit. Heads up — the tech window shifted to 1:00pm to 4:00pm. Your move: confirm he will be home this afternoon."* |

---

## 6. Phase 5 — System Architecture & Component Design

### 6.1 Architectural Topology

The Voice & Facts system (Pair D) sits cleanly between Brain (Pair C) and Transport (Pair A):

```
                        ┌─────────────────────────────────┐
                        │      PAIR C: BRAIN              │
                        │  ThreadMemoryStore (SQLite/PG)  │
                        │  RecapGenerator (Fast LLM)      │
                        └────────────────┬────────────────┘
                                         │ RecapRequest
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        PAIR D: VOICE & FACTS PIPELINE                                  │
│                                                                                        │
│   ┌────────────────────────────────┐       ┌─────────────────────────────────────┐     │
│   │ 1. Fact-Freshness Engine       │       │ 2. Pre-Normalization & Formatting   │     │
│   │    - Async parallel verification│  ──►  │    - 8 Rime Rule Enforcement        │     │
│   │    - Detects changed values    │       │    - Pre-expands dates & bare hours │     │
│   │    - Emits "Heads up" flags    │       │    - spell(...) wrapping on IDs     │     │
│   └────────────────────────────────┘       └──────────────────┬──────────────────┘     │
│                                                               │ Spoken Text            │
│                                                               ▼                        │
│   ┌────────────────────────────────┐       ┌─────────────────────────────────────┐     │
│   │ 4. Latency & Telemetry Monitor │       │ 3. Rime Voice Engine & Client       │     │
│   │    - TTFA tracking (P50/P90)   │  ◄──  │    - Model: Coda (or Mist v3 fast)  │     │
│   │    - Step-by-step timing logs  │       │    - Speaker: Eyre (warm/calm)      │     │
│   │    - Audio frame metrics       │       │    - Speed: timeScaleFactor 0.92    │     │
│   └────────────────────────────────┘       └──────────────────┬──────────────────┘     │
└───────────────────────────────────────────────────────────────┼────────────────────────┘
                                                                │ TtsRequest
                                                                ▼
                        ┌─────────────────────────────────┐
                        │      PAIR A: TRANSPORT          │
                        │  LiveKit Dual-Track Invariant   │
                        │  Public: Caller Ringback (Muted)│
                        │  Private: Whisper Track (Rime)  │
                        └─────────────────────────────────┘
```

### 6.2 Component Responsibilities

1. **`FactFreshnessChecker` (`modules/voice/freshness_checker.py`):**
   - Receives `TimeSensitiveFact` objects from `RecapRequest`.
   - Executes non-blocking async REST queries against the live/mock enterprise API using `asyncio.gather`.
   - Flags changes: generates spoken diff (`"Heads up — [old] is now [new]."`).
2. **`TextNormalizer` & `RecapTextBuilder` (`modules/voice/recap_text_builder.py`):**
   - Applies pre-normalization rules for Rime gaps (MM/DD, bare hours, unformatted digit runs).
   - Enforces the 8 Rime prompting guide rules (sentence length ≤ 18 words, headline first, punctuation prosody).
   - Validates using `RimePromptValidator`; guarantees zero SSML or stacked fillers.
3. **`RimeTtsClient` (`modules/voice/rime_tts_client.py`):**
   - Enforces the **Dual-Track Invariant**: strictly verifies `private_track_id == settings.private_track_id`.
   - Configures model parameters: selects `coda` as primary, sets `speaker="eyre"`, and assigns `timeScaleFactor=0.92`.
   - Generates typed, immutable `TtsRequest`.
4. **`StreamingAudioHandler` (Transport integration):**
   - Consumes chunked HTTP stream (`audio/mpeg` or `audio/webm;codecs=opus`) in 4096-byte blocks.
   - Pushes bytes directly to LiveKit private track audio pump without buffering full body.
5. **`LatencyMonitor`:**
   - Records: `t_reconnect_detect`, `t_freshness_done`, `t_text_built`, `t_rime_ttfa`, `t_audio_start`.
   - Emits structured telemetry for the Continuum React dashboard.

---

## 7. Verification & Implementation Roadmap

When approved to move from design to implementation:

1. **Refine `RimeTtsClient`:**
   - Update default speaker from placeholder to `"eyre"`.
   - Default model to `coda` with clean fallback to `mistv3`.
   - Refine `timeScaleFactor` handling for Coda (`0.92`).
2. **Enhance `RecapTextBuilder` & Pre-Normalizer:**
   - Integrate date & bare-hour pre-normalization to eliminate Rime pronunciation anomalies.
   - Add sentence splitting safeguard ensuring no sentence exceeds 18 words.
3. **Update Test Suites:**
   - Run `evaluation/test_voice_pair_d.py` and `evaluation/run_voice_cases.py` to confirm all 44+ tests pass.
   - Add end-to-end latency benchmarks verifying TTFA < 200ms.

---
*Continuum Voice & Facts Design Specification — Approved for pair implementation.*
