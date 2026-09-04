from fastapi.testclient import TestClient

from dashboard.server import app


client = TestClient(app)


def test_dashboard_health_advertises_private_track_policy() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["audio_policy"] == "private-track-only"


def test_dashboard_refuses_audio_payloads() -> None:
    response = client.post(
        "/api/events",
        json={
            "event": "recap.tts_first_audio",
            "thread_id": "z-contact-01",
            "meta": {"audio_bytes": "not-accepted"},
        },
    )

    assert response.status_code == 400


def test_dashboard_accepts_timestamped_metadata_event() -> None:
    response = client.post(
        "/api/events",
        json={
            "event": "thread.match_found",
            "thread_id": "z-contact-01",
            "meta": {"confidence": 1.0},
        },
    )

    assert response.status_code == 202
    assert response.json()["meta"]["confidence"] == 1.0
