from pathlib import Path

from app.conversation_state.storage_providers.base import ConversationStorageProvider
from app.conversation_state.storage_providers.memory import InMemoryConversationStorage
from app.conversation_state.storage_providers.sqlite import SQLiteConversationStorage
from app.core.config import settings


def build_conversation_storage_provider() -> ConversationStorageProvider:
    backend = settings.conversation_storage_backend.strip().lower()
    if backend == "sqlite":
        return SQLiteConversationStorage(
            db_path=Path(settings.conversation_sqlite_path),
            ttl_minutes=settings.conversation_state_ttl_minutes,
        )
    return InMemoryConversationStorage(ttl_minutes=settings.conversation_state_ttl_minutes)


__all__ = [
    "ConversationStorageProvider",
    "InMemoryConversationStorage",
    "SQLiteConversationStorage",
    "build_conversation_storage_provider",
]
