from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Thread

from app.conversation_state import ConversationStateManager
from app.conversation_state.models import ConversationState
from app.conversation_state.storage import InMemoryConversationStateStorage
from app.conversation_state.storage_providers.sqlite import SQLiteConversationStorage


def test_conversation_state_manager_create_update_clear():
    manager = ConversationStateManager(storage=InMemoryConversationStateStorage(ttl_minutes=30))
    state = ConversationState(
        conversation_id="conv-1",
        user_id="u1",
        original_question="usuarios conectados",
        enhanced_question="usuarios conectados",
        clarification_questions=["clientes o medidores?"],
        unresolved_ambiguities=["conectados => cliente o medidor"],
    )
    saved = manager.update_state(state)
    assert manager.get_state("conv-1") is not None
    saved.sql_generation_ready = True
    manager.update_state(saved)
    assert manager.get_state("conv-1").sql_generation_ready is True
    manager.clear_state("conv-1")
    assert manager.get_state("conv-1") is None


def test_conversation_state_expiration_ttl():
    storage = InMemoryConversationStateStorage(ttl_minutes=1)
    old_state = ConversationState(
        conversation_id="expired",
        user_id="u1",
        original_question="q",
        enhanced_question="q",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    storage.save(old_state)
    assert storage.expire_old_states() == 1
    assert storage.get("expired") is None


def test_conversation_state_multiple_conversations_isolated():
    storage = InMemoryConversationStateStorage(ttl_minutes=30)
    storage.save(ConversationState(conversation_id="c1", user_id="u1", original_question="q1", enhanced_question="q1"))
    storage.save(ConversationState(conversation_id="c2", user_id="u2", original_question="q2", enhanced_question="q2"))
    assert [item.conversation_id for item in storage.list_pending_for_user("u1")] == ["c1"]
    assert [item.conversation_id for item in storage.list_pending_for_user("u2")] == ["c2"]


def test_conversation_state_storage_thread_safety_basic():
    storage = InMemoryConversationStateStorage(ttl_minutes=30)

    def _writer(index: int) -> None:
        storage.save(
            ConversationState(
                conversation_id=f"conv-{index}",
                user_id="shared-user",
                original_question=f"q-{index}",
                enhanced_question=f"q-{index}",
            )
        )

    threads = [Thread(target=_writer, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    pending = storage.list_pending_for_user("shared-user")
    assert len(pending) == 10


def test_sqlite_conversation_state_persists_between_managers(tmp_path):
    db_path = tmp_path / "conversation_state.sqlite3"
    storage_a = SQLiteConversationStorage(db_path=db_path, ttl_minutes=30)
    manager_a = ConversationStateManager(storage=storage_a)
    state = ConversationState(
        conversation_id="conv-sqlite",
        user_id="u1",
        original_question="usuarios conectados",
        enhanced_question="usuarios conectados",
        clarification_questions=["clientes o medidores?"],
        unresolved_ambiguities=["conectados => cliente o medidor"],
    )
    manager_a.update_state(state)

    storage_b = SQLiteConversationStorage(db_path=db_path, ttl_minutes=30)
    manager_b = ConversationStateManager(storage=storage_b)
    recovered = manager_b.get_state("conv-sqlite")
    assert recovered is not None
    assert recovered.original_question == "usuarios conectados"
    assert recovered.unresolved_ambiguities == ["conectados => cliente o medidor"]


def test_sqlite_conversation_state_cleanup_expired_states(tmp_path):
    db_path = tmp_path / "conversation_state.sqlite3"
    storage = SQLiteConversationStorage(db_path=db_path, ttl_minutes=1)
    expired = ConversationState(
        conversation_id="expired-sqlite",
        user_id="u1",
        original_question="q",
        enhanced_question="q",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    storage.save_state(expired)
    assert storage.cleanup_expired_states() == 1
    assert storage.get_state("expired-sqlite") is None


def test_sqlite_multiple_conversation_isolation(tmp_path):
    db_path = tmp_path / "conversation_state.sqlite3"
    storage = SQLiteConversationStorage(db_path=db_path, ttl_minutes=30)
    storage.save_state(ConversationState(conversation_id="sqlite-1", user_id="u1", original_question="q1", enhanced_question="q1"))
    storage.save_state(ConversationState(conversation_id="sqlite-2", user_id="u2", original_question="q2", enhanced_question="q2"))
    assert [item.conversation_id for item in storage.list_pending_for_user("u1")] == ["sqlite-1"]
    assert [item.conversation_id for item in storage.list_pending_for_user("u2")] == ["sqlite-2"]


def test_sqlite_conversation_state_recovers_corrupt_local_file(tmp_path):
    db_path = tmp_path / "conversation_state.sqlite3"
    db_path.write_text("not a sqlite database", encoding="utf-8")

    storage = SQLiteConversationStorage(db_path=db_path, ttl_minutes=30)
    storage.save_state(
        ConversationState(
            conversation_id="recovered-sqlite",
            user_id="u1",
            original_question="q",
            enhanced_question="q",
        )
    )

    assert storage.get_state("recovered-sqlite") is not None
    assert storage.db_path.exists()
