from pathlib import Path
import shutil
import uuid

import pytest
import yaml

from app.semantic_catalog.models import ColumnMetadata, DomainCatalog, RelationshipMetadata, TableMetadata
from scripts.evaluate_text_to_sql import resolve_output_path
from app.evaluation.evaluator import TextToSQLEvaluator, _sql_contains_semantic
from app.llm.sql_generator import SQLGenerationTrace


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _write_questions(base: Path, questions: list[dict]) -> Path:
    path = base / "questions.yml"
    path.write_text(yaml.safe_dump({"questions": questions}, sort_keys=False), encoding="utf-8")
    return path


def _mock_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
        lambda self: [DomainCatalog(name="domain_alpha", description="d")],
    )
    monkeypatch.setattr(
        "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
        lambda self: [
            TableMetadata(
                schema="TEST_SCHEMA",
                name="TEST_TABLE",
                domain="domain_alpha",
                allowed_for_query=True,
                columns=[
                    ColumnMetadata(name="ID", type="number", allowed_for_select=True),
                    ColumnMetadata(name="STATUS_FLAG", type="varchar", allowed_for_select=True),
                ],
            )
        ],
    )
    monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_relationships", lambda self: [])
    monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"domain_alpha": []})
    monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings", lambda self: [])



def _mock_pipeline(monkeypatch, sql: str):
    async def fake_classify(self, question, domains):
        return "domain_alpha"

    async def fake_generate_with_trace(self, question, retrieval):
        return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

    monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
    monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)



def test_questions_empty_no_break(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT ID FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(root, [])

        evaluator = TextToSQLEvaluator(questions_path=questions_path)
        report = evaluator.evaluate()
        assert report.total_questions == 0
        assert report.failed == 0
    finally:
        _cleanup(root)



def test_questions_approved_false_skipped(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT ID FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "domain_alpha",
                    "question": "estado",
                    "approved": False,
                }
            ],
        )

        evaluator = TextToSQLEvaluator(questions_path=questions_path)
        report = evaluator.evaluate()
        assert report.skipped == 1
        assert report.passed == 0
    finally:
        _cleanup(root)



