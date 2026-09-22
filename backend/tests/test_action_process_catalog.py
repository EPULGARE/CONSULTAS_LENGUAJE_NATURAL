from pathlib import Path

import pytest

from app.context_selector.directory_loader import ContextDirectoryLoader
from app.context_selector.selector import SemanticContextSelector
from app.core.config import settings
from app.llm.classifier import DomainClassifier
from app.llm.prompts import build_sql_user_prompt
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_normalization.normalizer import SemanticNormalizer
from app.sql.dialects import SQLDialect
from app.sql.validator import SQLValidator


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('phrase', [
    'procesos tipo 46', 'proceso tipo 46', 'procesos de tipo 46',
    'tipo de proceso 46', 'tipo de procesos 46',
])
def test_process_type_filter_is_governed_and_wrong_column_is_rejected(monkeypatch, phrase):
    monkeypatch.setattr(settings, 'metadata_path', ROOT / 'metadata')
    question = (
        r'acciones de proceso cerrada por los usuarios EDEQ\AOSPINMA y AOSPINMA '
        'en el año 2026 para los ' + phrase
    )
    resolved = SemanticNormalizer().normalize(question).resolved_numeric_filters
    assert len(resolved) == 1
    assert resolved[0].source_table == 'SAC.PROCESOS'
    assert resolved[0].source_column == 'TIPO'
    assert resolved[0].value == '46'
    assert resolved[0].value_type == 'string'
    validator = SQLValidator(max_rows=500, dialect=SQLDialect.ORACLE)
    kwargs = dict(allowed_tables={'SAC.PROCESOS'}, resolved_numeric_filters=resolved)
    validator.validate("SELECT P.NUMERO_PROCESO FROM SAC.PROCESOS P WHERE P.TIPO = '46'", **kwargs)
    with pytest.raises(ValueError, match='UNRESOLVED_NUMERIC_FILTER'):
        validator.validate("SELECT P.NUMERO_PROCESO FROM SAC.PROCESOS P WHERE P.PROCESO = '46'", **kwargs)


def test_process_code_remains_distinct_from_process_type(monkeypatch):
    monkeypatch.setattr(settings, 'metadata_path', ROOT / 'metadata')
    resolved = SemanticNormalizer().normalize('procesos 4601').resolved_numeric_filters
    assert len(resolved) == 1
    assert resolved[0].source_column == 'PROCESO'
    assert resolved[0].value == '4601'


def test_sql_prompt_includes_approved_action_semantics():
    catalog = SemanticCatalogLoader(ROOT / 'metadata')
    view = next(t for t in catalog.load_tables() if t.full_name == 'SAC.V_AC_PROCESOS')
    prompt = build_sql_user_prompt(
        question='cantidad de acciones cerradas en 2026', tables=[view],
        relationships=[], examples=[], approved_parametric_mappings=[],
        static_value_mappings=catalog.load_static_value_mappings(),
        resolved_lookup_values=[], resolved_numeric_filters=[],
        intent_guardrails=[], auxiliary_semantic_context=[],
    )
    assert 'trabajador que termino la accion' in prompt
    assert 'COUNT(*)' in prompt
    assert 'no usar FECHA_FIN' in prompt
    assert 'F significa accion cerrada' in prompt


def test_user_action_query_accepts_approved_join_and_rejects_wrong_key():
    catalog = SemanticCatalogLoader(ROOT / 'metadata')
    sql = (ROOT / 'docs/examples/acciones_procesos.sql').read_text(encoding='utf-8')
    sql = '\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
    validator = SQLValidator(max_rows=500, dialect=SQLDialect.ORACLE)
    options = dict(
        allowed_tables={t.full_name for t in catalog.load_tables() if t.allowed_for_query},
        approved_relationships=catalog.load_relationships(),
        approved_parametric_mappings=catalog.load_parametric_mappings(),
    )
    result = validator.validate(sql, **options)
    assert 'SAC.V_AC_PROCESOS' in {table.upper() for table in result.used_tables}
    assert 'FETCH FIRST 500 ROWS ONLY' in result.sql
    with pytest.raises(ValueError):
        validator.validate(sql.replace('ac.numero_proceso = pr.numero_proceso',
                                       'ac.numero_proceso = pr.cliente_id'), **options)


@pytest.mark.parametrize('question', [
    'acciones de procesos por trabajador y mes',
    'respuestas de procesos por usuario del sistema',
])
def test_action_questions_retrieve_view_and_parent_locally(monkeypatch, question):
    monkeypatch.setattr(settings, 'metadata_path', ROOT / 'metadata')
    monkeypatch.setattr(settings, 'use_llm_context_selector', False)
    monkeypatch.setattr(settings, 'enable_llm_table_selection_fallback', False)
    catalog = SemanticCatalogLoader(ROOT / 'metadata')
    domain = DomainClassifier.classify_by_vocabulary(question, catalog.load_domains())
    assert domain == 'procesos'
    selector = SemanticContextSelector(ContextDirectoryLoader(ROOT / 'metadata'))
    selected = selector.select(question=question, domain=domain,
                               relationships=catalog.load_relationships(),
                               parametric_mappings=catalog.load_parametric_mappings())
    assert {'SAC.V_AC_PROCESOS', 'SAC.PROCESOS'} <= {item.table for item in selected}
