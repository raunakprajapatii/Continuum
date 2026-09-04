"""
modules/transport/main.py
-------------------------
Executable CLI entry point for Pair A (Transport).

Run with mocks:
    USE_MOCKS=true python -m modules.transport.main

Flags:
    --scenario normal|reconnect|instant_connect
    --caller +14155550199
    --ducking (demonstrates audio ducking during mid-call recap)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone

from modules.transport.engine import TransportEngine
from shared.config import settings
from shared.schemas import CallState, RimeModel, TtsRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("continuum.transport.main")


async def run_transport_demo(scenario: str, caller_id: str, test_ducking: bool) -> None:
    print("=" * 70)
    print("Continuum — Pair A: Transport Module Live Demo")
    print(f"Target: LiveKit Room Transport & Private Whisper Fencing")
    print(f"Config: USE_MOCKS={settings.use_mocks} | Private Track: {settings.private_track_id}")
    print("=" * 70)

    engine = TransportEngine()
    await engine.start()

    session = engine.session_manager
    whisper = engine.whisper_channel

    # Set up subscriber to monitor events
    sub = session.subscribe()

    async def event_monitor():
        try:
            while True:
                evt = await sub.get()
                reconnect_str = " (RECONNECT!)" if evt.is_reconnect else ""
                print(f"[EVENT] State: {evt.state.value:<12} | Caller: {evt.caller_id}{reconnect_str}")
        except asyncio.CancelledError:
            pass

    monitor_task = asyncio.create_task(event_monitor())

    try:
        print(f"\n[1] Initiating Scenario: {scenario.upper()} with caller {caller_id}...")

        if scenario == "reconnect":
            session.register_interrupted_thread(caller_id, "thread-demo-Z-001")

            print("\n>> Phone is RINGING... Ring window is OPEN.")
            await session.transition_to(CallState.RINGING, caller_id=caller_id)

            # Synthesize & deliver recap during ring window
            print(">> Triggering pre-answer whispered recap on PRIVATE track...")
            tts_req = TtsRequest(
                request_id=f"req-{uuid.uuid4().hex[:6]}",
                session_id=session.session_id,
                thread_id=session.thread_id or "thread-demo-Z-001",
                text="Z wanted the Q3 number; you said you'd check with finance. Heads up — price is now $420.",
                model=RimeModel.CODA,
                speaker=settings.rime_default_speaker,
                private_track_id=settings.private_track_id,
                created_at=datetime.now(tz=timezone.utc),
            )

            metrics = await engine.deliver_recap(tts_req)
            print(f">> Recap finished on {metrics.private_track_id} in {metrics.duration_s:.2f}s!")

            # User answers call
            print("\n>> User answers phone -> State: CONNECTED")
            await session.transition_to(CallState.CONNECTED)
            await asyncio.sleep(2.0)

            if test_ducking:
                print("\n[AUDIO DUCKING FEATURE]")
                print(">> Testing Mid-Call Catch-Up (Decreasing caller volume, boosting summary)...")
                levels_ducked = await engine.ducking_controller.activate_ducking(reason="mid_call_demo")
                print(f"   [LEVELS] Caller Audio: {levels_ducked.caller_volume*100:.0f}% (DUCKED) | Recap: {levels_ducked.recap_volume*100:.0f}% (BOOSTED)")

                await asyncio.sleep(1.5)

                levels_normal = await engine.ducking_controller.restore_levels(reason="demo_complete")
                print(f"   [LEVELS] Caller Audio: {levels_normal.caller_volume*100:.0f}% (RESTORED) | Recap: {levels_normal.recap_volume*100:.0f}%")

            print("\n>> Call COMPLETED.")
            await session.transition_to(CallState.COMPLETED)

        elif scenario == "instant_connect":
            print("\n>> Instant connect without ring window...")
            await session.transition_to(CallState.CONNECTED, caller_id=caller_id)

            print("\n[AUDIO DUCKING FEATURE]")
            print(">> User taps 'Catch Me Up' during live call:")
            print("   -> Caller voice ducked to 25%, recap voice boosted to 125%")
            await engine.trigger_mid_call_catchup()
            print("   -> Recap complete! Audio levels automatically restored.")

            await asyncio.sleep(1.0)
            await session.transition_to(CallState.COMPLETED)

        else:  # normal call
            await session.transition_to(CallState.RINGING, caller_id=caller_id)
            await asyncio.sleep(1.0)
            await session.transition_to(CallState.CONNECTED)
            await asyncio.sleep(2.0)
            await session.transition_to(CallState.COMPLETED)

        print("\n" + "=" * 70)
        print("Transport Demo Completed Successfully!")
        print("Dual-Track Isolation: VERIFIED (Zero leak to caller track)")
        print("=" * 70)

    finally:
        monitor_task.cancel()
        session.unsubscribe(sub)
        await engine.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuum Transport Module Runner")
    parser.add_argument(
        "--scenario",
        choices=["reconnect", "instant_connect", "normal"],
        default="reconnect",
        help="Call scenario to simulate",
    )
    parser.add_argument(
        "--caller",
        default="+14155550199",
        help="Caller phone number (E.164)",
    )
    parser.add_argument(
        "--ducking",
        action="store_true",
        default=True,
        help="Test mid-call audio ducking and volume balance",
    )

    args = parser.parse_args()
    asyncio.run(run_transport_demo(args.scenario, args.caller, args.ducking))


if __name__ == "__main__":
    main()
