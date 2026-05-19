from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.conversation_state import get_conversation_state_manager
from app.conversation_state.manager import ConversationStateManager
from app.conversation_state.models import ConversationState
from app.conversation_state.storage_providers.sqlite import SQLiteConversationStorage
from app.main import app
from app.semantic_catalog.models import ColumnMetadata, DomainCatalog, TableMetadata


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    get_conversation_state_manager.cache_clear()
    yield
    get_conversation_state_manager.cache_clear()


def _mock_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_domains",
        lambda self: [DomainCatalog(name="clientes", description="d", keywords=["clientes"])],
    )
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_tables",
        lambda self: [
            TableMetadata(
                schema="SAC",
                name="CLIENTES",
                description="t",
                domain="clientes",
                columns=[ColumnMetadata(name="CLIENTE_ID", type="number"), ColumnMetadata(name="ESTADO_CLIENTE", type="number")],
            ),
            TableMetadata(
                schema="SAC",
                name="MULTITABLA",
                description="t",
                domain="clientes",
                columns=[ColumnMetadata(name="CODIGO_NUM", type="number"), ColumnMetadata(name="TABLA", type="varchar"), ColumnMetadata(name="DESCRIPCION", type="varchar")],
            ),
        ],
    )
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_relationships", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_examples", lambda self: {"clientes": []})


def test_state_resume_with_explicit_conversation_id(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", False)
    monkeypatch.setattr("app.api.routes_query.settings.conversation_state_enabled", True)

    async def fake_enhance(self, question):
        from app.intent_enhancer import EnhancedIntentResult

        return EnhancedIntentResult(
            original_question=question,
            enhanced_question=question,
            ambiguity_detected=True,
            clarification_questions=["'conectados' significa clientes activos o medidores activos?"],
            resolved_entities=["clientes"],
            unresolved_ambiguities=["conectados => cliente o medidor"],
            confidence=0.7,
            requires_user_confirmation=True,
        )

    async def fake_generate(self, question, retrieval):
        return (
            "SELECT COUNT(*) FROM SAC.CLIENTES C "
            "JOIN SAC.MULTITABLA MT ON C.ESTADO_CLIENTE = MT.CODIGO_NUM "
            "WHERE MT.TABLA = 'CLI_ESTADO' "
            "AND UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('Activo'))"
        )

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)

    client = TestClient(app)
    first = client.post("/query/preview", json={"question": "usuarios conectados", "user_id": "u1"})
    conversation_id = first.json()["conversation_id"]
    second = client.post(
        "/query/preview",
        json={"question": "me refiero a clientes", "user_id": "u1", "conversation_id": conversation_id},
    )
    body = second.json()
    assert second.status_code == 200
    assert body["conversation_id"] == conversation_id
    assert body["requires_user_confirmation"] is False

    state = get_conversation_state_manager().get_state(conversation_id)
    assert state is not None
    assert state.sql_generation_ready is True
    assert state.clarification_answers[-1].resolved_as == "conectados => clientes"


def test_state_resume_keeps_pending_when_answer_not_governed(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)
    monkeypatch.setattr("app.api.routes_query.settings.conversation_state_enabled", True)

    async def fake_enhance(self, question):
        from app.intent_enhancer import EnhancedIntentResult

        return EnhancedIntentResult(
            original_question=question,
            enhanced_question=question,
            ambiguity_detected=True,
            clarification_questions=["'conectados' significa clientes activos o medidores activos?"],
            resolved_entities=["clientes"],
            unresolved_ambiguities=["conectados => cliente o medidor"],
            confidence=0.7,
            requires_user_confirmation=True,
        )

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)

    client = TestClient(app)
    first = client.post("/query/preview", json={"question": "usuarios conectados", "user_id": "u1"})
    conversation_id = first.json()["conversation_id"]
    second = client.post(
        "/query/preview",
        json={"question": "no se", "user_id": "u1", "conversation_id": conversation_id},
    )
    body = second.json()
    assert second.status_code == 200
    assert body["requires_user_confirmation"] is True
    assert body["conversation_id"] == conversation_id


def test_state_resume_recovers_between_processes_with_sqlite(tmp_path):
    db_path = tmp_path / "conversation_state.sqlite3"
    storage_a = SQLiteConversationStorage(db_path=db_path, ttl_minutes=30)
    manager_a = ConversationStateManager(storage=storage_a)
    state = manager_a.update_state(
        ConversationState(
            conversation_id="conv-persisted",
            user_id="u1",
            original_question="usuarios conectados",
            enhanced_question="usuarios conectados",
            clarification_questions=["clientes o medidores?"],
            unresolved_ambiguities=["conectados => cliente o medidor"],
        )
    )
    storage_b = SQLiteConversationStorage(db_path=db_path, ttl_minutes=30)
    manager_b = ConversationStateManager(storage=storage_b)
    recovered = manager_b.get_state(state.conversation_id)
    assert recovered is not None
    assert recovered.conversation_id == "conv-persisted"
    assert recovered.user_id == "u1"
