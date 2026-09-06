"""
dashboard/test_sim_api.py
--------------------------
Tests for the interactive demo simulation endpoints exposed by
``dashboard.server`` (capabilities, sim turns/extraction/recap, Rime gating,
barge-in intent classification and the STT websocket policy).

These tests never touch external services:
  - the Thread Memory Store is swapped for an in-memory SQLite store,
  - the FreshnessChecker is replaced with a deterministic stub,
  - Rime endpoints are exercised only when no RIME_API_KEY is configured
    (503 gate — Rime is the only TTS provider, never silently substituted).
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from dashboard import sim_engine
from dashboard.server import app
from modules.brain.store import ThreadMemoryStore
from shared.config import settings
from shared.schemas import (
    FactCheckResult,
    FreshnessResult,
    FreshnessStatus,
)

client = TestClient(app)


class _StubFreshness:
    """Deterministic freshness checker: price_usd is always now $420."""

    async def check(self, recap_request):
        results = [
            FactCheckResult(
                key=fact.key,
                label=fact.label,
                cached_value=fact.value,
                live_value="$420" if fact.key == "price_usd" else fact.value,
                status=(
                    FreshnessStatus.CHANGED
                    if fact.key == "price_usd" and fact.value != "$420"
                    else FreshnessStatus.UNCHANGED
                ),
                checked_at=datetime.now(tz=timezone.utc),
                latency_ms=12,
            )
            for fact in recap_request.facts_to_verify
        ]
        return FreshnessResult(
            request_id=recap_request.request_id,
            thread_id=recap_request.thread_id,
            results=results,
            any_changed=any(r.status == FreshnessStatus.CHANGED for r in results),
            completed_at=datetime.now(tz=timezone.utc),
        )

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _isolated_sim_engine(monkeypatch: pytest.MonkeyPatch):
    """
    Point the sim endpoints at an in-memory store + stub freshness checker so
    tests are isolated from the on-disk continuum.db and localhost:8001.
    """
    store = ThreadMemoryStore(db_path=":memory:")
    brain = sim_engine.BrainService(store=store)
    sim_engine.configure(
        store=store,
        brain=brain,
        freshness=_StubFreshness(),
    )
    yield
    sim_engine.configure(store=None, brain=None, freshness=None, builder=None, tts_client=None)


CALLER_Z = "+14155550199"
SESS_ONE = "sim-test-call-1"
SESS_TWO = "sim-test-call-2"


def _seed_call_one() -> None:
    """Run the demo call-one conversation so a ThreadSummary exists."""
    client.post("/api/sim/reset", json={"caller_id": CALLER_Z, "session_ids": [SESS_ONE, SESS_TWO]})

    turns = [
        ("CALLER", "Hey, it's Z, wanted to follow up on the Q3 numbers."),
        ("USER", "Sure, the unit price we discussed was four hundred dollars."),
        ("USER", "I'll check with finance on volume discounts and get back to you."),
        ("CALLER", "And the ticket number is XYZ-4821, just making sure you got it befo"),
    ]
    for speaker, text in turns:
        response = client.post(
            "/api/sim/turn",
            json={"session_id": SESS_ONE, "speaker": speaker, "text": text},
        )
        assert response.status_code == 202

    response = client.post(
        "/api/sim/call-ended",
        json={
            "session_id": SESS_ONE,
            "caller_id": CALLER_Z,
            "caller_name": "Z",
            "interrupted": True,
        },
    )
    assert response.status_code == 200


# ── Capabilities ───────────────────────────────────────────────────────────────


def test_capabilities_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without a RIME_API_KEY the dashboard reports Rime disabled (mock mode).
    monkeypatch.setattr(settings, "rime_api_key", "YOUR_RIME_API_KEY_HERE")
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["use_mocks"] is True  # .env runs with USE_MOCKS=true in dev/test
    assert set(body["rime"]) == {
        "enabled",
        "model",
        "speaker",
        "language",
        "endpoint",
        "time_scale_factor",
        "private_track_id",
    }
    assert body["rime"]["enabled"] is False  # no key -> Rime gated
    assert body["stt"]["enabled"] is False
    assert "freshness" in body
    assert body["ready"] is False


# ── Rime gating (Rule 2: no silent substitution) ──────────────────────────────


def test_rime_tts_gated_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # A placeholder / empty key must 503 with a clear message — never a silent
    # swap to another TTS provider. Rime works in mock mode only when a real
    # key is configured (Rime stays the only provider).
    monkeypatch.setattr(settings, "rime_api_key", "YOUR_RIME_API_KEY_HERE")
    response = client.post("/api/rime/tts", json={"text": "Heads up — price is now $420."})
    assert response.status_code == 503
    assert "USE_MOCKS" in response.json()["detail"]


def test_private_recap_audio_gated_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rime_api_key", "YOUR_RIME_API_KEY_HERE")
    response = client.post("/api/private-recap-audio")
    assert response.status_code == 503


# ── Sim flow: conversation -> memory -> recap ─────────────────────────────────


def test_sim_full_call_one_to_recap() -> None:
    _seed_call_one()

    # Thread memory persisted
    thread = client.get(f"/api/sim/thread?caller_id={quote(CALLER_Z, safe='')}")
    assert thread.status_code == 200
    summary = thread.json()
    assert summary["caller_name"] == "Z"
    assert summary["is_interrupted"] is True
    fact_values = {f["key"]: f["value"] for f in summary["time_sensitive_facts"]}
    assert fact_values.get("price_usd") == "$400"

    # Reconnect recap (Brain -> freshness -> Rime-formatted text)
    recap = client.post(
        "/api/sim/recap",
        json={"caller_id": CALLER_Z, "session_id": SESS_TWO, "ring_window_s": 25.0},
    )
    assert recap.status_code == 200
    payload = recap.json()
    assert payload["text"]
    assert payload["headline"]
    assert payload["freshness"]["any_changed"] is True
    assert payload["metrics"]["freshness_ms"] >= 0
    assert "$420" in payload["text"] or "Heads up" in payload["text"]


def test_sim_recap_hinglish_language_frames() -> None:
    """
    The recap request accepts a language; "hi" produces HINGLISH frames —
    Hindi written in Latin (Roman) letters mixed with English, never
    Devanagari. Thread-memory content stays as recorded.
    """
    _seed_call_one()

    recap = client.post(
        "/api/sim/recap",
        json={
            "caller_id": CALLER_Z,
            "session_id": SESS_TWO,
            "ring_window_s": 25.0,
            "language": "hi",
        },
    )
    assert recap.status_code == 200
    payload = recap.json()
    assert payload["language"] == "hi"
    assert payload["speaker"] == "nadi", "Hinglish recap must use the Hindi-accent voice (nadi)"
    # Hinglish (Latin-script) frames: freshness flag and next-action framing.
    assert any(
        marker in payload["text"]
        for marker in ("Sun —", "confirm nahi", "Call beech mein cut", "Aapka move", "Sabse zaroori")
    )
    # No Devanagari anywhere in the Hinglish recap.
    assert not any("\u0900" <= ch <= "\u097f" for ch in payload["text"])
    # English is still the default when no language is passed.
    recap_en = client.post(
        "/api/sim/recap",
        json={"caller_id": CALLER_Z, "session_id": SESS_TWO, "ring_window_s": 25.0},
    )
    assert recap_en.status_code == 200
    assert recap_en.json()["language"] == "en"


def test_sim_recap_auto_language_follows_conversation() -> None:
    """
    With no explicit language, the recap follows the language the call was
    actually spoken in: a Hindi/Hinglish thread gets Hinglish frames + the
    Hindi-accented voice, an English thread gets English frames + the default
    whisper voice.
    """
    # ── Hinglish thread → auto 'hi' ──────────────────────────────────────────
    client.post("/api/sim/reset", json={"caller_id": CALLER_Z, "session_ids": [SESS_ONE, SESS_TWO]})
    hinglish_turns = [
        ("CALLER", "Hey, Z bhai yahan se bol raha hai, basmati rice ka quote check karo."),
        ("USER", "Haan theek hai, basmati ab $940 per tonne hai."),
        ("USER", "I'll check with finance aur kal tak confirm kar dunga."),
    ]
    for speaker, text in hinglish_turns:
        response = client.post(
            "/api/sim/turn",
            json={"session_id": SESS_ONE, "speaker": speaker, "text": text},
        )
        assert response.status_code == 202
    response = client.post(
        "/api/sim/call-ended",
        json={"session_id": SESS_ONE, "caller_id": CALLER_Z, "caller_name": "Z", "interrupted": True},
    )
    assert response.status_code == 200

    recap = client.post(
        "/api/sim/recap",
        json={"caller_id": CALLER_Z, "session_id": SESS_TWO, "ring_window_s": 25.0},
    )
    assert recap.status_code == 200
    payload = recap.json()
    assert payload["language"] == "hi", "auto language must follow the Hinglish thread"
    assert payload["speaker"] == "nadi", "Hinglish recap must use the Hindi-accent voice (nadi)"
    # Hinglish frames: interruption note + next-action lead-in are localised.
    assert "Call beech mein cut" in payload["text"]
    assert "Aapka move" in payload["text"]
    assert not any("\u0900" <= ch <= "\u097f" for ch in payload["text"])

    # ── English thread → auto 'en' ───────────────────────────────────────────
    _seed_call_one()
    recap_en = client.post(
        "/api/sim/recap",
        json={"caller_id": CALLER_Z, "session_id": SESS_TWO, "ring_window_s": 25.0},
    )
    assert recap_en.status_code == 200
    payload_en = recap_en.json()
    assert payload_en["language"] == "en", "auto language must follow the English thread"
    assert payload_en["speaker"] == "eyre", "English recap must use the default whisper voice (eyre)"
    assert "Your move" in payload_en["text"]


def test_sim_recap_context_keeps_recap_substantive() -> None:
    """
    The recap carries the extracted context (what was actually discussed), so
    an interrupted short call never collapses into just "call got cut" + "last
    line" — the substance and the freshness flag are both spoken.
    """
    _seed_call_one()
    recap = client.post(
        "/api/sim/recap",
        json={"caller_id": CALLER_Z, "session_id": SESS_TWO, "ring_window_s": 25.0},
    )
    assert recap.status_code == 200
    payload = recap.json()
    # Real spoken content from the call survives into the recap text...
    assert "four hundred dollars" in payload["text"], "context must carry the call's substance"
    # ...the freshness flag still fires...
    assert "Heads up" in payload["text"] or "$420" in payload["text"]
    # ...and the interruption note does not crowd out the substance.
    assert "mid-sentence" in payload["text"] or "dropped" in payload["text"]


def test_sim_call_ended_without_turns_is_409() -> None:
    client.post(
        "/api/sim/reset",
        json={"caller_id": CALLER_Z, "session_ids": [SESS_ONE]},
    )
    response = client.post(
        "/api/sim/call-ended",
        json={"session_id": SESS_ONE, "caller_id": CALLER_Z, "interrupted": True},
    )
    assert response.status_code == 409


def test_sim_recap_without_thread_is_404() -> None:
    client.post(
        "/api/sim/reset",
        json={"caller_id": "+19999999999", "session_ids": [SESS_ONE]},
    )
    response = client.post(
        "/api/sim/recap",
        json={"caller_id": "+19999999999", "session_id": SESS_TWO, "ring_window_s": 20.0},
    )
    assert response.status_code == 404


def test_sim_bad_speaker_rejected() -> None:
    response = client.post(
        "/api/sim/turn",
        json={"session_id": SESS_ONE, "speaker": "ROBOT", "text": "beep"},
    )
    assert response.status_code == 422


# ── Barge-in intent classification (action vs generic stop) ───────────────────


def test_barge_intent_action_auto_answer() -> None:
    response = client.post(
        "/api/sim/barge-intent",
        json={"text": "I know, just pick up the call"},
    )
    assert response.status_code == 200
    assert response.json()["intent"] == "ANSWER_CALL"


@pytest.mark.parametrize(
    "text",
    [
        # The command is not one fixed sentence — any Hinglish/Hindi/English
        # phrasing with a pickup verb must auto-answer (Latin + Devanagari).
        "call utha lo",
        "mujhe pta hai call utha lo",
        "haan, utha lo",
        "call le lo",
        "answer kar do",
        "pick the phone up",
        "कॉल उठा लो",
        "मुझे पता है, कॉल उठा लो",
    ],
)
def test_barge_intent_action_auto_answer_any_phrasing(text: str) -> None:
    response = client.post("/api/sim/barge-intent", json={"text": text})
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "ANSWER_CALL"
    assert body["matched_phrase"]


def test_barge_intent_generic_stop_hold_on() -> None:
    response = client.post("/api/sim/barge-intent", json={"text": "Hold on a second"})
    assert response.status_code == 200
    assert response.json()["intent"] == "DISMISS_RECAP"


@pytest.mark.parametrize(
    "text",
    [
        "skip karo",
        "mujhe pata hai",
        "samajh gaya",
        "ruk ja",
        "मुझे पता है",
    ],
)
def test_barge_intent_generic_stop_hinglish(text: str) -> None:
    response = client.post("/api/sim/barge-intent", json={"text": text})
    assert response.status_code == 200
    assert response.json()["intent"] == "DISMISS_RECAP"


def test_barge_intent_skip() -> None:
    response = client.post("/api/sim/barge-intent", json={"text": "skip, I remember"})
    assert response.status_code == 200
    assert response.json()["intent"] == "DISMISS_RECAP"


@pytest.mark.parametrize(
    "text",
    [
        "the weather is nice today",
        "call kar lo",  # "make the call" — not "pick up"
        "main kal answer karunga",  # "I'll reply tomorrow" — not an answer now
        "सवाल का जवाब दो",  # "answer the question" — no phone context
    ],
)
def test_barge_intent_ambient_ignored(text: str) -> None:
    response = client.post("/api/sim/barge-intent", json={"text": text})
    assert response.status_code == 200
    assert response.json()["intent"] == "IGNORE"


# ── STT websocket policy ──────────────────────────────────────────────────────


def test_stt_websocket_reports_mock_mode_error() -> None:
    with client.websocket_connect("/api/stt/stream?session_id=ws-test") as ws:
        message = ws.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "stt_unavailable"


def test_normalize_speaker_valid() -> None:
    from dashboard.stt_bridge import normalize_speaker

    assert normalize_speaker("USER") == "USER"
    assert normalize_speaker("caller") == "CALLER"
    assert normalize_speaker(None) == "USER"


def test_normalize_speaker_rejects_unknown() -> None:
    from dashboard.stt_bridge import normalize_speaker

    with pytest.raises(ValueError):
        normalize_speaker("ROBOT")
