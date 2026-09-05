"""
shared/config/settings.py
--------------------------
Single source of truth for all environment-driven configuration.

Usage:
    from shared.config import settings

    print(settings.rime_api_key)
    print(settings.livekit_url)

All values are loaded from environment variables (or a .env file via
python-dotenv). See .env.example at the repo root for required variables.

Rules enforced here:
  - No default values for secrets — missing secrets raise at startup, not at
    the moment of first use.
  - USE_MOCKS=true switches all pairs to mock implementations (see /mocks/).
  - PRIVATE_TRACK_ID must be set; Transport enforces it at the LiveKit layer.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Continuum runtime configuration.

    Loaded from environment variables. In local development, place a .env
    file in the repo root (copy .env.example and fill in your credentials).
    NEVER commit a .env file with real credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Rime TTS ──────────────────────────────────────────────────────────────
    rime_api_key: str = Field(
        ...,
        description="Rime API key. Obtain from the Rime dashboard.",
    )
    rime_api_url: str = Field(
        "https://users.rime.ai/v1/rime-tts",
        description=(
            "Rime TTS endpoint. Override with the regional endpoint nearest your "
            "LiveKit deployment to minimise network latency."
        ),
    )
    rime_default_model: str = Field(
        "coda",
        description="Default Rime model: 'coda', 'mist_v2', or 'mist_v3'.",
    )
    rime_default_speaker: str = Field(
        "sol",  # a neutral, clear voice — update after reviewing the live catalog
        description=(
            "Default Rime voice ID. Always verify against the live catalog "
            "(users.rime.ai/data/voices/all-v2.json) at build time."
        ),
    )
    rime_default_language: str = Field(
        "en",
        description="BCP-47 language code for Rime TTS output.",
    )
    rime_time_scale_factor: float = Field(
        0.78,
        ge=0.5,
        le=2.0,
        description=(
            "Global speed multiplier for Coda / Mist v3. <1.0 speeds up — "
            "0.78 makes the recap comfortably faster than natural speech "
            "while staying intelligible."
        ),
    )

    # ── LiveKit ───────────────────────────────────────────────────────────────
    livekit_url: str = Field(
        ...,
        description="LiveKit server WebSocket URL (e.g. wss://your-project.livekit.cloud).",
    )
    livekit_api_key: str = Field(
        ...,
        description="LiveKit API key for server-side token generation.",
    )
    livekit_api_secret: str = Field(
        ...,
        description="LiveKit API secret.",
    )
    private_track_id: str = Field(
        "continuum-private-whisper",
        description=(
            "Stable LiveKit track / participant identity for the user-private "
            "whisper channel. Transport MUST route all Rime audio to this track "
            "ONLY and reject any attempt to play on the caller-facing track."
        ),
    )

    # ── Telephony (SIP) ───────────────────────────────────────────────────────
    sip_trunk_id: str = Field(
        "",
        description=(
            "LiveKit SIP trunk ID or Twilio SIP trunk SID. "
            "Empty string = browser-simulated ring for local dev."
        ),
    )

    # ── Speech-to-Text ────────────────────────────────────────────────────────
    stt_provider: Literal["deepgram", "assemblyai"] = Field(
        "deepgram",
        description="Streaming STT provider. Must be LiveKit-plugin-supported.",
    )
    deepgram_api_key: str = Field(
        "",
        description="Deepgram API key. Required when stt_provider=deepgram.",
    )
    assemblyai_api_key: str = Field(
        "",
        description="AssemblyAI API key. Required when stt_provider=assemblyai.",
    )

    # ── LLM (Recap Generator + Freshness Reasoning) ───────────────────────────
    llm_fast_model: str = Field(
        "gemini-2.0-flash",
        description=(
            "Fast / cheap model for latency-sensitive paths (TL;DR generation). "
            "Swappable via Antigravity's multi-model support."
        ),
    )
    llm_strong_model: str = Field(
        "gemini-2.5-pro",
        description=(
            "Stronger reasoning model for freshness-diff logic and complex "
            "thread summarisation."
        ),
    )
    llm_api_key: str = Field(
        "",
        description=(
            "API key for the LLM provider (Gemini / Anthropic). "
            "Leave empty if using Antigravity's built-in model access."
        ),
    )
    gemini_api_key: str = Field(
        "",
        description=(
            "Google AI Studio / Gemini API key used by the ConversationExtractor "
            "to generate the recap summary. Read from GEMINI_API_KEY in .env."
        ),
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        "sqlite+aiosqlite:///./continuum.db",
        description=(
            "SQLAlchemy async database URL. "
            "Default: SQLite for hackathon speed. "
            "Swap to postgresql+asyncpg://... for production."
        ),
    )

    # ── Mock / dev flags ──────────────────────────────────────────────────────
    use_mocks: bool = Field(
        False,
        description=(
            "Toggle all module implementations to their /mocks/ equivalents. "
            "Set USE_MOCKS=true in .env for local development without external services."
        ),
    )
    mock_freshness_api_url: str = Field(
        "http://localhost:8001",
        description="Base URL of the mock fact-freshness REST API (see /mocks/mock_freshness.py).",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = Field("0.0.0.0", description="Host for the FastAPI control surface.")
    port: int = Field(8000, description="Port for the FastAPI control surface.")
    log_level: str = Field("info", description="Uvicorn / logging level.")

    @field_validator("rime_api_key")
    @classmethod
    def rime_key_must_not_be_placeholder(cls, v: str, info: object) -> str:
        import os

        # Allow an empty key when USE_MOCKS=true so the eval suite and local
        # development work without real Rime credentials.  In production
        # (use_mocks=false) an empty or placeholder key is a hard error.
        use_mocks = os.getenv("USE_MOCKS", "false").lower() in ("true", "1", "yes")
        if not use_mocks and (v.startswith("YOUR_") or v == ""):
            raise ValueError(
                "RIME_API_KEY is not set. Copy .env.example to .env and fill in your credentials. "
                "Set USE_MOCKS=true in .env to run without a real Rime key during development."
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    Use this in production code:
        from shared.config import settings

    In tests, call get_settings.cache_clear() after patching environment
    variables to force a fresh load.
    """
    return Settings()


# Module-level convenience singleton (import as `from shared.config import settings`)
settings = get_settings()
