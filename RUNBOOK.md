# Continuum — Local Runbook

How to start the demo stack by hand. Two processes (no mocks needed):

| Process           | What it is                                                                                              | URL                   |
| ----------------- | ------------------------------------------------------------------------------------------------------- | --------------------- |
| Dashboard backend | FastAPI control surface: Deepgram STT bridge, Gemini recap writer, Rime TTS proxy, SQLite thread memory | http://localhost:8000 |
| Frontend          | Vite dev server (React dashboard)                                                                       | http://localhost:5173 |

Open **http://localhost:5173** in Chrome. The launch screen first asks for the
**test case** you want to run (before any recording):

- **Test case 1 — full recap** (hear the whole recap, then answer)
- **Test case 2 — barge-in** (mic stays hot; interrupt with any pickup phrasing — *"call utha lo"*, *"I know, just pick up the call"* — to auto-answer)
- **Test case 3 — 30s time limit & auto-pickup** (network connects the call after ~30 s of ring; a scripted Z joins under the recap)

Pick one, then press **Start the simulation** — the chosen test case is carried
through the whole run and auto-starts when the callback recap is ready.

**Language model (no switch):** the dashboard copy is English only — the
*voice layer follows the conversation*. The mic transcribes with the Deepgram
Nova-3 Hindi model (`language=hi` — `multi` misdetects Hindi as Spanish), and
the backend romanizes the Devanagari to Latin-script Hinglish ("hello भाई
कैसे हो" → "hello bhai kaise ho"). The recap language is auto-detected from
the call (`RECAP_LANG=auto`): English calls get an English recap on Rime's
`eyre` voice; Hindi / Hinglish calls get Hinglish frames (Latin script) on the
Hindi-accented `nadi` voice. The scripted Z in the auto-pickup test case
speaks the same language as the recap (`cupola` for English, `taru` for
Hinglish) and follows the **Meridian enterprise scenario** — confirming
Basmati rice 1121, copper cathode and Shankar-6 cotton quotes from the live
catalog (`mocks/enterprise`, port 8001).

## What the simulation does now (live, no mocks)

1. **Call 1 — live two-way conversation.** Both sides are real voice input.
   Choose **Record User 1** or **Record User 2**, speak, then **Stop & save turn**.
   Each segment is transcribed live by Deepgram and stored to SQLite in real time.
2. **Drop the call** (interrupted) — the thread memory is extracted and persisted.
3. **Callback — Rime recap.** Gemini writes the summary from the stored turns and
   Rime dictates it (timeScaleFactor 0.78 — a little faster) on the private whisper track.
4. **Barge-in or listen** — interrupt with any pickup phrasing (*"call utha lo"*, *"mujhe pta hai call utha lo"*, *"I know, just pick up the call"*) for auto-answer, or a stop phrase (*"Hold on"*, *"bas karo"*) for stop-only, then record the reconnected call the same way.
5. **Option C — Mock caller · India auto-pickup** (single-presenter test). Pick *Option C*
   (or **Test case 3** on the launch screen): after ~30 s of ring the network connects the call by itself while
   the recap keeps playing. A scripted Z (Rime male voice, ducked low) joins on the caller
   lane so you can still hear the recap, and only your voice is transcribed — the mock lines
   are authored text recorded straight to memory as CALLER turns. When the recap ends you
   go live automatically; both sides land in the thread for the Gemini summary.

---

## Prerequisites (one-time)

```bash
# 1. Python 3.12 venv (LiveKit plugins refuse 3.13+; uv installs 3.12 if needed)
uv python install 3.12
uv venv --python 3.12 .venv

# 2. Install dependencies (includes google-genai for the Gemini summary writer)
uv pip install --python .venv -r requirements.txt

# 3. Environment
cp .env.example .env
# Edit .env — set RIME_API_KEY, DEEPGRAM_API_KEY and GEMINI_API_KEY.
# Keep USE_MOCKS=false. Do NOT export USE_MOCKS in your shell:
# the process env overrides .env in pydantic-settings.

# 4. Frontend deps (node_modules is already committed; only needed if you reinstall)
cd web && pnpm install   # or: npm install
```

---

## Start (two terminals, from the repo root)

```bash
# ── Terminal 1 — dashboard backend (port 8000) ────────────────────────────────
.venv/Scripts/python.exe -m uvicorn dashboard.server:app --port 8000
#   (on macOS/Linux: .venv/bin/python -m uvicorn dashboard.server:app --port 8000)

# ── Terminal 2 — Vite dev server (port 5173) ──────────────────────────────────
cd web
./node_modules/.bin/vite
#   or: pnpm dev   (node_modules is committed, so plain vite works without pnpm)
```

> The demo runs on real providers; the freshness check queries the **Meridian
> enterprise price feed** (mocks/enterprise, port 8001) — the live stand-in data
> source. Start it in a third terminal to re-verify product prices during the
> recap:
>
> ```bash
> # ── Terminal 3 — enterprise price feed + console (port 8001) ────────────────
> python -m mocks.mock_freshness
> # open http://localhost:8001/ → Meridian pricing console; click
> # "Simulate overnight market move" between call one and the callback to
> # demonstrate the freshness catch (price changes get flagged in the recap).
> ```
>
> Without the feed running, freshness checks report facts as unverified and the
> recap simply omits staleness flags.

---

## Verify

```bash
curl http://localhost:8000/health        # {"status":"ok","audio_policy":"private-track-only"}
curl -o /dev/null -w "%{http_code}\n" http://localhost:5173/   # 200
curl http://localhost:8000/api/capabilities
# expect: {"use_mocks":false, "rime":{...} ,"stt":{...}, "llm":{...}, "ready":true}
```

---

## Key .env values

| Variable                   | Purpose                                                         |
| -------------------------- | --------------------------------------------------------------- |
| `RIME_API_KEY`           | Rime TTS (the recap voice — never substituted)                 |
| `DEEPGRAM_API_KEY`       | Live streaming STT for both speakers                            |
| `GEMINI_API_KEY`         | Writes the recap summary (falls back to a heuristic without it) |
| `RIME_TIME_SCALE_FACTOR` | `0.78` — the recap speaks a little faster                    |
| `USE_MOCKS`              | Keep`false` — the demo is fully live                         |

---

## Useful notes

- **Speaker labels:** User 1 records as `USER`, User 2 (Z) as `CALLER` — matching
  the Brain extractor's Speaker enum, so commitments/facts are attributed correctly.
- **Auto-pickup mock knobs:** the ring delay is `AUTO_PICKUP.ringDelayS` and the mock
  caller lines/volumes live under `MOCK_CALLER` in `web/src/sim/config.js`.
- **Faster recap:** per-recap speed comes from the recap payload's
  `time_scale_factor` (STANDARD 0.78 / EXTENDED 0.85); the global default is 0.78.
- **LiveKit transport path** (needs the venv Python 3.12):
  `USE_MOCKS=false .venv/Scripts/python.exe -m modules.transport.main`
- **Tests:**
  ```bash
  USE_MOCKS=true .venv/Scripts/python.exe -m pytest dashboard/ -v
  cd web && ./node_modules/.bin/vitest run
  ```
