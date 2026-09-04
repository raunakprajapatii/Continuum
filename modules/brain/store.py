"""
modules/brain/store.py
----------------------
Thread Memory Store for Pair C (Brain).

Persists structured ThreadSummary objects per caller/thread using async SQLite
(aiosqlite). Also provides transient session turn buffering during active calls.

Robustness enhancements:
  - WAL mode + busy_timeout=5000 for concurrent async access
  - Shared in-memory URI support for :memory: testing
  - Defensive deserialization (catches corrupted/schema-divergent JSON)
  - Full CRUD: save, get by thread, get by caller, list, delete
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
import aiosqlite

from shared.config import settings
from shared.schemas import ThreadSummary, TranscriptEvent

logger = logging.getLogger(__name__)


class ThreadMemoryStore:
    """
    Production-grade async SQLite store for ThreadSummary models and session turn buffers.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is not None:
            if db_path == ":memory:":
                # Use shared in-memory database URI
                self.db_path = "file:mem_brain?mode=memory&cache=shared"
                self._is_uri = True
                self._is_memory = True
            else:
                self.db_path = db_path
                self._is_uri = False
                self._is_memory = False
        else:
            db_url = settings.database_url
            if "sqlite" in db_url:
                self.db_path = db_url.split("///")[-1]
            else:
                self.db_path = "./continuum.db"
            self._is_uri = False
            self._is_memory = False

        self._initialized: bool = False
        self._keepalive_conn: Optional[aiosqlite.Connection] = None

    async def _connect(self) -> aiosqlite.Connection:
        """Open a configured SQLite connection with WAL mode and busy timeout."""
        if self._is_memory and self._keepalive_conn is not None:
            return self._keepalive_conn

        db = await aiosqlite.connect(self.db_path, uri=self._is_uri)
        try:
            if not self._is_memory:
                await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA busy_timeout = 5000")
            await db.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass  # Some in-memory setups disallow WAL; safe to ignore

        if self._is_memory:
            self._keepalive_conn = db

        return db

    async def close(self) -> None:
        """Close any persistent keepalive connection."""
        if self._keepalive_conn:
            await self._keepalive_conn.close()
            self._keepalive_conn = None

    async def _release(self, db: aiosqlite.Connection) -> None:
        """Release a connection, keeping it open if in-memory mode."""
        if not self._is_memory:
            await db.close()

    async def init_db(self) -> None:
        """Initialise database schema and indexes."""
        if self._initialized:
            return

        # Ensure directory exists if not an in-memory database
        if not self._is_uri and ":memory:" not in self.db_path:
            path = Path(self.db_path)
            if path.parent and not path.parent.exists():
                path.parent.mkdir(parents=True, exist_ok=True)

        db = await self._connect()
        try:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_summaries (
                    thread_id TEXT PRIMARY KEY,
                    caller_id TEXT NOT NULL,
                    caller_name TEXT,
                    summary_json TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_caller_id
                ON thread_summaries (caller_id)
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS session_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    is_final INTEGER NOT NULL,
                    raw_event_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_id
                ON session_turns (session_id)
                """
            )
            await db.commit()
            self._initialized = True
        finally:
            await self._release(db)

    async def save_summary(self, summary: ThreadSummary) -> None:
        """Persist or replace a ThreadSummary."""
        await self.init_db()
        summary_json = summary.model_dump_json()
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO thread_summaries (
                    thread_id, caller_id, caller_name, summary_json, last_updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    caller_id = excluded.caller_id,
                    caller_name = excluded.caller_name,
                    summary_json = excluded.summary_json,
                    last_updated_at = excluded.last_updated_at
                """,
                (
                    summary.thread_id,
                    summary.caller_id,
                    summary.caller_name,
                    summary_json,
                    summary.last_updated_at.isoformat(),
                ),
            )
            await db.commit()
        finally:
            await self._release(db)

    async def get_summary_by_thread_id(
        self, thread_id: str
    ) -> Optional[ThreadSummary]:
        """Fetch a ThreadSummary by thread_id with defensive error handling."""
        await self.init_db()
        db = await self._connect()
        try:
            async with db.execute(
                "SELECT summary_json FROM thread_summaries WHERE thread_id = ?",
                (thread_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    try:
                        return ThreadSummary.model_validate_json(row[0])
                    except Exception as e:
                        logger.error("Failed to parse ThreadSummary for thread %s: %s", thread_id, e)
                        return None
            return None
        finally:
            await self._release(db)

    async def get_summary_by_caller(
        self, caller_id: str
    ) -> Optional[ThreadSummary]:
        """Fetch the most recently updated ThreadSummary for a caller_id."""
        await self.init_db()
        db = await self._connect()
        try:
            async with db.execute(
                """
                SELECT summary_json FROM thread_summaries
                WHERE caller_id = ?
                ORDER BY last_updated_at DESC
                LIMIT 1
                """,
                (caller_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    try:
                        return ThreadSummary.model_validate_json(row[0])
                    except Exception as e:
                        logger.error("Failed to parse ThreadSummary for caller %s: %s", caller_id, e)
                        return None
            return None
        finally:
            await self._release(db)

    async def list_summaries(self) -> list[ThreadSummary]:
        """List all stored ThreadSummaries ordered by last_updated_at DESC."""
        await self.init_db()
        db = await self._connect()
        try:
            async with db.execute(
                "SELECT summary_json FROM thread_summaries ORDER BY last_updated_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                results: list[ThreadSummary] = []
                for r in rows:
                    try:
                        results.append(ThreadSummary.model_validate_json(r[0]))
                    except Exception as e:
                        logger.warning("Skipping corrupted ThreadSummary record: %s", e)
                return results
        finally:
            await self._release(db)

    async def delete_summary(self, thread_id: str) -> bool:
        """Delete a ThreadSummary by thread_id."""
        await self.init_db()
        db = await self._connect()
        try:
            cursor = await db.execute(
                "DELETE FROM thread_summaries WHERE thread_id = ?",
                (thread_id,),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await self._release(db)

    async def append_turn(self, session_id: str, event: TranscriptEvent) -> None:
        """Buffer a transcript event for an active session."""
        await self.init_db()
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO session_turns (
                    session_id, event_id, speaker, text, start_ms, is_final, raw_event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event.event_id,
                    event.speaker.value,
                    event.text,
                    event.start_ms,
                    1 if event.is_final else 0,
                    event.model_dump_json(),
                ),
            )
            await db.commit()
        finally:
            await self._release(db)

    async def get_session_turns(
        self, session_id: str, final_only: bool = True
    ) -> list[TranscriptEvent]:
        """Retrieve recorded turns for a call session in chronological order."""
        await self.init_db()
        query = "SELECT raw_event_json FROM session_turns WHERE session_id = ?"
        params: list = [session_id]
        if final_only:
            query += " AND is_final = 1"
        query += " ORDER BY start_ms ASC, id ASC"

        db = await self._connect()
        try:
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                results: list[TranscriptEvent] = []
                for r in rows:
                    try:
                        results.append(TranscriptEvent.model_validate_json(r[0]))
                    except Exception as e:
                        logger.warning("Skipping corrupted TranscriptEvent: %s", e)
                return results
        finally:
            await self._release(db)

    async def clear_session_turns(self, session_id: str) -> None:
        """Clear buffered turns for a session after processing."""
        await self.init_db()
        db = await self._connect()
        try:
            await db.execute(
                "DELETE FROM session_turns WHERE session_id = ?",
                (session_id,),
            )
            await db.commit()
        finally:
            await self._release(db)
