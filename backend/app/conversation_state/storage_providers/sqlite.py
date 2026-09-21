from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from app.conversation_state.models import ConversationState
from app.conversation_state.storage_providers.base import ConversationStorageProvider


class SQLiteConversationStorage(ConversationStorageProvider):
    def __init__(self, *, db_path: Path, ttl_minutes: int = 30, recover_corrupt: bool = True) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl = timedelta(minutes=max(ttl_minutes, 1))
        self._recover_corrupt = recover_corrupt
        self._lock = RLock()
        self._ensure_schema()

    def save_state(self, state: ConversationState) -> ConversationState:
        stored = state.model_copy(deep=True)
        expires_at = self._compute_expires_at(stored.updated_at)
        payload_json = json.dumps(stored.model_dump(mode="json"), ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_state (
                    conversation_id,
                    payload_json,
                    created_at,
                    updated_at,
                    expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    stored.conversation_id,
                    payload_json,
                    stored.created_at.isoformat(),
                    stored.updated_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()
        return stored

    def save(self, state: ConversationState) -> ConversationState:
        return self.save_state(state)

    def get_state(self, conversation_id: str) -> ConversationState | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json, expires_at
                FROM conversation_state
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            if row is None:
                return None
            if self._is_expired(row["expires_at"]):
                conn.execute("DELETE FROM conversation_state WHERE conversation_id = ?", (conversation_id,))
                conn.commit()
                return None
            return ConversationState.model_validate(json.loads(row["payload_json"]))

    def get(self, conversation_id: str) -> ConversationState | None:
        return self.get_state(conversation_id)

    def update_state(self, state: ConversationState) -> ConversationState:
        return self.save_state(state)

    def delete_state(self, conversation_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM conversation_state WHERE conversation_id = ?", (conversation_id,))
            conn.commit()

    def delete(self, conversation_id: str) -> None:
        self.delete_state(conversation_id)

    def cleanup_expired_states(self) -> int:
        cutoff = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM conversation_state WHERE expires_at <= ?", (cutoff,))
            conn.commit()
            return int(cursor.rowcount or 0)

    def expire_old_states(self) -> int:
        return self.cleanup_expired_states()

    def list_pending_for_user(self, user_id: str) -> list[ConversationState]:
        cutoff = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM conversation_state WHERE expires_at <= ?", (cutoff,))
            rows = conn.execute(
                """
                SELECT payload_json
                FROM conversation_state
                WHERE expires_at > ?
                ORDER BY updated_at DESC
                """,
                (cutoff,),
            ).fetchall()
        pending: list[ConversationState] = []
        for row in rows:
            state = ConversationState.model_validate(json.loads(row["payload_json"]))
            if state.user_id == user_id and not state.sql_generation_ready:
                pending.append(state)
        return pending

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        try:
            self._create_schema()
        except sqlite3.DatabaseError:
            if not self._recover_corrupt or not self.db_path.exists():
                raise
            if not self._quarantine_database_files():
                self.db_path = self._build_recovered_database_path()
            self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA quick_check")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_state (
                    conversation_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_state_expires_at ON conversation_state(expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_state_updated_at ON conversation_state(updated_at)"
            )
            conn.commit()

    def _quarantine_database_files(self) -> bool:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        targets = [
            self.db_path,
            self.db_path.with_name(f"{self.db_path.name}-journal"),
            self.db_path.with_name(f"{self.db_path.name}-wal"),
            self.db_path.with_name(f"{self.db_path.name}-shm"),
        ]
        for target in targets:
            if not target.exists():
                continue
            backup = target.with_name(f"{target.name}.corrupt.{timestamp}")
            try:
                target.replace(backup)
            except PermissionError:
                return False
        return True

    def _build_recovered_database_path(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        suffix = self.db_path.suffix or ".sqlite3"
        stem = self.db_path.stem if self.db_path.suffix else self.db_path.name
        return self.db_path.with_name(f"{stem}.recovered.{timestamp}{suffix}")

    def _compute_expires_at(self, updated_at: datetime) -> datetime:
        return updated_at + self._ttl

    def _is_expired(self, expires_at_raw: str) -> bool:
        expires_at = datetime.fromisoformat(expires_at_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)
