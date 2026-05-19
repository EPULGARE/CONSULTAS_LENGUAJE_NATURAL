import pytest

from app.semantic_catalog.models import ColumnMetadata, RelationshipMetadata, TableMetadata
from app.semantic_catalog.retriever import SemanticRetriever


def test_retrieve_relevant_tables():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            columns=[ColumnMetadata(name="status_flag", type="varchar")],
        ),
        TableMetadata(
            schema="TEST_SCHEMA",
            name="RELATED_TABLE",
            domain="domain_alpha",
            columns=[ColumnMetadata(name="id", type="number")],
        ),
    ]
    rels = [
        RelationshipMetadata(
            left_table="TEST_SCHEMA.TEST_TABLE",
            left_column="id",
            right_table="TEST_SCHEMA.RELATED_TABLE",
            right_column="id",
        )
    ]
    retriever = SemanticRetriever(tables=tables, relationships=rels, examples={"domain_alpha": []})

    result = retriever.retrieve(domain="domain_alpha", question="ver status_flag")
    names = {t.full_name for t in result.tables}
    assert "TEST_SCHEMA.TEST_TABLE" in names


def test_retriever_without_tables_raises():
    retriever = SemanticRetriever(tables=[], relationships=[], examples={})
    with pytest.raises(ValueError, match="No semantic metadata available for query generation."):
        retriever.retrieve(domain="domain_alpha", question="anything")


def test_exclude_table_allowed_for_query_false():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=False,
            columns=[ColumnMetadata(name="status_flag", type="varchar")],
        )
    ]
    retriever = SemanticRetriever(tables=tables, relationships=[], examples={"domain_alpha": []})
    with pytest.raises(ValueError, match="No semantic metadata available for query generation."):
        retriever.retrieve(domain="domain_alpha", question="status")


def test_exclude_sensitive_columns():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            sensitive_columns=["SECRET_COL"],
            columns=[
                ColumnMetadata(name="PUBLIC_COL", type="varchar"),
                ColumnMetadata(name="SECRET_COL", type="varchar", sensitive=True),
            ],
        )
    ]
    retriever = SemanticRetriever(tables=tables, relationships=[], examples={"domain_alpha": []})
    result = retriever.retrieve(domain="domain_alpha", question="public_col")
    assert [c.name for c in result.tables[0].columns] == ["PUBLIC_COL"]
    assert "TEST_SCHEMA.TEST_TABLE.SECRET_COL" in result.disallowed_columns


def test_exclude_column_not_allowed_for_select():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            columns=[
                ColumnMetadata(name="VISIBLE_COL", type="varchar", allowed_for_select=True),
                ColumnMetadata(name="HIDDEN_COL", type="varchar", allowed_for_select=False),
            ],
        )
    ]
    retriever = SemanticRetriever(tables=tables, relationships=[], examples={"domain_alpha": []})
    result = retriever.retrieve(domain="domain_alpha", question="visible_col")
    assert [c.name for c in result.tables[0].columns] == ["VISIBLE_COL"]
    assert "TEST_SCHEMA.TEST_TABLE.HIDDEN_COL" in result.disallowed_columns