def test_evaluation_does_not_call_executor(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT ID FROM TEST_SCHEMA.TEST_TABLE")

        def fail_execute(*args, **kwargs):
            raise AssertionError("executor should not be called")

        monkeypatch.setattr("app.sql.executor.SQLExecutor.execute", fail_execute)

        questions_path = _write_questions(
            root,
            [{"id": "q1", "domain": "domain_alpha", "question": "estado", "approved": True}],
        )
        evaluator = TextToSQLEvaluator(questions_path=questions_path)
        report = evaluator.evaluate()
        assert report.passed == 1
        assert len(report.successful_queries) == 1
        assert report.successful_queries[0].generated_sql is not None
    finally:
        _cleanup(root)



def test_expected_tables_missing_generates_failure(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT ID FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "domain_alpha",
                    "question": "estado",
                    "expected_tables": ["TEST_SCHEMA.OTHER_TABLE"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert report.failures[0].missing_expected_tables == ["TEST_SCHEMA.OTHER_TABLE"]
    finally:
        _cleanup(root)



def test_forbidden_tables_detected_generates_failure(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT ID FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "domain_alpha",
                    "question": "estado",
                    "forbidden_tables": ["TEST_SCHEMA.TEST_TABLE"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert report.failures[0].forbidden_tables_found == ["TEST_SCHEMA.TEST_TABLE"]
    finally:
        _cleanup(root)



def test_forbidden_columns_detected_generates_failure(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "domain_alpha",
                    "question": "estado",
                    "forbidden_columns": ["STATUS_FLAG"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert report.failures[0].forbidden_columns_found == ["STATUS_FLAG"]
    finally:
        _cleanup(root)



def test_forbidden_sql_contains_detected_generates_failure(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "domain_alpha",
                    "question": "estado",
                    "forbidden_sql_contains": ["STATUS_FLAG"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert report.failures[0].forbidden_sql_found == ["STATUS_FLAG"]
    finally:
        _cleanup(root)



def test_output_outside_outputs_is_blocked():
    try:
        resolve_output_path("metadata/out.json")
        assert False, "Expected ValueError"
    except ValueError:
        assert True



def test_output_inside_outputs_is_allowed():
    output = resolve_output_path("outputs/text_to_sql_evaluation.json")
    assert str(output).lower().endswith("outputs\\text_to_sql_evaluation.json")


def test_evaluator_does_not_call_intent_enhancer_when_disabled(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        _mock_pipeline(monkeypatch, "SELECT ID FROM TEST_SCHEMA.TEST_TABLE")
        questions_path = _write_questions(
            root,
            [{"id": "q1", "domain": "domain_alpha", "question": "estado", "approved": True}],
        )

        async def fail_enhance(self, question):
            raise AssertionError("intent enhancer should not be called")

        monkeypatch.setattr("app.evaluation.evaluator.IntentEnhancer.enhance", fail_enhance)
        evaluator = TextToSQLEvaluator(questions_path=questions_path, enable_intent_enhancer=False)
        report = evaluator.evaluate()
        assert report.passed == 1
    finally:
        _cleanup(root)


def test_reports_extraction_error_when_llm_returns_no_sql(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)

        async def fake_classify(self, question, domains):
            return "domain_alpha"

        async def fake_generate_with_trace(self, question, retrieval):
            return SQLGenerationTrace(
                raw_llm_response="No puedo responder",
                extracted_sql=None,
                extraction_error="LLM_NO_SQL_FOUND",
            )

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(
            root,
            [{"id": "q1", "domain": "domain_alpha", "question": "estado", "approved": True}],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert report.failures[0].reason == "LLM_NO_SQL_FOUND"
        assert report.failures[0].raw_llm_response == "No puedo responder"
        assert report.failures[0].extraction_error == "LLM_NO_SQL_FOUND"
    finally:
        _cleanup(root)


def test_semantic_fixed_filter_match_accepts_alias(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
            lambda self: [DomainCatalog(name="clientes", description="d")],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
            lambda self: [
                TableMetadata(
                    schema="SAC",
                    name="CLIENTES",
                    domain="clientes",
                    columns=[ColumnMetadata(name="ESTADO_CLIENTE", type="NUMBER", allowed_for_select=True)],
                ),
                TableMetadata(
                    schema="SAC",
                    name="MULTITABLA",
                    domain="clientes",
                    columns=[
                        ColumnMetadata(name="TABLA", type="VARCHAR2", allowed_for_select=True),
                        ColumnMetadata(name="CODIGO_NUM", type="NUMBER", allowed_for_select=True),
                        ColumnMetadata(name="DESCRIPCION", type="VARCHAR2", allowed_for_select=True),
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_relationships",
            lambda self: [
                RelationshipMetadata(
                    left_table="SAC.CLIENTES",
                    left_column="ESTADO_CLIENTE",
                    right_table="SAC.MULTITABLA",
                    right_column="CODIGO_NUM",
                    fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                )
            ],
        )
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"clientes": []})
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings",
            lambda self: [
                {
                    "source_table": "SAC.CLIENTES",
                    "source_column": "ESTADO_CLIENTE",
                    "lookup_table": "SAC.MULTITABLA",
                    "lookup_key": "CODIGO_NUM",
                    "lookup_description": "DESCRIPCION",
                    "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                }
            ],
        )

        async def fake_classify(self, question, domains):
            return "clientes"

        async def fake_generate_with_trace(self, question, retrieval):
            sql = (
                "SELECT MT.DESCRIPCION, COUNT(C.ESTADO_CLIENTE) "
                "FROM SAC.CLIENTES C JOIN SAC.MULTITABLA MT ON C.ESTADO_CLIENTE = MT.CODIGO_NUM "
                "WHERE MT.TABLA = 'CLI_ESTADO' GROUP BY MT.DESCRIPCION"
            )
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "clientes",
                    "question": "estado",
                    "expected_tables": ["SAC.CLIENTES", "SAC.MULTITABLA"],
                    "expected_columns": ["DESCRIPCION"],
                    "expected_sql_contains": ["SAC.MULTITABLA.TABLA = 'CLI_ESTADO'"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.passed == 1
    finally:
        _cleanup(root)


def test_unapproved_parametric_join_is_reported(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
            lambda self: [DomainCatalog(name="clientes", description="d")],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
            lambda self: [
                TableMetadata(
                    schema="SAC",
                    name="CLIENTES",
                    domain="clientes",
                    columns=[ColumnMetadata(name="MUNICIPIO", type="NUMBER", allowed_for_select=True)],
                ),
                TableMetadata(
                    schema="SAC",
                    name="MULTITABLA",
                    domain="clientes",
                    columns=[
                        ColumnMetadata(name="CODIGO_NUM", type="NUMBER", allowed_for_select=True),
                        ColumnMetadata(name="DESCRIPCION", type="VARCHAR2", allowed_for_select=True),
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_relationships",
            lambda self: [
                RelationshipMetadata(
                    left_table="SAC.CLIENTES",
                    left_column="ESTADO_CLIENTE",
                    right_table="SAC.MULTITABLA",
                    right_column="CODIGO_NUM",
                    fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                )
            ],
        )
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"clientes": []})
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings",
            lambda self: [
                {
                    "source_table": "SAC.CLIENTES",
                    "source_column": "ESTADO_CLIENTE",
                    "lookup_table": "SAC.MULTITABLA",
                    "lookup_key": "CODIGO_NUM",
                    "lookup_description": "DESCRIPCION",
                    "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                }
            ],
        )

        async def fake_classify(self, question, domains):
            return "clientes"

        async def fake_generate_with_trace(self, question, retrieval):
            sql = (
                "SELECT MT.DESCRIPCION, COUNT(*) FROM SAC.CLIENTES C "
                "JOIN SAC.MULTITABLA MT ON C.MUNICIPIO = MT.CODIGO_NUM "
                "WHERE MT.TABLA = 'MUNICIPIO' GROUP BY MT.DESCRIPCION"
            )
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(
            root,
            [{"id": "q1", "domain": "clientes", "question": "municipio", "approved": True}],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert "UNAPPROVED_PARAMETRIC_JOIN" in report.failures[0].reason
    finally:
        _cleanup(root)


def test_unapproved_join_path_records_relationship_candidate(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
            lambda self: [DomainCatalog(name="medidores", description="d")],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
            lambda self: [
                TableMetadata(
                    schema="SAC",
                    name="CLIENTES",
                    domain="medidores",
                    columns=[ColumnMetadata(name="CLIENTE_ID", type="NUMBER", allowed_for_select=True)],
                ),
                TableMetadata(
                    schema="SAC",
                    name="PROCESOS",
                    domain="medidores",
                    columns=[ColumnMetadata(name="CODIGO_CUENTA", type="NUMBER", allowed_for_select=True)],
                ),
            ],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_relationships",
            lambda self: [],
        )
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"medidores": []})
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings", lambda self: [])
        monkeypatch.setattr(
            "app.evaluation.evaluator.settings.metadata_path",
            root / "metadata",
        )
        (root / "metadata" / "generated").mkdir(parents=True, exist_ok=True)

        async def fake_classify(self, question, domains):
            return "medidores"

        async def fake_generate_with_trace(self, question, retrieval):
            sql = (
                "SELECT COUNT(*) FROM SAC.CLIENTES C "
                "JOIN SAC.PROCESOS P ON C.CLIENTE_ID = P.CODIGO_CUENTA"
            )
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(
            root,
            [{"id": "q1", "domain": "medidores", "question": "x", "approved": True}],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert "UNAPPROVED_JOIN_PATH" in report.failures[0].reason
        assert report.failures[0].relationship_candidates[0]["to_column"] == "CODIGO_CUENTA"
    finally:
        _cleanup(root)


def test_expected_qualified_column_matches_alias(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
            lambda self: [DomainCatalog(name="clientes", description="d")],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
            lambda self: [
                TableMetadata(
                    schema="SAC",
                    name="CLIENTES",
                    domain="clientes",
                    columns=[ColumnMetadata(name="MUNICIPIO", type="NUMBER", allowed_for_select=True)],
                ),
                TableMetadata(
                    schema="SAC",
                    name="MUNICIPIOS",
                    domain="clientes",
                    columns=[
                        ColumnMetadata(name="MUNICIPIO", type="NUMBER", allowed_for_select=True),
                        ColumnMetadata(name="DESCRIPCION", type="VARCHAR2", allowed_for_select=True),
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_relationships",
            lambda self: [
                RelationshipMetadata(
                    left_table="SAC.CLIENTES",
                    left_column="MUNICIPIO",
                    right_table="SAC.MUNICIPIOS",
                    right_column="MUNICIPIO",
                )
            ],
        )
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"clientes": []})
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings", lambda self: [])

        async def fake_classify(self, question, domains):
            return "clientes"

        async def fake_generate_with_trace(self, question, retrieval):
            sql = (
                "SELECT M.DESCRIPCION, COUNT(C.CLIENTE_ID) "
                "FROM SAC.CLIENTES C JOIN SAC.MUNICIPIOS M ON C.MUNICIPIO = M.MUNICIPIO "
                "GROUP BY M.DESCRIPCION"
            )
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "clientes",
                    "question": "municipio",
                    "expected_tables": ["SAC.CLIENTES", "SAC.MUNICIPIOS"],
                    "expected_columns": ["MUNICIPIOS.DESCRIPCION"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.passed == 1
    finally:
        _cleanup(root)

@pytest.mark.parametrize(
    "source_column,filter_token",
    [
        ("MUNICIPIO", "MUNICIPIO"),
        ("ESTRATO", "ESTRATO"),
        ("ESTADO_FACTURACION", "ESTADO_FACTURACION"),
    ],
)
def test_unapproved_multitabla_usage_is_rejected_for_nonapproved_columns(monkeypatch, source_column, filter_token):
    root = _mk_workspace_tmp()
    try:
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
            lambda self: [DomainCatalog(name="clientes", description="d")],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
            lambda self: [
                TableMetadata(schema="SAC", name="CLIENTES", domain="clientes", columns=[ColumnMetadata(name=source_column, type="NUMBER")]),
                TableMetadata(schema="SAC", name="MULTITABLA", domain="clientes", columns=[ColumnMetadata(name="CODIGO_NUM", type="NUMBER")]),
            ],
        )
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_relationships", lambda self: [])
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"clientes": []})
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings",
            lambda self: [
                {
                    "source_table": "SAC.CLIENTES",
                    "source_column": "ESTADO_CLIENTE",
                    "lookup_table": "SAC.MULTITABLA",
                    "lookup_key": "CODIGO_NUM",
                    "lookup_description": "DESCRIPCION",
                    "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                }
            ],
        )

        async def fake_classify(self, question, domains):
            return "clientes"

        async def fake_generate_with_trace(self, question, retrieval):
            sql = (
                f"SELECT MT.CODIGO_NUM, COUNT(*) FROM SAC.CLIENTES C "
                f"JOIN SAC.MULTITABLA MT ON C.{source_column} = MT.CODIGO_NUM "
                f"WHERE MT.TABLA = '{filter_token}' GROUP BY MT.CODIGO_NUM"
            )
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(root, [{"id": "q1", "domain": "clientes", "question": "x", "approved": True}])
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert "UNAPPROVED_PARAMETRIC_JOIN" in report.failures[0].reason
    finally:
        _cleanup(root)


def test_without_approved_mapping_base_code_column_is_accepted(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)

        async def fake_generate_with_trace(self, question, retrieval):
            sql = "SELECT ID, STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)
        questions_path = _write_questions(
            root,
            [{"id": "q1", "domain": "domain_alpha", "question": "base", "expected_columns": ["STATUS_FLAG"], "approved": True}],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.passed == 1
    finally:
        _cleanup(root)


def test_estado_facturacion_requires_aggregation(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        async def fake_generate_with_trace(self, question, retrieval):
            sql = "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE"
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)
        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "domain_alpha",
                    "question": "Clientes por estado de facturacion",
                    "expected_sql_contains": ["COUNT(", "GROUP BY", "ESTADO_FACTURACION"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.failed == 1
        assert "missing_expected_sql_contains" in report.failures[0].reason
    finally:
        _cleanup(root)


def test_debug_llm_prompt_only_in_development_with_flag(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _mock_catalog(monkeypatch)
        monkeypatch.setattr("app.evaluation.evaluator.settings.app_env", "development")
        monkeypatch.setattr("app.evaluation.evaluator.settings.query_include_llm_prompt_in_debug", True)
        async def fake_classify(self, question, domains):
            return "domain_alpha"
        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)

        async def fake_generate_with_trace(self, question, retrieval):
            return SQLGenerationTrace(
                raw_llm_response="SELECT ID FROM TEST_SCHEMA.TEST_TABLE",
                extracted_sql="SELECT ID FROM TEST_SCHEMA.TEST_TABLE",
                extraction_error=None,
                debug_llm_prompt="prompt with sk-secret",
            )

        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)
        monkeypatch.setattr("app.evaluation.evaluator.settings.openrouter_api_key", "sk-secret")
        questions_path = _write_questions(root, [{"id": "q1", "domain": "domain_alpha", "question": "x", "approved": True}])
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.successful_queries[0].debug_llm_prompt == "prompt with ***"

        monkeypatch.setattr("app.evaluation.evaluator.settings.app_env", "production")
        report2 = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report2.successful_queries[0].debug_llm_prompt is None
    finally:
        _cleanup(root)


@pytest.mark.parametrize("state_value", ["activo", "ACTIVO", "Activo", "aCtIvO"])
def test_sql_contains_semantic_accepts_upper_trim_case_variants(state_value):
    sql = (
        "SELECT M.DESCRIPCION FROM SAC.MUNICIPIOS M "
        f"WHERE UPPER(TRIM(M.DESCRIPCION)) = UPPER(TRIM('{state_value}'))"
    )
    assert _sql_contains_semantic(sql, "M.DESCRIPCION = 'ACTIVO'")


def test_estado_suministro_uses_base_column_and_forbids_multitabla(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_domains",
            lambda self: [DomainCatalog(name="clientes", description="d")],
        )
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_tables",
            lambda self: [
                TableMetadata(
                    schema="SAC",
                    name="CLIENTES",
                    domain="clientes",
                    columns=[
                        ColumnMetadata(name="CLIENTE_ID", type="NUMBER", allowed_for_select=True),
                        ColumnMetadata(name="ESTADO_SUMINISTRO", type="NUMBER", allowed_for_select=True),
                    ],
                )
            ],
        )
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_relationships", lambda self: [])
        monkeypatch.setattr("app.evaluation.evaluator.SemanticCatalogLoader.load_examples", lambda self: {"clientes": []})
        monkeypatch.setattr(
            "app.evaluation.evaluator.SemanticCatalogLoader.load_parametric_mappings",
            lambda self: [
                {
                    "source_table": "SAC.CLIENTES",
                    "source_column": "ESTADO_CLIENTE",
                    "lookup_table": "SAC.MULTITABLA",
                    "lookup_key": "CODIGO_NUM",
                    "lookup_description": "DESCRIPCION",
                    "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                }
            ],
        )

        async def fake_classify(self, question, domains):
            return "clientes"

        async def fake_generate_with_trace(self, question, retrieval):
            sql = (
                "SELECT C.ESTADO_SUMINISTRO, COUNT(C.CLIENTE_ID) "
                "FROM SAC.CLIENTES C "
                "GROUP BY C.ESTADO_SUMINISTRO"
            )
            return SQLGenerationTrace(raw_llm_response=sql, extracted_sql=sql, extraction_error=None)

        monkeypatch.setattr("app.evaluation.evaluator.DomainClassifier.classify", fake_classify)
        monkeypatch.setattr("app.evaluation.evaluator.SQLGenerator.generate_with_trace", fake_generate_with_trace)

        questions_path = _write_questions(
            root,
            [
                {
                    "id": "q1",
                    "domain": "clientes",
                    "question": "Cantidad de Clientes por estado suministro",
                    "expected_columns": ["ESTADO_SUMINISTRO"],
                    "expected_sql_contains": ["COUNT(", "GROUP BY", "ESTADO_SUMINISTRO"],
                    "forbidden_tables": ["SAC.MULTITABLA"],
                    "approved": True,
                }
            ],
        )
        report = TextToSQLEvaluator(questions_path=questions_path).evaluate()
        assert report.passed == 1
    finally:
        _cleanup(root)
