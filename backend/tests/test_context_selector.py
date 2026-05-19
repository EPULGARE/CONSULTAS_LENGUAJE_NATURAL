from pathlib import Path

from app.context_selector.directory_loader import ContextDirectoryLoader
from app.context_selector.selector import SemanticContextSelector
from app.core.config import settings
from app.semantic_catalog.models import ParametricMapping, RelationshipMetadata


def test_directory_loads():
    loader = ContextDirectoryLoader(Path("metadata"))
    entries = loader.load_directory()
    names = {e.table for e in entries}
    assert "SAC.CLIENTES" in names
    assert "SAC.MULTITABLA" in names
    assert "SAC.MUNICIPIOS" in names


def test_select_municipio_tables():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    rels = [
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO")
    ]
    selected = selector.select(
        question="clientes por municipio",
        domain="clientes",
        relationships=rels,
        parametric_mappings=[],
    )
    names = {s.table for s in selected}
    assert "SAC.CLIENTES" in names
    assert "SAC.MUNICIPIOS" in names


def test_estado_uses_multitabla_by_mapping():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    mappings = [
        ParametricMapping(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_key="CODIGO_NUM",
            lookup_description="DESCRIPCION",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    selected = selector.select(
        question="clientes por estado",
        domain="clientes",
        relationships=[],
        parametric_mappings=mappings,
    )
    names = {s.table for s in selected}
    assert "SAC.CLIENTES" in names
    assert "SAC.MULTITABLA" in names


def test_estrato_does_not_require_multitabla_without_mapping():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    selected = selector.select(
        question="clientes por estrato",
        domain="clientes",
        relationships=[],
        parametric_mappings=[],
    )
    names = {s.table for s in selected}
    assert "SAC.CLIENTES" in names


def test_selected_columns_respect_limit(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "max_columns_per_table_in_sql_context", 2)
    selected = selector.select(
        question="clientes",
        domain="clientes",
        relationships=[],
        parametric_mappings=[],
    )
    assert all(len(item.selected_columns) <= 2 for item in selected)


def test_estado_suministro_prioritizes_base_column_without_multitabla_mapping():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    mappings = [
        ParametricMapping(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_key="CODIGO_NUM",
            lookup_description="DESCRIPCION",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    selected = selector.select(
        question="Cantidad de Clientes por estado suministro",
        domain="clientes",
        relationships=[],
        parametric_mappings=mappings,
    )
    by_table = {s.table: s for s in selected}
    assert "SAC.CLIENTES" in by_table
    assert "ESTADO_SUMINISTRO" in by_table["SAC.CLIENTES"].selected_columns


def test_estado_de_su_suministro_still_selects_estado_suministro():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    mappings = [
        ParametricMapping(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_key="CODIGO_NUM",
            lookup_description="DESCRIPCION",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    selected = selector.select(
        question="Cantidad de usuarios agrupados por el estado de su suministro de energia",
        domain="clientes",
        relationships=[],
        parametric_mappings=mappings,
    )
    by_table = {s.table: s for s in selected}
    assert "SAC.CLIENTES" in by_table
    assert "ESTADO_SUMINISTRO" in by_table["SAC.CLIENTES"].selected_columns
    assert "ESTADO_CLIENTE" not in by_table["SAC.CLIENTES"].selected_columns


def test_usuarios_armenia_estado_activo_selects_three_tables():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    mappings = [
        ParametricMapping(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_key="CODIGO_NUM",
            lookup_description="DESCRIPCION",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    rels = [
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="ESTADO_CLIENTE", right_table="SAC.MULTITABLA", right_column="CODIGO_NUM", fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'"),
    ]
    selected = selector.select(
        question="Quiero saber cuantos usuarios hay en armenia con estado Activo",
        domain="clientes",
        relationships=rels,
        parametric_mappings=mappings,
    )
    names = {s.table for s in selected}
    assert {"SAC.CLIENTES", "SAC.MUNICIPIOS", "SAC.MULTITABLA"}.issubset(names)


def test_medidores_por_municipio_selects_bridge_tables():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    rels = [
        RelationshipMetadata(left_table="SAC.MEDIDORES", left_column="CLIENTE_ID", right_table="SAC.CLIENTES", right_column="CLIENTE_ID"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO"),
    ]
    selected = selector.select(
        question="Cuantos medidores hay por municipio",
        domain="medidores",
        relationships=rels,
        parametric_mappings=[],
    )
    names = {s.table for s in selected}
    assert {"SAC.MEDIDORES", "SAC.CLIENTES", "SAC.MUNICIPIOS"}.issubset(names)
    assert selector.last_selection_debug["strategy"] == "LOCAL_ONLY"
    assert selector.last_selection_debug["used_llm_table_selection"] is False


def test_grouped_dimension_includes_display_column_for_municipios():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    rels = [
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO")
    ]
    selected = selector.select(
        question="cuantos clientes hay por municipio",
        domain="clientes",
        relationships=rels,
        parametric_mappings=[],
    )
    by_table = {s.table: s for s in selected}
    assert "SAC.MUNICIPIOS" in by_table
    assert "DESCRIPCION" in by_table["SAC.MUNICIPIOS"].selected_columns


def test_parametric_dimension_includes_display_column_for_multitabla():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    mappings = [
        ParametricMapping(
            source_table="SAC.CLIENTES",
            source_column="ESTADO_CLIENTE",
            lookup_table="SAC.MULTITABLA",
            lookup_key="CODIGO_NUM",
            lookup_description="DESCRIPCION",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    rels = [
        RelationshipMetadata(
            left_table="SAC.CLIENTES",
            left_column="ESTADO_CLIENTE",
            right_table="SAC.MULTITABLA",
            right_column="CODIGO_NUM",
            fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    selected = selector.select(
        question="cantidad de clientes por estado cliente",
        domain="clientes",
        relationships=rels,
        parametric_mappings=mappings,
    )
    by_table = {s.table: s for s in selected}
    assert "SAC.MULTITABLA" in by_table
    assert "DESCRIPCION" in by_table["SAC.MULTITABLA"].selected_columns


def test_medidores_activos_includes_estado_column():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    selected = selector.select(
        question="Cuantos medidores activos hay",
        domain="medidores",
        relationships=[],
        parametric_mappings=[],
    )
    by_table = {s.table: s for s in selected}
    assert "SAC.MEDIDORES" in by_table
    assert "ESTADO" in by_table["SAC.MEDIDORES"].selected_columns


def test_complex_query_users_city_medidores_selects_required_tables():
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    rels = [
        RelationshipMetadata(left_table="SAC.MEDIDORES", left_column="CLIENTE_ID", right_table="SAC.CLIENTES", right_column="CLIENTE_ID"),
        RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO"),
    ]
    selected = selector.select(
        question="cantidad de usuarios de armenia conectados con mas de dos medidores retirados",
        domain="medidores",
        relationships=rels,
        parametric_mappings=[],
    )
    names = {s.table for s in selected}
    assert {"SAC.MEDIDORES", "SAC.CLIENTES", "SAC.MUNICIPIOS"}.issubset(names)


def test_unknown_pattern_can_fallback_to_llm(monkeypatch):
    loader = ContextDirectoryLoader(Path("metadata"))
    selector = SemanticContextSelector(loader)
    monkeypatch.setattr(settings, "use_llm_context_selector", True)
    monkeypatch.setattr(settings, "enable_llm_table_selection_fallback", True)

    class _LLMResult:
        selected_tables = ["SAC.CLIENTES", "SAC.MULTITABLA"]
        reason = "fallback llm"
        confidence = 0.72

    monkeypatch.setattr("app.context_selector.selector.select_tables_with_llm", lambda *args, **kwargs: _LLMResult())
    selected = selector.select(
        question="dame algo raro de clientes",
        domain="clientes",
        relationships=[],
        parametric_mappings=[],
    )
    names = {s.table for s in selected}
    assert "SAC.CLIENTES" in names
    assert selector.last_selection_debug["strategy"] == "LOCAL_PLUS_LLM"
    assert selector.last_selection_debug["used_llm_table_selection"] is True