def test_retriever_includes_related_table_for_join_hint():
    tables = [
        TableMetadata(
            schema="SAC",
            name="CLIENTES",
            domain="clientes",
            columns=[ColumnMetadata(name="ESTADO_CLIENTE", type="NUMBER")],
        ),
        TableMetadata(
            schema="SAC",
            name="MULTITABLA",
            domain="clientes",
            columns=[
                ColumnMetadata(name="TABLA", type="VARCHAR2"),
                ColumnMetadata(name="CODIGO_NUM", type="NUMBER"),
                ColumnMetadata(name="DESCRIPCION", type="VARCHAR2"),
            ],
        ),
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
    retriever = SemanticRetriever(tables=tables, relationships=rels, examples={"clientes": []})
    result = retriever.retrieve(domain="clientes", question="estado_cliente", max_tables=5)
    names = {t.full_name for t in result.tables}
    assert "SAC.CLIENTES" in names
    assert "SAC.MULTITABLA" in names
    assert any("fixed_filter" in text for text in result.relationships_text)


def test_medidores_estado_uses_static_mapping_and_excludes_multitabla():
    tables = [
        TableMetadata(
            schema="SAC",
            name="MEDIDORES",
            domain="medidores",
            columns=[ColumnMetadata(name="ESTADO", type="VARCHAR2"), ColumnMetadata(name="MEDIDOR_ID", type="NUMBER")],
        ),
        TableMetadata(
            schema="SAC",
            name="MULTITABLA",
            domain="clientes",
            columns=[ColumnMetadata(name="CODIGO_NUM", type="NUMBER")],
        ),
    ]
    rels = [
        RelationshipMetadata(
            left_table="SAC.MEDIDORES",
            left_column="ESTADO",
            right_table="SAC.MULTITABLA",
            right_column="CODIGO_CAR",
        )
    ]
    retriever = SemanticRetriever(
        tables=tables,
        relationships=rels,
        examples={"medidores": []},
        static_value_mappings=[
            {
                "table": "SAC.MEDIDORES",
                "column": "ESTADO",
                "values": {
                    "I": {"label": "Instalado", "synonyms": ["activo"]},
                    "R": {"label": "Retirado", "synonyms": ["inactivo"]},
                },
            }
        ],
    )
    result = retriever.retrieve(domain="medidores", question="Cuantos medidores activos hay", max_tables=5)
    names = {t.full_name for t in result.tables}
    assert "SAC.MEDIDORES" in names
    assert "SAC.MULTITABLA" not in names


def test_retriever_attaches_detected_cardinality_pattern():
    tables = [
        TableMetadata(
            schema="SAC",
            name="MEDIDORES",
            domain="medidores",
            columns=[ColumnMetadata(name="CLIENTE_ID", type="NUMBER"), ColumnMetadata(name="MEDIDOR_ID", type="NUMBER")],
        )
    ]
    retriever = SemanticRetriever(tables=tables, relationships=[], examples={"medidores": []})
    result = retriever.retrieve(
        domain="medidores",
        question="cantidad de usuarios con mas de dos medidores retirados",
    )
    assert result.detected_query_pattern is not None
    assert result.detected_query_pattern.type == "entity_count_with_cardinality_condition"


def test_retriever_keeps_municipios_for_city_name_filters():
    tables = [
        TableMetadata(schema="SAC", name="CLIENTES", domain="clientes", columns=[ColumnMetadata(name="CLIENTE_ID", type="NUMBER")]),
        TableMetadata(schema="SAC", name="MEDIDORES", domain="clientes", columns=[ColumnMetadata(name="CLIENTE_ID", type="NUMBER")]),
        TableMetadata(schema="SAC", name="MUNICIPIOS", domain="clientes", columns=[ColumnMetadata(name="DESCRIPCION", type="VARCHAR2")]),
        TableMetadata(schema="SAC", name="MULTITABLA", domain="clientes", columns=[ColumnMetadata(name="DESCRIPCION", type="VARCHAR2")]),
    ]
    retriever = SemanticRetriever(tables=tables, relationships=[], examples={"clientes": []})
    result = retriever.retrieve(domain="clientes", question="cuantos clientes de calarca tienen un medidor retirado", max_tables=4)
    names = {t.full_name for t in result.tables}
    assert "SAC.MUNICIPIOS" in names


def test_estado_suministro_with_approved_mapping_prefers_multitabla_for_descriptions():
    tables = [
        TableMetadata(schema="SAC", name="CLIENTES", domain="clientes", columns=[ColumnMetadata(name="ESTADO_SUMINISTRO", type="NUMBER")]),
        TableMetadata(schema="SAC", name="MULTITABLA", domain="clientes", columns=[ColumnMetadata(name="DESCRIPCION", type="VARCHAR2")]),
    ]
    retriever = SemanticRetriever(
        tables=tables,
        relationships=[],
        examples={"clientes": []},
        parametric_mappings=[
            {
                "source_table": "SAC.CLIENTES",
                "source_column": "ESTADO_SUMINISTRO",
                "lookup_table": "SAC.MULTITABLA",
                "lookup_key": "CODIGO_NUM",
                "lookup_description": "DESCRIPCION",
                "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_SUMINISTRO'",
            }
        ],
    )
    result = retriever.retrieve(domain="clientes", question="Cuales son las descripciones de los tipos de estado de suministro", max_tables=5)
    names = {t.full_name for t in result.tables}
    assert "SAC.MULTITABLA" in names


def test_estado_suministro_codes_does_not_force_lookup_table():
    tables = [
        TableMetadata(schema="SAC", name="CLIENTES", domain="clientes", columns=[ColumnMetadata(name="ESTADO_SUMINISTRO", type="NUMBER")]),
        TableMetadata(schema="SAC", name="MULTITABLA", domain="clientes", columns=[ColumnMetadata(name="DESCRIPCION", type="VARCHAR2")]),
    ]
    retriever = SemanticRetriever(
        tables=tables,
        relationships=[],
        examples={"clientes": []},
        parametric_mappings=[
            {
                "source_table": "SAC.CLIENTES",
                "source_column": "ESTADO_SUMINISTRO",
                "lookup_table": "SAC.MULTITABLA",
                "lookup_key": "CODIGO_NUM",
                "lookup_description": "DESCRIPCION",
                "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_SUMINISTRO'",
            }
        ],
    )
    result = retriever.retrieve(domain="clientes", question="Cuales son los codigos de estado de suministro", max_tables=5)
    names = {t.full_name for t in result.tables}
    assert "SAC.MULTITABLA" not in names
