# Continuum — Agent Guardrails

This file governs how Antigravity agents work within this repository.
All agents **must** treat every rule below as a hard constraint, not a suggestion.
If an agent cannot satisfy a rule, it must **flag it explicitly** rather than silently working around it.

---

## Architecture

The system is described fully in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).  
The module breakdown and pair ownership are in the [project blueprint](Continuum_Rime_Hackathon_Blueprint.pdf), § 06–08.

The pipeline is:

```
Audio → Transcript → Memory → Recap Text → Speech → Private Track
 (A)       (B)         (C)        (C)          (D)        (A)
```

---

## Hard Rules

### 1 — Dual-track invariant (CRITICAL — judges will test this)

> **The caller-facing audio track and the user-private audio track must be architecturally separate LiveKit tracks. They must never be mixed.**

- Rime TTS audio goes **exclusively** to `settings.private_track_id`.
- No agent may route, copy, or mix recap audio into the caller-facing track for any reason, including testing or debugging.
- If an agent needs to verify audio routing, it must do so by inspecting track metadata — never by audibly playing recap audio on the caller-facing track.

### 2 — Rime is the only TTS provider in the judged path

- All spoken output in the recap flow must use the Rime API.
- Agents must **not** silently substitute `speechSynthesis`, `gTTS`, `pyttsx3`, or any other TTS library "to save time."
- If Rime access is unavailable, the agent must stop and raise an error with a clear message — do not fall back silently.

### 3 — No API keys in code, docs, screenshots, or recordings

- All credentials are loaded from environment variables (see `shared/config/settings.py`).
- The `.env` file is gitignored. Use `.env.example` for placeholders.
- If an agent generates code that references a credential, it must use `settings.<field>` — never a string literal.

### 4 — Rime prompting guide compliance is mandatory

All recap text must pass these rules **before** being sent to Rime synthesis:

1. Lead with the one-sentence headline. No preamble.
2. Every sentence must be under 20 words.
3. Use natural disfluencies sparingly ("so,", "yeah,") — never stacked.
4. Use punctuation as the only prosody tool. No SSML, no `<break>` tags.
5. If a fact has changed, say so plainly and early: `"Heads up — [old] is now [new]."`
6. Wrap any ID, ticket number, or code in `spell(...)`.
7. Never invent details not present in the thread memory.
8. End with the single most useful next action, if one exists.

Agents building the Recap Generator must implement this as a validation step, not just a comment.

### 5 — Schema changes require group notification

- `/shared/schemas/` is owned by all four pairs.
- No agent may merge a change to `/shared/schemas/` without first confirming it with the team.
- Changes to schemas break all mocks immediately — treat them like a breaking API change.

### 6 — Mock flag

- `USE_MOCKS=true` switches all modules to their `/mocks/` equivalents.
- Agents must read `settings.use_mocks` and route accordingly — never hardcode which implementation to use.

---

## Module Ownership

| Directory | Pair | Owners |
|-----------|------|--------|
| `/modules/transport/` | A — Transport | @pair-a-1 @pair-a-2 |
| `/modules/signal/` | B — Signal | @pair-b-1 @pair-b-2 |
| `/modules/brain/` | C — Brain | @pair-c-1 @pair-c-2 |
| `/modules/voice/` | D — Voice & Facts | @pair-d-1 @pair-d-2 |
| `/shared/schemas/` | Everyone | All four pairs |

---

## Suggested Agent Split (Antigravity Manager View)

Spawn these agents in parallel once the shared schemas are merged:

1. **Agent 1** — Thread Memory Store schema + persistence layer (`/modules/brain/`)
2. **Agent 2** — Recap Generator prompt engineering (seed with Rime drop-in voice prompt)
3. **Agent 3** — Mock fact-freshness API + the "changed value overnight" evaluation fixture
4. **Agent 4** — Evaluation harness scripts (force-disconnect, force-reconnect, timing capture)
5. **Agent 5** — Minimal React dashboard for demo legibility

Use a **fast model** (e.g. `gemini-2.0-flash`) for latency-sensitive paths (TL;DR generation).  
Use a **strong model** (e.g. `gemini-2.5-pro`) for freshness-diff reasoning and complex summarisation.
