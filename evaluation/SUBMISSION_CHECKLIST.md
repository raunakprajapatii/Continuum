# Continuum — Rime Hackathon Submission Package
=================================================

This folder (`evaluation/`) consolidates all materials, evidence, scripts, and formal documentation required for the **Rime Hackathon Submission**.

---

## Submission Checklist (per Rime Hackathon PS § 15)

- [x] **Working Source Code**: Fully implemented modules in `modules/`, `dashboard/`, `web/`, and `shared/`.
- [x] **Rime TTS Sole Spoken Path**: All spoken recaps use Rime API (`coda`, `mist_v2`, `mist_v3`; voices `sol`, `eyre`, `nadi`).
- [x] **Dual-Track Architectural Isolation**: Private LiveKit track (`settings.private_track_id`) is strictly isolated; caller track never hears recap audio.
- [x] **Evidence Document**: [`RIME_EVIDENCE.md`](RIME_EVIDENCE.md) documenting the hard voice claims, test procedures, pass criteria, results, limitations, and reproducible commands.
- [x] **Automated Acceptance Suite**: 65/65 tests passing via `pytest evaluation/ -v`.
- [x] **Configuration Hygiene**: Clean `.env.example` with zero credentials or secrets committed.
- [x] **Demo Video Script**: [`Continuum_Demo_Website_Script.pdf`](Continuum_Demo_Website_Script.pdf) outlining the 4–5 minute live presentation.
- [x] **Architecture Blueprint**: [`Continuum_Rime_Hackathon_Blueprint.pdf`](Continuum_Rime_Hackathon_Blueprint.pdf) detailing system design.
- [x] **Challenge Specification**: [`Rime PS (1).pdf`](Rime%20PS%20(1).pdf) problem statement reference.

---

## Quick Links to Key Files in this Folder

| File | Description |
|------|-------------|
| [`RIME_EVIDENCE.md`](RIME_EVIDENCE.md) | **Primary Evidence Artifact**: Acceptance tests, measured results, limitations, and reproducible test runs. |
| [`Continuum_Demo_Website_Script.pdf`](Continuum_Demo_Website_Script.pdf) | Step-by-step 4–5 minute video demonstration script. |
| [`Continuum_Rime_Hackathon_Blueprint.pdf`](Continuum_Rime_Hackathon_Blueprint.pdf) | System architecture, track separation invariants, and module contracts. |
| [`Rime PS (1).pdf`](Rime%20PS%20(1).pdf) | Official Rime Hackathon Problem Statement & Judging Rubric. |
| [`artifacts/`](artifacts/) | Committed JSON test verification artifacts (latency, zero caller impact, context fencing, freshness catch, interruptibility, fallback whisper). |
| [`run_voice_cases.py`](run_voice_cases.py) | Standalone voice runner verifying Rime endpoints and speed alpha controls. |

---

## Running the Evaluation Suite

```bash
# Run all acceptance and unit tests
USE_MOCKS=true pytest evaluation/ -v

# Run individual hard voice claim tests
pytest evaluation/test_pre_answer_latency.py -v
pytest evaluation/test_zero_caller_impact.py -v
pytest evaluation/test_context_fencing.py -v
pytest evaluation/test_freshness_catch.py -v
pytest evaluation/test_interruptibility.py -v
pytest evaluation/test_fallback_whisper.py -v
```
