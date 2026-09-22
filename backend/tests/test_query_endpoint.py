from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.semantic_catalog.models import ColumnMetadata, DomainCatalog, RelationshipMetadata, TableMetadata


@pytest.fixture(autouse=True)
def _disable_intent_enhancer(monkeypatch):
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", False)


class FakeExecutor:
    def execute(self, sql: str):
        return {
            "columns": ["STATUS_FLAG"],
            "rows": [{"STATUS_FLAG": "OK"}],
            "row_count": 1,
            "limited": True,
        }


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



def test_query_endpoint_with_metadata(monkeypatch):
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", True)
    monkeypatch.setattr("app.api.routes_query.settings.query_dry_run_default", False)
    monkeypatch.setattr("app.api.routes_query.SQLExecutor", lambda: FakeExecutor())

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": False})
    assert response.status_code == 200
    assert response.json()["row_count"] == 1



def test_query_endpoint_without_metadata(monkeypatch):
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_domains", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_tables", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_relationships", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_examples", lambda self: {})

    client = TestClient(app)
    payload = {
        "question": "Muestrame estado",
        "user_id": "usuario_demo",
    }
    response = client.post("/query", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Semantic catalog is not ready for query generation."



def test_query_does_not_call_openrouter_when_catalog_not_ready(monkeypatch):
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
                allowed_for_query=False,
                columns=[ColumnMetadata(name="STATUS_FLAG", type="varchar", allowed_for_select=True)],
            )
        ],
    )
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_relationships", lambda self: [])
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_examples", lambda self: {"domain_alpha": []})

    called = {"classifier": False, "generator": False}

    async def fail_classifier(self, question, domains):
        called["classifier"] = True
        raise AssertionError("classifier should not be called")

    async def fail_generator(self, question, retrieval):
        called["generator"] = True
        raise AssertionError("generator should not be called")

    monkeypatch.setattr("app.api.routes_query.DomainClassifier.classify", fail_classifier)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fail_generator)

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado", "user_id": "u1"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Semantic catalog is not ready for query generation."
    assert called["classifier"] is False
    assert called["generator"] is False



@pytest.mark.parametrize("max_rows", [0, 500])
def test_query_dry_run_true_does_not_call_executor(monkeypatch, max_rows):
    monkeypatch.setattr("app.api.routes_query.settings.db_max_rows", max_rows)
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", True)

    class FailingExecutor:
        def execute(self, sql):
            raise AssertionError("executor should not be called")

    monkeypatch.setattr("app.api.routes_query.SQLExecutor", lambda: FailingExecutor())

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": True})
    body = response.json()
    assert response.status_code == 200
    assert body["execution_skipped"] is True
    assert body["execution_skip_reason"] == "dry_run=true"
    assert body["generated_sql"].lower().startswith("select")
    expected = "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"
    if max_rows:
        expected += " FETCH FIRST 500 ROWS ONLY"
    assert body["validated_sql"].upper() == expected



def test_query_allow_execution_false_blocks_executor(monkeypatch):
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", False)

    class FailingExecutor:
        def execute(self, sql):
            raise AssertionError("executor should not be called")

    monkeypatch.setattr("app.api.routes_query.SQLExecutor", lambda: FailingExecutor())

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": False})
    assert response.status_code == 200
    assert response.json()["execution_skip_reason"] == "QUERY_ALLOW_EXECUTION=false"



def test_query_preview_never_calls_executor(monkeypatch):
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", True)

    class FailingExecutor:
        def execute(self, sql):
            raise AssertionError("executor should not be called")

    monkeypatch.setattr("app.api.routes_query.SQLExecutor", lambda: FailingExecutor())

    client = TestClient(app)
    response = client.post("/query/preview", json={"question": "estado actual", "user_id": "u1", "dry_run": False})
    assert response.status_code == 200
    assert response.json()["execution_skipped"] is True



def test_prompt_not_exposed_by_default(monkeypatch):
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_include_llm_prompt_in_debug", False)

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": True})
    assert response.status_code == 200
    assert response.json()["debug_prompt"] is None



def test_prompt_exposed_only_in_development(monkeypatch):
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_include_llm_prompt_in_debug", True)
    monkeypatch.setattr("app.api.routes_query.settings.app_env", "development")

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": True})
    assert response.status_code == 200
    assert response.json()["debug_prompt"] is not None

    monkeypatch.setattr("app.api.routes_query.settings.app_env", "prod")
    response_prod = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": True})
    assert response_prod.status_code == 200
    assert response_prod.json()["debug_prompt"] is None


@pytest.mark.parametrize("max_rows", [0, 500])
def test_pipeline_unchanged_when_intent_enhancer_disabled(monkeypatch, max_rows):
    monkeypatch.setattr("app.api.routes_query.settings.db_max_rows", max_rows)
    async def fake_generate(self, question, retrieval):
        return "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"

    async def fail_enhance(self, question):
        raise AssertionError("intent enhancer should not be called when disabled")

    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fail_enhance)

    client = TestClient(app)
    response = client.post("/query", json={"question": "estado actual", "user_id": "u1", "dry_run": True})
    assert response.status_code == 200
    expected = "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"
    if max_rows:
        expected += " FETCH FIRST 500 ROWS ONLY"
    assert response.json()["validated_sql"].upper() == expected


