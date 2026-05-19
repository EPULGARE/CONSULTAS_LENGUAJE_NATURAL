from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.conversation_state import get_conversation_state_manager
from app.intent_enhancer import EnhancedIntentResult
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


def test_clarification_flow_resumes_conversation_without_manual_flag(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", False)
    monkeypatch.setattr("app.api.routes_query.settings.conversation_state_enabled", True)

    seen = {"enhance_calls": 0, "generate_question": None}

    async def fake_enhance(self, question):
        seen["enhance_calls"] += 1
        return EnhancedIntentResult(
            original_question=question,
            enhanced_question=question,
            ambiguity_detected=True,
            clarification_questions=["'conectados' significa clientes activos o medidores activos?"],
            resolved_entities=["clientes"],
            unresolved_ambiguities=["conectados => cliente o medidor"],
            intent_guardrails=["No inferir conectados"],
            confidence=0.7,
            requires_user_confirmation=True,
        )

    async def fake_generate(self, question, retrieval):
        seen["generate_question"] = question
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
    first_body = first.json()
    assert first.status_code == 200
    assert first_body["requires_user_confirmation"] is True
    assert first_body["conversation_id"]

    second = client.post("/query/preview", json={"question": "clientes", "user_id": "u1"})
    second_body = second.json()
    assert second.status_code == 200
    assert second_body["requires_user_confirmation"] is False
    assert "CLI_ESTADO" in second_body["validated_sql"]
    assert "Activo" in second_body["validated_sql"]
    assert seen["enhance_calls"] == 1
    assert "Interpretar conectados como clientes activos" in seen["generate_question"]


def test_clarification_flow_does_not_break_normal_query(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", False)

    async def fake_generate(self, question, retrieval):
        return "SELECT CLIENTE_ID FROM SAC.CLIENTES"

    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    client = TestClient(app)
    response = client.post("/query/preview", json={"question": "clientes", "user_id": "u1"})
    body = response.json()
    assert response.status_code == 200
    assert body["validated_sql"].upper().startswith("SELECT CLIENTE_ID FROM SAC.CLIENTES")
    assert body["conversation_id"] is None
