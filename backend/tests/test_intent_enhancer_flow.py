from fastapi.testclient import TestClient

from app.intent_enhancer import EnhancedIntentResult
from app.main import app
from app.semantic_catalog.models import ColumnMetadata, DomainCatalog, TableMetadata


def _mock_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_domains",
        lambda self: [DomainCatalog(name="domain_alpha", description="d", keywords=["estado"])],
    )
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_tables",
        lambda self: [
            TableMetadata(
                schema="TEST_SCHEMA",
                name="TEST_TABLE",
                description="table",
                domain="domain_alpha",
                columns=[ColumnMetadata(name="STATUS_FLAG", type="varchar")],
            )
        ],
    )
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_relationships", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_examples", lambda self: {"domain_alpha": []})


def test_query_requires_confirmation_when_intent_is_ambiguous(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)

    async def fake_enhance(self, question):
        return EnhancedIntentResult(
            original_question=question,
            enhanced_question="Cantidad de clientes activos en Armenia",
            ambiguity_detected=True,
            clarification_questions=["conectados significa clientes activos?"],
            detected_entities=["clientes", "armenia"],
            detected_filters=["conectados"],
            resolved_entities=["clientes", "municipio Armenia"],
            resolved_filters=[],
            unresolved_ambiguities=["conectados => cliente o medidor"],
            confidence=0.6,
            requires_user_confirmation=True,
        )

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)

    client = TestClient(app)
    response = client.post("/query/preview", json={"question": "usuarios conectados de armenia", "user_id": "u1"})
    body = response.json()
    assert response.status_code == 200
    assert body["execution_skipped"] is True
    assert body["execution_skip_reason"] == "requires_user_confirmation"
    assert body["requires_user_confirmation"] is True
    assert body["clarification_questions"]


def test_query_uses_enhanced_question_when_auto_accepted(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", False)

    seen = {"question": None}

    async def fake_enhance(self, question):
        return EnhancedIntentResult(
            original_question=question,
            enhanced_question="estado actual de clientes",
            ambiguity_detected=False,
            clarification_questions=[],
            detected_entities=["clientes"],
            detected_filters=["estado"],
            resolved_entities=["clientes"],
            resolved_filters=[],
            unresolved_ambiguities=[],
            confidence=0.99,
            requires_user_confirmation=False,
        )

    async def fake_generate(self, question, retrieval):
        seen["question"] = question
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado cliente", "user_id": "u1", "dry_run": True})
    body = response.json()
    assert response.status_code == 200
    assert seen["question"] == "estado actual de clientes"
    assert body["enhanced_question"] == "estado actual de clientes"
    assert body["requires_user_confirmation"] is False


def test_ambiguous_intent_returns_preliminary_domain_tables_and_pattern(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_domains",
        lambda self: [DomainCatalog(name="medidores", description="d", keywords=["medidores"])],
    )
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_tables",
        lambda self: [
            TableMetadata(schema="SAC", name="MEDIDORES", description="t", domain="medidores", columns=[ColumnMetadata(name="CLIENTE_ID", type="number")]),
            TableMetadata(schema="SAC", name="CLIENTES", description="t", domain="medidores", columns=[ColumnMetadata(name="CLIENTE_ID", type="number")]),
            TableMetadata(schema="SAC", name="MUNICIPIOS", description="t", domain="medidores", columns=[ColumnMetadata(name="MUNICIPIO", type="number")]),
        ],
    )
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_relationships", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_examples", lambda self: {"medidores": []})
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)

    async def fake_enhance(self, question):
        return EnhancedIntentResult(
            original_question=question,
            enhanced_question=question,
            ambiguity_detected=True,
            clarification_questions=["activos aplica a clientes o a medidores?"],
            detected_entities=["clientes", "medidores", "armenia"],
            detected_filters=["retirados"],
            resolved_entities=["clientes", "municipio Armenia", "medidores"],
            resolved_filters=["MED.ESTADO='R'"],
            unresolved_ambiguities=["activos => cliente o medidor"],
            confidence=0.88,
            requires_user_confirmation=True,
        )

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)

    client = TestClient(app)
    response = client.post(
        "/query/preview",
        json={"question": "cantidad de usuarios de armenia activos con mas de dos medidores retirados", "user_id": "u1"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["execution_skip_reason"] == "requires_user_confirmation"
    assert body["detected_domain"] == "medidores"
    assert body["retrieved_tables"]
    assert body["detected_query_pattern"] == "entity_count_with_cardinality_condition"
