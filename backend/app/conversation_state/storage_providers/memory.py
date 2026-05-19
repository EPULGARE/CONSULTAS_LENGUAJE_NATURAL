from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock

from app.conversation_state.models import ConversationState
from app.conversation_state.storage_providers.base import ConversationStorageProvider


class InMemoryConversationStorage(ConversationStorageProvider):
    def __init__(self, *, ttl_minutes: int = 30) -> None:
        self._states: dict[str, ConversationState] = {}
        self._lock = RLock()
        self._ttl = timedelta(minutes=max(ttl_minutes, 1))

    def save_state(self, state: ConversationState) -> ConversationState:
        with self._lock:
            self._states[state.conversation_id] = state.model_copy(deep=True)
            return self._states[state.conversation_id].model_copy(deep=True)

    def save(self, state: ConversationState) -> ConversationState:
        return self.save_state(state)

    def get_state(self, conversation_id: str) -> ConversationState | None:
        with self._lock:
            state = self._states.get(conversation_id)
            if state is None:
                return None
            if self._is_expired(state):
                self._states.pop(conversation_id, None)
                return None
            return state.model_copy(deep=True)

    def get(self, conversation_id: str) -> ConversationState | None:
        return self.get_state(conversation_id)

    def update_state(self, state: ConversationState) -> ConversationState:
        return self.save_state(state)

    def delete_state(self, conversation_id: str) -> None:
        with self._lock:
            self._states.pop(conversation_id, None)

    def delete(self, conversation_id: str) -> None:
        self.delete_state(conversation_id)

    def cleanup_expired_states(self) -> int:
        with self._lock:
            removed = 0
            for conversation_id, state in list(self._states.items()):
                if self._is_expired(state):
                    self._states.pop(conversation_id, None)
                    removed += 1
            return removed

    def expire_old_states(self) -> int:
        return self.cleanup_expired_states()

    def list_pending_for_user(self, user_id: str) -> list[ConversationState]:
        with self._lock:
            pending: list[ConversationState] = []
            for conversation_id, state in list(self._states.items()):
                if self._is_expired(state):
                    self._states.pop(conversation_id, None)
                    continue
                if state.user_id == user_id and not state.sql_generation_ready:
                    pending.append(state.model_copy(deep=True))
            pending.sort(key=lambda item: item.updated_at, reverse=True)
            return pending

    def _is_expired(self, state: ConversationState) -> bool:
        return datetime.now(timezone.utc) - state.updated_at > self._ttl
