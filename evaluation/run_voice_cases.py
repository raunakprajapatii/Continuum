"""
evaluation/run_voice_cases.py
------------------------------
Pair D — Voice & Facts Test Case Runner

Runs multiple real-world test cases against the Continuum Voice module:
  1. Overnight changed fact (Scenario C — stale price catch: $400 -> $420)
  2. Technical support ticket with spell() wrapping & Mist v2 selection
  3. Fast pre-answer ring window (HEADLINE_ONLY urgency)
  4. Extended call context with mid-sentence interruption note
  5. Resilient degradation during backend outage (HTTP 500 / timeout)
  6. Dual-track isolation security invariant defense

Usage:
    USE_MOCKS=true RIME_API_KEY="" LIVEKIT_URL="wss://mock.livekit.io" LIVEKIT_API_KEY="mock_key" LIVEKIT_API_SECRET="mock_secret" python3 evaluation/run_voice_cases.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone

import httpx

from mocks.mock_brain import make_recap_request
from mocks.mock_freshness import app as mock_freshness_app, set_fact_value
from modules.voice import (
    FreshnessChecker,
    RecapTextBuilder,
    RimePromptValidator,
    RimeTtsClient,
    VoicePipeline,
)
from shared.schemas import (
    Commitment,
    FactCheckResult,
    FreshnessResult,
    FreshnessStatus,
    RecapUrgency,
    RimeModel,
    ThreadSummary,
    TimeSensitiveFact,
)

# Terminal ANSI colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_header(title: str) -> None:
    print(f"\n{CYAN}{BOLD}{'=' * 78}{RESET}")
    print(f"{CYAN}{BOLD}  {title}{RESET}")
    print(f"{CYAN}{BOLD}{'=' * 78}{RESET}")


def print_field(label: str, value: str, color: str = "") -> None:
    print(f"  {DIM}{label:.<26}{RESET} {color}{value}{RESET}")


async def run_scenario_1():
    print_header("Test Case 1: Overnight Changed Fact (Blueprint Scenario C)")
    print("  Context: Caller reconnects after price was updated from $400 to $420.")

    set_fact_value("price_usd", "$420")
    transport = httpx.ASGITransport(app=mock_freshness_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")
    pipeline = VoicePipeline(freshness_checker=FreshnessChecker(client=client))

    req = make_recap_request(urgency=RecapUrgency.STANDARD)
    t0 = time.monotonic()
    tts = await pipeline.run(req)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    validator = RimePromptValidator()
    violations = validator.validate(tts.text)

    print_field("Spoken Whisper Text", f'"{tts.text}"', GREEN)
    print_field("Selected Model", tts.model.value, YELLOW)
    print_field("Private Track ID", tts.private_track_id, GREEN)
    print_field("Freshness Catch Flag", "PASSED ('Heads up' in text)", GREEN)
    print_field("Old & New Values", "PASSED ($400 and $420 present)", GREEN)
    print_field("Rime Rule Violations", str(len(violations)), GREEN if not violations else RED)
    print_field("Execution Latency", f"{elapsed_ms} ms", GREEN)

    assert "Heads up" in tts.text
    assert "$400" in tts.text and "$420" in tts.text
    assert not violations
    assert "caller" not in tts.private_track_id.lower()


async def run_scenario_2():
    print_header("Test Case 2: Support Ticket with spell() & Coda Model")
    print("  Context: Open item contains ticket 'TKT-9941'. Rule 6 requires spell().")

    set_fact_value("price_usd", "$400")
    transport = httpx.ASGITransport(app=mock_freshness_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")
    pipeline = VoicePipeline(freshness_checker=FreshnessChecker(client=client))

    req = make_recap_request(urgency=RecapUrgency.STANDARD)
    req.summary.open_items = ["Follow up on ticket TKT-9941 before noon."]

    t0 = time.monotonic()
    tts = await pipeline.run(req)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    validator = RimePromptValidator()
    violations = validator.validate(tts.text)

    print_field("Spoken Whisper Text", f'"{tts.text}"', GREEN)
    print_field("Spell Wrapping", "spell(TKT-9941)" if "spell(TKT-9941)" in tts.text else "MISSING", GREEN)
    print_field("Selected Model", tts.model.value, YELLOW)
    print_field("Speed Alpha Parameter", str(tts.speed_alpha), GREEN)
    print_field("Rime Rule Violations", str(len(violations)), GREEN if not violations else RED)
    print_field("Execution Latency", f"{elapsed_ms} ms", GREEN)

    assert "spell(TKT-9941)" in tts.text
    # coda is the primary model per RIME_VOICE_DESIGN.md — spell() is native.
    assert tts.model == RimeModel.CODA
    assert not violations


async def run_scenario_3():
    print_header("Test Case 3: Fast Ring Window (Urgency: HEADLINE_ONLY)")
    print("  Context: Short ring window (~2-3 sec). Recap must sprint through headline.")

    set_fact_value("price_usd", "$400")
    transport = httpx.ASGITransport(app=mock_freshness_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")
    pipeline = VoicePipeline(freshness_checker=FreshnessChecker(client=client))

    req = make_recap_request(urgency=RecapUrgency.HEADLINE_ONLY)
    t0 = time.monotonic()
    tts = await pipeline.run(req)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    validator = RimePromptValidator()
    violations = validator.validate(tts.text)

    print_field("Spoken Whisper Text", f'"{tts.text}"', GREEN)
    print_field("Word Count", f"{len(tts.text.split())} words (limit: 20)", GREEN)
    print_field("Time Scale Factor", f"{tts.time_scale_factor} (fast tempo)", YELLOW)
    print_field("Rime Rule Violations", str(len(violations)), GREEN if not violations else RED)
    print_field("Execution Latency", f"{elapsed_ms} ms", GREEN)

    assert len(tts.text.split()) <= 20
    assert tts.time_scale_factor == 0.75
    assert not violations


async def run_scenario_4():
    print_header("Test Case 4: Extended Call Context with Dropped Sentence")
    print("  Context: Urgency is EXTENDED; previous call dropped mid-sentence.")

    transport = httpx.ASGITransport(app=mock_freshness_app)
    client = httpx.AsyncClient(transport=transport, base_url="http://localhost:8001")
    pipeline = VoicePipeline(freshness_checker=FreshnessChecker(client=client))

    req = make_recap_request(urgency=RecapUrgency.EXTENDED)
    req.summary.last_spoken_turn_text = "I think the discount should be-"
    req.summary.is_interrupted = True

    t0 = time.monotonic()
    tts = await pipeline.run(req)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    validator = RimePromptValidator()
    violations = validator.validate(tts.text)

    print_field("Spoken Whisper Text", f'"{tts.text}"', GREEN)
    print_field("Interruption Note Included", "PASSED", GREEN)
    print_field("Time Scale Factor", f"{tts.time_scale_factor} (normal tempo)", YELLOW)
    print_field("Rime Rule Violations", str(len(violations)), GREEN if not violations else RED)
    print_field("Execution Latency", f"{elapsed_ms} ms", GREEN)

    assert "mid-sentence" in tts.text or "dropped" in tts.text
    assert not violations


async def run_scenario_5():
    print_header("Test Case 5: Fact-Check Backend Outage / Timeout Resilience")
    print("  Context: Live freshness backend is down (HTTP 500 error simulated).")

    err_transport = httpx.MockTransport(lambda r: httpx.Response(500))
    err_client = httpx.AsyncClient(transport=err_transport, base_url="http://localhost:8001")
    pipeline = VoicePipeline(freshness_checker=FreshnessChecker(client=err_client))

    req = make_recap_request(urgency=RecapUrgency.STANDARD)
    t0 = time.monotonic()
    tts = await pipeline.run(req)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    validator = RimePromptValidator()
    violations = validator.validate(tts.text)

    print_field("Pipeline Handled Error", "PASSED (Zero crashes / exceptions)", GREEN)
    print_field("Spoken Whisper Text", f'"{tts.text}"', GREEN)
    print_field("Rime Rule Violations", str(len(violations)), GREEN if not violations else RED)
    print_field("Execution Latency", f"{elapsed_ms} ms", GREEN)

    assert tts.text
    assert not violations


async def run_scenario_6():
    print_header("Test Case 6: Dual-Track Isolation Security Invariant")
    print("  Context: AGENTS.md Rule 1 — recap audio must NEVER route to caller track.")

    client = RimeTtsClient(speaker="sol", private_track_id="caller-public-audio")
    req = make_recap_request()

    try:
        client.make_request(req, "Testing audio routing.")
        passed = False
    except ValueError as exc:
        passed = "DUAL-TRACK INVARIANT VIOLATION" in str(exc)

    print_field("Public Caller Track Rejection", "BLOCKED WITH EXCEPTION" if passed else "FAILED", GREEN if passed else RED)
    assert passed, "Caller track was not blocked!"


async def main():
    print(f"\n{BOLD} Continuum Pair D — Voice & Facts Functional Verification Suite{RESET}")
    print(f"{DIM}Running 6 comprehensive scenarios across all components...{RESET}")

    await run_scenario_1()
    await run_scenario_2()
    await run_scenario_3()
    await run_scenario_4()
    await run_scenario_5()
    await run_scenario_6()

    print(f"\n{GREEN}{BOLD}{'=' * 78}{RESET}")
    print(f"{GREEN}{BOLD}  ALL 6 SCENARIOS PASSED WITH ZERO VIOLATIONS!{RESET}")
    print(f"{GREEN}{BOLD}{'=' * 78}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
