# Rime AI Research & Technical Intelligence

Comprehensive research based on the official Rime AI documentation ([docs.rime.ai](https://docs.rime.ai)) for **Continuum**, a real-time telephony platform delivering a synthesized whisper recap privately into an agent's ear before answering a reconnected dropped call.

---

## 1. Documentation Pages Studied

The following official documentation pages from [https://docs.rime.ai/llms.txt](https://docs.rime.ai/llms.txt) were systematically reviewed:

| Documentation Page | URL | Key Focus & Relevance to Continuum |
| :--- | :--- | :--- |
| **Documentation Index** | `https://docs.rime.ai/llms.txt` | Complete map of Rime documentation, API references, guides, and SDK integrations. |
| **Models** | `https://docs.rime.ai/docs/models.md` | Model families (`coda`, `mistv3`, `mistv2`), feature matrix, architectural differences, and tradeoffs. |
| **Voices Catalog** | `https://docs.rime.ai/docs/voices.md` | Voice lineup, language support (BCP 47), starter voices (`astra`, `eyre`, `hesse`, etc.), and styles. |
| **Prompting Guide** | `https://docs.rime.ai/docs/prompting.md` | Writing for the ear vs written prose, disfluencies, punctuation as prosody, sentence length, and drop-in prompts. |
| **Low-Latency TTS** | `https://docs.rime.ai/docs/latency.md` | TTFA (Time-to-First-Audio) benchmarks, RTF, regional routing, telephony sampling rates, and latency factors. |
| **Streaming TTS** | `https://docs.rime.ai/docs/streaming.md` | HTTP streaming vs WebSockets vs SSE, audio chunk consumption, telephony integration (LiveKit, SIP). |
| **WebSocket API Overview** | `https://docs.rime.ai/docs/websockets.md` | `/ws3` (JSON) vs `/ws2` vs `/ws`, word-level timestamps, context IDs, interruption controls (`clear`, `flush`, `eos`). |
| **Text Normalization** | `https://docs.rime.ai/docs/text-normalization.md` | Automatic expansion of numbers, dates, times, currencies, and debugging with `/textnorm`. |
| **Spell Function** | `https://docs.rime.ai/docs/spell.md` | Letter-by-letter and digit-by-digit reading with `spell(...)`, grouping pauses, and symbol handling. |
| **Playback Speed** | `https://docs.rime.ai/docs/speed.md` | Speed controls: `timeScaleFactor` vs `speedAlpha` across Coda and Mist, inline speed overrides. |
| **Custom Pauses** | `https://docs.rime.ai/docs/custom-pauses.md` | Millisecond-level pause tags (`<750>`) on Mist models using `pauseBetweenBrackets`. |
| **Pre-Normalization** | `https://docs.rime.ai/docs/pre-normalization.md` | Known normalizer gaps (bare MM/DD, bare hours, Roman numerals, vanity numbers) and LLM prompt templates. |
| **Numbers & Currencies** | `https://docs.rime.ai/docs/numbers.md` | Specific normalizer expansion rules for quantities, decimals, fractions, ranges, and phone numbers. |
| **Coda HTTP API** | `https://docs.rime.ai/api-reference/coda/http.md` | Request payload schema, Accept header codecs (`audio/webm;codecs=opus`, `audio/PCMU`, `audio/mpeg`, `audio/L16`). |

---

## 2. Models & Architectural Tradeoffs

Rime provides two active model families: **Coda** and **Mist** (`mistv3`, `mistv2`, legacy `mist`).

### 2.1 Model Overview

| Model ID | Release Date | Architecture & Strengths | Target Use Case |
| :--- | :--- | :--- | :--- |
| **`coda`** | May 2026 | Flagship TTS model pairing an LLM backbone with a dedicated speech inference engine trained on full-duplex conversational data. Highest human evaluation scores for naturalness, prosody, and conversational realism. | Conversational AI, natural agent briefings, high-realism dialogue where human-like warmth is critical. |
| **`mistv3`** | March 2026 | Ultra-low latency engine. Fastest TTFA in the industry (~37ms P50). Supports custom pause tags `<ms>`. Uses native grammar normalizer. | Extreme latency-critical turn-taking, IVR, interactive voice bots requiring sub-50ms TTFA. |
| **`mistv2`** | Feb 2025 | Production clarity engine. Supports inline phonetic overrides (`phonemizeBetweenBrackets`) and custom pauses. Higher median latency (~175ms). | Applications strictly requiring custom IPA/phoneme overrides for uncommon enterprise lexicons. |

### 2.2 Benchmarks (Lambda H100 SXM5 Benchmark)

| Metric | `coda` | `mistv3` | Analysis for Continuum |
| :--- | :--- | :--- | :--- |
| **TTFA (P50 @ 1 Concurrency)** | **96 ms** | **37 ms** | Both are well under the human perceptual lag limit (~200ms). |
| **TTFA (P90 @ 1 Concurrency)** | **98 ms** | **56 ms** | Highly deterministic first-chunk emission. |
| **TTFA (P50 @ 12 Concurrency)** | **150 ms** | **37 ms** | Coda scales gracefully under load, maintaining sub-200ms. |
| **TTFA (P90 @ 12 Concurrency)** | **181 ms** | **56 ms** | Even at peak concurrency, Coda cloud stays <200ms. |
| **RTF (P99)** | **0.33** | **0.004** | Coda generates audio 3x faster than real-time; Mist is instantaneous. |

### 2.3 Feature Matrix

| Feature | `coda` | `mistv3` | `mistv2` |
| :--- | :---: | :---: | :---: |
| **Voice Catalog Count** | 253 voices | 78 voices | 138 voices |
| **Cloud Languages** | 9 (`en`, `es`, `fr`, `de`, `ja`, `pt`, `ar`, `hi`, `it`) | 4 (`en`, `es`, `fr`, `de`) | 4 |
| **Native Text Normalization** | Handled natively by model | Rule-based grammar stage | Rule-based grammar stage |
| **`spell()` Function** | Passed through to model | Handled with acoustic grouping | Handled |
| **Prosody via Punctuation** | Highly expressive | Moderate | Moderate |
| **Custom Pauses (`<ms>`)** | ❌ | ✅ (`pauseBetweenBrackets`) | ✅ |
| **Inline Phonemes (`[phoneme]`)** | ❌ | ❌ | ✅ (`phonemizeBetweenBrackets`) |
| **Speed Parameter** | `timeScaleFactor` (default 1.0) | `timeScaleFactor` | `speedAlpha` |

### 2.4 Model Tradeoff Analysis for Continuum

1. **Naturalness & Cognitive Comfort vs Raw Latency:**
   - **Continuum's context:** An agent wears headphones all day. When a customer call drops and reconnects, the agent needs a brief 5–10 second recap. Hearing an IVR-style or robotic voice produces auditory fatigue and cognitive friction.
   - **Verdict:** `coda` is vastly superior in vocal texture, warmth, and conversational realism. Its sub-100ms model latency (plus ~25-50ms network RTT) gives an end-to-end TTFA of ~125–150ms, comfortably below the 200ms telephony threshold while sounding like an authentic colleague.
2. **Deterministic Control vs Conversational Prosody:**
   - While `mistv3` supports explicit millisecond pause tags `<750>`, `coda` responds naturally to standard punctuation (commas, ellipses, periods) and generates human-grade cadence without artificial gaps.

---

## 3. Voice Options & Acoustic Characteristics

Rime categorizes its flagship Coda voices into four distinct styles: **Professional**, **Formal**, **Casual**, and **Energetic**.

### 3.1 Featured Coda Voices

| Speaker ID | Gender | Age / Accent | Style Assignment | Catalog Description & Acoustic Profile |
| :--- | :--- | :--- | :--- | :--- |
| **`eyre`** | Female | 30–50 / American | **Formal** | *"A warm, friendly American voice; calm and easy to listen to."* Unhurried, grounded, highly soothing on headphones. |
| **`hesse`** | Female | 18–30 / American | **Casual** | *"A relaxed, easygoing female voice."* Low tension, natural conversational tone, feels like an empathetic peer. |
| **`lyra`** | Female | 18–30 / American | **Professional** | *"A warm young American voice; bright and lively."* Clear, articulate, professional. |
| **`masonry`** | Male | 30–50 / Southern US | **Professional** | *"A confident, low Southern voice; authoritative without being loud."* Deep pitch, reassuring, steady. |
| **`marlu`** | Male | 30–50 / Australian | **Formal** | *"An older Australian voice; low, mature, unhurried."* Deep, calm, steady pacing. |
| **`bancroft`** | Male | 60+ / American | **Formal** | *"A composed American voice; strong on professional and formal contexts."* Measured, mature. |
| **`astra`** | Female | 18–30 / Californian | **Energetic** | *"Bright, lively Californian; quick and expressive."* Default Rime test voice; energetic and crisp. |
| **`luna`** | Female | 18–30 / American | **Casual** | *"A bright, lively female voice; energetic with a casual core."* Friendly and upbeat. |
| **`cove`** *(Mist v3)*| Female | Young / African Am. | **Mist v3** | Smooth, balanced, clear pronunciation. |

### 3.2 Voice Selection for Continuum's "Whisper Recap" Persona

- **The Goal:** A private briefing in an agent's headset. The agent has just experienced the stress of a dropped call and must immediately reconnect with a customer.
- **Auditory Requirements:**
  - Zero piercing highs or harsh sibilance.
  - Steady, unhurried cadence (~140–155 WPM).
  - Calm, empathetic, collegial baseline.
- **Top Voice Recommendations:**
  1. **Primary Recommendation: `eyre` (`modelId: coda`)**
     - Matches the description perfectly: *"warm, friendly, calm, and easy to listen to."*
     - The mature 30–50 demographic gives an air of steady competence without being clinical.
  2. **Alternative Female: `hesse` (`modelId: coda`)**
     - For contact centers preferring a casual, low-stress, peer-to-peer vibe.
  3. **Alternative Male: `masonry` (`modelId: coda`)**
     - For environments preferring a grounded, low-frequency masculine voice that does not fatigue the ear.

---

## 4. Prompting Techniques for Speech Synthesis

Rime documentation stresses that LLMs are trained to generate text for readers, not listeners. Reading written prose aloud produces stiff, robotic TTS.

### 4.1 Core Rules for the Spoken Ear

1. **Write for the Ear, Not the Page:**
   - Always use contractions: *"He's"*, *"they've"*, *"didn't"*, *"we're"*.
   - Never use formal document transitions: eliminate *"furthermore"*, *"moreover"*, *"in conclusion"*, *"as per our records"*.
   - Start sentences with conversational connectives: *"So"*, *"And"*, *"Heads up"*, *"Right now"*.
2. **Sentence Length & Breath Control:**
   - **Strict constraint:** Spoken sentences must remain under **20 words**, ideally **10–15 words**.
   - TTS engines reading long sentences without commas sound breathless and hurried.
3. **Punctuation Controls Prosody (No SSML):**
   - Rime models **do not accept SSML** (`<break>`, `<prosody>`, `<emotion>` tags will either be read literally or cause errors).
   - **Comma (`,`):** Inserts a natural short internal pause (~150–250ms) with a subtle rise in intonation.
   - **Period (`.`):** Produces a definitive falling pitch and end-of-sentence pause (~400–600ms).
   - **Ellipsis (`...`):** Introduces a thoughtful, hesitant pause (~500–700ms). Perfect for signaling a topic transition: *"So... here's where we left off."*
   - **Question Mark (`?`):** Generates rising intonation.
   - **Exclamation Mark (`!`):** Injects pitch emphasis and excitement. **Use sparingly or avoid entirely in Continuum** to keep the agent calm.
4. **Controlled Disfluencies:**
   - Human speech contains natural micro-disfluencies: *"so"*, *"yeah"*, *"well"*, *"one sec"*.
   - **Rule:** Sprinkle, do not stack. Never use two fillers in a row (e.g., *"um, uh"* sounds like an engine glitch).
   - Use disfluencies strategically at the start of pivots: *"Heads up —"*, *"Quick update —"*.
5. **Freshness & Fact Changes:**
   - In dropped calls, situational facts may change while reconnecting (e.g., flight status updated, item out of stock, technician delayed).
   - Must be stated immediately and plainly: *"Heads up — the seat was booked by someone else, so we need alternative 14B."*

---

## 5. Text Normalization Rules & Edge Cases

Rime features a built-in grammar normalizer (`/textnorm`) that converts non-standard words into spoken equivalents.

### 5.1 Formats Handled Automatically by Rime

The following pass through natively without any preprocessing:
- **Currency with symbols:** `$124.50` -> *"one hundred twenty four dollars and fifty cents"*
- **Full dates with year:** `04/21/2026` -> *"April twenty-first twenty twenty-six"*, `2024-10-12` -> *"October twelfth twenty twenty-four"*
- **Clock times with minutes:** `7:05 PM` -> *"seven oh five PM"*, `15:45` -> *"fifteen forty-five"*
- **Standard phone numbers:** `(213) 555-9274` -> automatically grouped and read naturally.
- **Percentages & measurements:** `95%` -> *"ninety-five percent"*, `5kg` -> *"five kilograms"*, `98°F` -> *"ninety-eight degrees Fahrenheit"*.

### 5.2 Known Normalization Gaps (Must Pre-Normalize in Prompt/Pipeline)

Based on `docs/pre-normalization.md`, the following must be pre-expanded:

| Pattern / Gap | Bad Input | Why it Fails | Pre-Normalized Spoken Form |
| :--- | :--- | :--- | :--- |
| **Dates without a year** | `04/21` | Read as fraction or numbers | `April 21st` |
| **Month and year alone** | `07/2025` | Ambiguous division | `July 2025` |
| **Bare hours with meridiem** | `3pm` / `3 pm` | May read awkwardly | `3:00pm` |
| **Decade references** | `1990s` | Reads as "nineteen hundreds" | `the nineteen nineties` |
| **Financial quarters / periods** | `Q1 2025`, `1H 2024` | May mispronounce | `first quarter twenty twenty-five` |
| **Non-dollar shorthand** | `€900K`, `£2M` | Fails on scale word | `900 thousand euros`, `2 million pounds` |
| **Large unformatted numbers** | `10000000` | Reads digit-by-digit | `10,000,000` or `10 million` |
| **Bare unit 'm'** | `1m` | Reads as "one million" | `1 meter` |
| **Hyphenated numeric ranges** | `10-15` | Hyphen may be literal "minus" | `10 to 15` |

### 5.3 Forced Character-by-Character Reading: `spell()`

- **Syntax:** `spell(...)`
- **Behavior:** Forces letter-by-letter or digit-by-digit pronunciation with natural acoustic grouping (triplets and pairs).
- **Mandatory Use Cases:**
  - Tracking numbers: `spell(1Z9999999999)`
  - Confirmation codes: `spell(XY782K)`
  - Account numbers: `spell(ACC4921)`
  - Mixed alphanumeric IDs: `spell(rf543dc2)`
  - Vanity phone number letters: `1-800-spell(FLOWERS)`
- **Anti-patterns for `spell()`:**
  - Do NOT wrap standard phone numbers (native grouping is superior).
  - Do NOT wrap ordinary words that happen to be capitalized (e.g., `spell(URGENT)`).
  - Avoid dashes inside `spell(...)` or strings—dashes cause unexpected pauses.

---

## 6. Streaming Options & Real-Time Protocols

Rime provides three transport paradigms:

### 6.1 Transport Comparison

| Feature | HTTP Streaming (`POST /v1/rime-tts`) | WebSocket JSON (`/ws3`) | WebSocket Binary (`/ws`) | Server-Sent Events (`Accept: text/event-stream`) |
| :--- | :--- | :--- | :--- | :--- |
| **Model Support** | `coda`, `mistv3`, `mistv2` | `coda`, `mistv3`, `mistv2` | `coda`, `mistv3`, `mistv2` | `mistv2` only |
| **Connection Lifecycle** | One request per utterance | Persistent duplex session | Persistent duplex session | One request per utterance |
| **Input Delivery** | Full text upfront | Incremental text stream | Raw text buffer | Full text upfront |
| **Audio Framing** | Raw chunked byte stream | Base64 JSON chunks | Headerless binary | Base64 SSE events |
| **Word Timestamps** | ❌ None | ✅ `timestamps` event | ❌ None | ❌ None |
| **Context IDs** | ❌ None | ✅ Carried in events | ❌ None | ❌ None |
| **Cancellation / Interruption** | Close HTTP connection | Send `{"operation": "clear"}` | Socket close | Close HTTP connection |
| **Best Used For** | Server-to-server synthesis, complete recaps | Multi-turn dialog, live voice agents | Low-overhead embedded | Browser EventSource |

### 6.2 Supported Audio Codecs & Encodings

| Codec / Container | HTTP `Accept` Header | WebSocket `audioFormat` | Native Rate | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Opus (WebM)** | `audio/webm;codecs=opus` | `webm` | 24 kHz | Default WebRTC recommendation; minimal bandwidth. |
| **Opus (OGG)** | `audio/ogg;codecs=opus` | `ogg` | 24 kHz | Open container streaming. |
| **MP3** | `audio/mpeg` | `mp3` | 24 kHz | Universal player compatibility. |
| **WAV (PCM)** | `audio/wav` | `wav` | 24 kHz / 22.05 kHz | Uncompressed RIFF container. |
| **Headerless Linear PCM** | `audio/L16` | `pcm` | 24 kHz | 16-bit little-endian linear samples. |
| **G.711 μ-law** | `audio/PCMU` | `mulaw` | **8 kHz** | **Standard telephony codec**. Zero-transcode for PSTN/SIP. |

### 6.3 Interruption & Control Operations (`/ws3`)

- **`flush` (`{"operation": "flush"}`):** Forces synthesis of the buffered text immediately.
- **`clear` (`{"operation": "clear"}`):** Drops pending buffers without synthesis (critical if the agent clicks "Skip Recap").
- **`eos` (`{"operation": "eos"}`):** Synthesizes remaining buffer, fires `done`, and cleanly closes connection.

---

## 7. Latency Considerations & Telephony Optimization

For Continuum, audio latency is defined as **Time-to-First-Audio (TTFA)** from the moment the dropped call reconnection is detected to the first audio packet arriving at the agent's headset.

### 7.1 Key Factors Influencing End-to-End Latency

```
Reconnection Detected
       │
       ▼ [~50-150ms]  Brain / Memory Query & Freshness Check
       │
       ▼ [~200-400ms] LLM Fast-Model Recap Generation (e.g. Flash)
       │
       ▼ [~25-50ms]   Network Transit to Rime Endpoint
       │
       ▼ [~96ms]      Rime Coda Engine TTFA (Inference)
       │
       ▼ [~5ms]       Audio Chunk Handed to LiveKit Private Track
═════════════════════════════════════════════════════════════════
Total End-to-End: ~400–700ms (Well before the customer says "Hello?")
```

### 7.2 Practical Latency Optimizations for Continuum

1. **Regional Network Routing:**
   - Route traffic to `us-east` or `us-west` matching the cluster location. Transcontinental ping adds 60–85ms; co-located regional routing takes 5–25ms.
2. **Chunked Stream Consumption:**
   - Never wait for `response.content` or the full audio buffer before publishing to the LiveKit track. Stream 4096-byte chunks directly to the private audio frame pump.
3. **Pipelining LLM Generation & TTS:**
   - When generating longer summaries, stream the LLM tokens to Rime `/ws3` with `segment=bySentence`. Rime begins synthesizing the first sentence while the LLM is still drafting the second sentence.
4. **Telephony Sampling Rate Matching:**
   - If broadcasting over SIP/PSTN bridges, requesting `audio/PCMU` at `8000 Hz` bypasses heavy server-side resampling and shrinks bandwidth by over 60%. For internal LiveKit WebRTC tracks, 24kHz Opus (`audio/webm;codecs=opus` or `audio/mpeg`) yields studio-quality voice.
5. **Pre-Normalized Input:**
   - Sending clean, pre-normalized text ensures Rime does not hit syntax fallbacks or ambiguity checks.

---

## 8. Strategic Blueprint for Continuum

### 8.1 Architectural Guardrails (Hard Rules Compliance)

1. **Dual-Track Invariant:**
   - The recap audio streams **exclusively** to `settings.private_track_id`. The customer track must never receive recap frames.
2. **TTS Exclusivity:**
   - Rime API is the sole TTS engine. No fallbacks to local speech synthesis.
3. **Credential Isolation:**
   - `RIME_API_KEY` loaded strictly from `settings.rime_api_key`.

### 8.2 Recommended Configuration Matrix

| Parameter | Selected Value | Justification |
| :--- | :--- | :--- |
| **Model** | `coda` | Highest naturalness, conversational phrasing, artifact-free whisper quality. |
| **Voice / Speaker** | `eyre` | Female 30–50, calm, soothing, low fatigue for headphones. Fallback: `masonry` (Male). |
| **Transport** | HTTP Chunked Streaming (`/v1/rime-tts`) / `/ws3` | Direct streaming chunk ingestion into LiveKit private track queue. |
| **Audio Format** | `audio/mpeg` (or `audio/webm;codecs=opus`) | High fidelity 24kHz audio for clear headphone listening. |
| **Pacing (`timeScaleFactor`)**| `1.05` | Slightly unhurried (~5% slower) to ensure zero cognitive panic during dropped call reconnection. |
| **Max Sentence Length** | 18 words | Avoids breathless audio; maintains calm rhythm. |
| **Disfluency Profile** | Conversational anchors (`"So,"`, `"Heads up —"`, `"Right now,"`) | Colleagues speaking to colleagues; never robotic announcements. |
| **Code / ID Handling** | `spell(...)` wrapping | Accurate character-by-character clarity for ticket numbers and codes. |

---
*Document prepared for Continuum Voice Architecture. Source of truth: official Rime documentation (August 2026).*
