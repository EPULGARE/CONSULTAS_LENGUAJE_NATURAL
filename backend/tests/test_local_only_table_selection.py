from pathlib import Path

from app.context_selector.directory_loader import ContextDirectoryLoader
from app.context_selector.selector import SemanticContextSelector
from app.core.config import settings
from app.semantic_catalog.models import ParametricMapping, RelationshipMetadata, ResolvedLookupValue


def _clientes_estado_mapping() -> list[ParametricMapping]:
    return [
        ParametricMapping(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_key="CODIGO_NUM",
            lookup_description="DESCRIPCION",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]


def test_medidores_por_municipio_uses_local_only(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "use_llm_context_selector", True)
    monkeypatch.setattr(settings, "enable_llm_table_selection_fallback", True)
    monkeypatch.setattr(
        "app.context_selector.selector.select_tables_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM selector should be skipped")),
    )
    rels = [
        RelationshipMetadata(left_table="SAC.MEDIDORES", left_column="CLIENTE_ID", right_table="SAC.CLIENTES", right_column="CLIENTE_ID"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO"),
    ]

    selected = selector.select(
        question="cantidad de medidores por municipio",
        domain="medidores",
        relationships=rels,
        parametric_mappings=[],
        unresolved_ambiguities=[],
    )

    names = {item.table for item in selected}
    assert {"SAC.MEDIDORES", "SAC.CLIENTES", "SAC.MUNICIPIOS"}.issubset(names)
    assert selector.last_selection_debug["strategy"] == "LOCAL_ONLY"
    assert selector.last_selection_debug["used_llm_table_selection"] is False


def test_usuarios_conectados_del_quindio_uses_local_only_after_governed_resolution(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "use_llm_context_selector", True)
    monkeypatch.setattr(settings, "enable_llm_table_selection_fallback", True)
    monkeypatch.setattr(
        "app.context_selector.selector.select_tables_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM selector should be skipped")),
    )
    rels = [
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="DEPTO", right_table="SAC.MULTITABLA", right_column="CODIGO_NUM"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="ESTADO_CLIENTE", right_table="SAC.MULTITABLA", right_column="CODIGO_NUM", fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'"),
    ]
    resolved_lookup = [
        ResolvedLookupValue(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_description="DESCRIPCION",
            fixed_filter_value="CLI_ESTADO",
            canonical_value="Activo",
            matched_synonym="clientes",
        )
    ]

    selected = selector.select(
        question="usuarios conectados del quindio. interpretar conectados como clientes activos",
        domain="clientes",
        relationships=rels,
        parametric_mappings=_clientes_estado_mapping(),
        unresolved_ambiguities=[],
        resolved_lookup_values=resolved_lookup,
    )

    names = {item.table for item in selected}
    assert {"SAC.CLIENTES", "SAC.MULTITABLA"}.issubset(names)
    assert selector.last_selection_debug["strategy"] == "LOCAL_ONLY"
    assert selector.last_selection_debug["used_llm_table_selection"] is False


def test_top_clientes_activos_por_municipio_con_medidores_retirados_uses_local_only(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "use_llm_context_selector", True)
    monkeypatch.setattr(settings, "enable_llm_table_selection_fallback", True)
    monkeypatch.setattr(
        "app.context_selector.selector.select_tables_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM selector should be skipped")),
    )
    rels = [
        RelationshipMetadata(left_table="SAC.MEDIDORES", left_column="CLIENTE_ID", right_table="SAC.CLIENTES", right_column="CLIENTE_ID"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="ESTADO_CLIENTE", right_table="SAC.MULTITABLA", right_column="CODIGO_NUM", fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'"),
    ]
    resolved_lookup = [
        ResolvedLookupValue(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_description="DESCRIPCION",
            fixed_filter_value="CLI_ESTADO",
            canonical_value="Activo",
            matched_synonym="activos",
        )
    ]

    selected = selector.select(
        question="top 10 clientes activos por municipio con mas de dos medidores retirados",
        domain="clientes",
        relationships=rels,
        parametric_mappings=_clientes_estado_mapping(),
        unresolved_ambiguities=[],
        resolved_lookup_values=resolved_lookup,
        static_mapping_columns=["SAC.MEDIDORES.ESTADO"],
    )

    names = {item.table for item in selected}
    assert {"SAC.CLIENTES", "SAC.MEDIDORES", "SAC.MUNICIPIOS", "SAC.MULTITABLA"}.issubset(names)
    assert selector.last_selection_debug["strategy"] == "LOCAL_ONLY"
    assert selector.last_selection_debug["used_llm_table_selection"] is False


def test_ambiguous_question_allows_llm_fallback(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "use_llm_context_selector", True)
    monkeypatch.setattr(settings, "enable_llm_table_selection_fallback", True)

    class _LLMResult:
        selected_tables = ["SAC.CLIENTES", "SAC.MEDIDORES"]
        reason = "ambiguity fallback"
        confidence = 0.7

    monkeypatch.setattr("app.context_selector.selector.select_tables_with_llm", lambda *args, **kwargs: _LLMResult())
    selector.select(
        question="usuarios conectados",
        domain="clientes",
        relationships=[],
        parametric_mappings=_clientes_estado_mapping(),
        unresolved_ambiguities=["conectados => cliente o medidor"],
    )

    assert selector.last_selection_debug["strategy"] == "LOCAL_PLUS_LLM"
    assert selector.last_selection_debug["used_llm_table_selection"] is True


def test_no_join_path_allows_llm_fallback(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "use_llm_context_selector", True)
    monkeypatch.setattr(settings, "enable_llm_table_selection_fallback", True)
    monkeypatch.setattr(
        selector.relationship_graph,
        "expand_tables_with_join_path",
        lambda selected, question, max_hops=3: (list(selected), [], []),
    )

    class _LLMResult:
        selected_tables = ["SAC.MEDIDORES", "SAC.MUNICIPIOS"]
        reason = "join fallback"
        confidence = 0.68

    monkeypatch.setattr("app.context_selector.selector.select_tables_with_llm", lambda *args, **kwargs: _LLMResult())
    selector.select(
        question="medidores de armenia",
        domain="medidores",
        relationships=[],
        parametric_mappings=[],
        unresolved_ambiguities=[],
    )

    assert selector.last_selection_debug["strategy"] == "LOCAL_PLUS_LLM"
    assert selector.last_selection_debug["used_llm_table_selection"] is True
