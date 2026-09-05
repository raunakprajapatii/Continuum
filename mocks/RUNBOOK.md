# Continuum — Local Runbook

How to start the demo stack by hand. Three processes:

| Process | What it is | URL |
|---------|-----------|-----|
| Mock freshness API | Fake "live data" source for the fact-freshness check | http://localhost:8001 |
| Dashboard backend | FastAPI control surface (sim engine + Deepgram STT bridge + Rime TTS proxy) | http://localhost:8000 |
| Frontend | Vite dev server (React dashboard) | http://localhost:5173 |

Open **http://localhost:5173** in Chrome and press **Start the simulation**.

---

## Prerequisites (one-time)

```bash
# 1. Python 3.12 venv (LiveKit plugins refuse 3.13+; uv installs 3.12 if needed)
uv python install 3.12
uv venv --python 3.12 .venv

# 2. Install dependencies
uv pip install --python .venv -r requirements.txt

# 3. Environment
cp .env.example .env
# Edit .env — set RIME_API_KEY and DEEPGRAM_API_KEY (required for the judged path),
# and USE_MOCKS=false. Do NOT export USE_MOCKS in your shell:
# the process env overrides .env in pydantic-settings.

# 4. Frontend deps (node_modules is already committed; only needed if you reinstall)
cd web && pnpm install   # or: npm install
```

---

## Start (three terminals, from the repo root)

```bash
# ── Terminal 1 — mock freshness data source (port 8001) ────────────────────────
.venv/Scripts/python.exe -m mocks.mock_freshness
#   (on macOS/Linux: .venv/bin/python -m mocks.mock_freshness)

# ── Terminal 2 — dashboard backend (port 8000) ─────────────────────────────────
.venv/Scripts/python.exe -m uvicorn dashboard.server:app --port 8000
#   (.env has USE_MOCKS=false — keep it that way for the real Rime + Deepgram path)

# ── Terminal 3 — Vite dev server (port 5173) ───────────────────────────────────
cd web
./node_modules/.bin/vite
#   or: pnpm dev   (node_modules is committed, so plain vite works without pnpm)
```

---

## Verify

```bash
curl http://localhost:8001/health        # {"status":"ok","service":"mock-freshness-api"}
curl http://localhost:8000/health        # {"status":"ok","audio_policy":"private-track-only"}
curl -o /dev/null -w "%{http_code}\n" http://localhost:5173/   # 200
```

---

## Useful notes

- **Rehearsal mode without API keys:** set `USE_MOCKS=true` in `.env`. The dashboard
  boots but gates Rime + Deepgram; you can still rehearse with typed replies and the
  simulated caller voice.
- **Change the stale price fact mid-demo** (Scenario C: $400 → $420):
  ```bash
  curl -X POST http://localhost:8001/facts/price_usd -H "Content-Type: application/json" -d '{"value":"$420"}'
  ```
- **LiveKit transport path** (needs the venv Python 3.12):
  `USE_MOCKS=false .venv/Scripts/python.exe -m modules.transport.main`
- **Tests:**
  ```bash
  USE_MOCKS=true .venv/Scripts/python.exe -m pytest evaluation/ -v
  cd web && ./node_modules/.bin/vitest run
  ```