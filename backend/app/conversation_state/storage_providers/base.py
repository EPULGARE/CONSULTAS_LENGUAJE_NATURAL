from __future__ import annotations

from abc import ABC, abstractmethod

from app.conversation_state.models import ConversationState


class ConversationStorageProvider(ABC):
    @abstractmethod
    def save_state(self, state: ConversationState) -> ConversationState:
        raise NotImplementedError

    @abstractmethod
    def get_state(self, conversation_id: str) -> ConversationState | None:
        raise NotImplementedError

    @abstractmethod
    def update_state(self, state: ConversationState) -> ConversationState:
        raise NotImplementedError

    @abstractmethod
    def delete_state(self, conversation_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def cleanup_expired_states(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_pending_for_user(self, user_id: str) -> list[ConversationState]:
        raise NotImplementedError