def test_invalid_clarification_answer_keeps_requires_confirmation(monkeypatch):
    _mock_catalog(monkeypatch)
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)

    async def fake_enhance(self, question):
        from app.intent_enhancer.models import EnhancedIntentResult

        return EnhancedIntentResult(
            original_question=question,
            enhanced_question=question,
            ambiguity_detected=True,
            clarification_questions=["activos aplica a clientes o a medidores?"],
            detected_entities=["clientes"],
            detected_filters=["activos"],
            resolved_entities=["clientes"],
            resolved_filters=[],
            unresolved_ambiguities=["activos => cliente o medidor"],
            confidence=0.88,
            requires_user_confirmation=True,
        )

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)
    client = TestClient(app)
    response = client.post(
        "/query/preview",
        json={"question": "usuarios activos", "user_id": "u1", "clarification_answer": "no-se"},
    )
    assert response.status_code == 200
    assert response.json()["requires_user_confirmation"] is True


def test_clarification_answer_clientes_continues_and_preserves_cardinality_sql(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_domains",
        lambda self: [DomainCatalog(name="medidores", description="d", keywords=["medidores"])],
    )
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_tables",
        lambda self: [
            TableMetadata(schema="SAC", name="MEDIDORES", description="t", domain="medidores", columns=[ColumnMetadata(name="MEDIDOR_ID", type="number"), ColumnMetadata(name="CLIENTE_ID", type="number"), ColumnMetadata(name="ESTADO", type="varchar")]),
            TableMetadata(schema="SAC", name="CLIENTES", description="t", domain="medidores", columns=[ColumnMetadata(name="CLIENTE_ID", type="number"), ColumnMetadata(name="MUNICIPIO", type="number"), ColumnMetadata(name="ESTADO_CLIENTE", type="number")]),
            TableMetadata(schema="SAC", name="MUNICIPIOS", description="t", domain="medidores", columns=[ColumnMetadata(name="MUNICIPIO", type="number"), ColumnMetadata(name="DESCRIPCION", type="varchar")]),
            TableMetadata(schema="SAC", name="MULTITABLA", description="t", domain="medidores", columns=[ColumnMetadata(name="CODIGO_NUM", type="number"), ColumnMetadata(name="TABLA", type="varchar"), ColumnMetadata(name="DESCRIPCION", type="varchar")]),
        ],
    )
    monkeypatch.setattr(
        "app.api.routes_query.SemanticCatalogLoader.load_relationships",
        lambda self: [
            RelationshipMetadata(
                left_table="SAC.MEDIDORES",
                left_column="CLIENTE_ID",
                right_table="SAC.CLIENTES",
                right_column="CLIENTE_ID",
            ),
            RelationshipMetadata(
                left_table="SAC.CLIENTES",
                left_column="MUNICIPIO",
                right_table="SAC.MUNICIPIOS",
                right_column="MUNICIPIO",
            ),
        ],
    )
    monkeypatch.setattr("app.api.routes_query.SemanticCatalogLoader.load_examples", lambda self: {"medidores": []})
    monkeypatch.setattr("app.api.routes_query.settings.enable_intent_enhancer", True)

    async def fake_enhance(self, question):
        from app.intent_enhancer.models import EnhancedIntentResult

        return EnhancedIntentResult(
            original_question=question,
            enhanced_question=question,
            ambiguity_detected=True,
            clarification_questions=["activos aplica a clientes o a medidores?"],
            detected_entities=["clientes", "medidores", "armenia"],
            detected_filters=["retirados", "activos"],
            resolved_entities=["clientes", "municipio Armenia", "medidores"],
            resolved_filters=["MED.ESTADO='R'"],
            unresolved_ambiguities=["activos => cliente o medidor"],
            confidence=0.88,
            requires_user_confirmation=True,
        )

    async def fake_generate(self, question, retrieval):
        assert "CLI_ESTADO" in question
        return (
            "SELECT COUNT(*) AS TOTAL FROM ( "
            "SELECT C.CLIENTE_ID "
            "FROM SAC.MEDIDORES MED "
            "JOIN SAC.CLIENTES C ON MED.CLIENTE_ID = C.CLIENTE_ID "
            "JOIN SAC.MUNICIPIOS M ON C.MUNICIPIO = M.MUNICIPIO "
            "JOIN SAC.MULTITABLA MT ON C.ESTADO_CLIENTE = MT.CODIGO_NUM "
            "WHERE MED.ESTADO='R' "
            "AND UPPER(TRIM(M.DESCRIPCION)) = UPPER(TRIM('ARMENIA')) "
            "AND MT.TABLA = 'CLI_ESTADO' "
            "AND UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('ACTIVO')) "
            "GROUP BY C.CLIENTE_ID "
            "HAVING COUNT(MED.MEDIDOR_ID) > 2 "
            ") Q"
        )

    monkeypatch.setattr("app.api.routes_query.IntentEnhancer.enhance", fake_enhance)
    monkeypatch.setattr("app.api.routes_query.SQLGenerator.generate", fake_generate)
    monkeypatch.setattr("app.api.routes_query.settings.query_allow_execution", False)
    client = TestClient(app)
    response = client.post(
        "/query",
        json={
            "question": "cantidad de usuarios de armenia activos con mas de dos medidores retirados",
            "user_id": "u1",
            "dry_run": True,
            "clarification_answer": "clientes",
        },
    )
    body = response.json()
    assert response.status_code == 200
    sql = body["validated_sql"].upper()
    assert "SELECT COUNT(*) AS TOTAL FROM (" in sql
    assert "MED.ESTADO='R'" in sql
    assert "MT.TABLA = 'CLI_ESTADO'" in sql
    assert "HAVING COUNT(MED.MEDIDOR_ID) > 2" in sql
