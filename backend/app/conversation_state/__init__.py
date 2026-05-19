from functools import lru_cache

from app.conversation_state.manager import ConversationStateManager
from app.conversation_state.models import ClarificationAnswerRecord, ClarificationResolution, ConversationState
from app.conversation_state.storage_providers import (
    ConversationStorageProvider,
    InMemoryConversationStorage,
    SQLiteConversationStorage,
    build_conversation_storage_provider,
)
from app.core.config import settings


@lru_cache(maxsize=1)
def get_conversation_state_manager() -> ConversationStateManager:
    storage = build_conversation_storage_provider()
    return ConversationStateManager(storage=storage)


__all__ = [
    "ClarificationAnswerRecord",
    "ClarificationResolution",
    "ConversationState",
    "ConversationStateManager",
    "ConversationStorageProvider",
    "InMemoryConversationStorage",
    "SQLiteConversationStorage",
    "build_conversation_storage_provider",
    "get_conversation_state_manager",
]
