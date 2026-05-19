import pytest

from app.semantic_catalog.models import DetectedQueryPattern, ParametricMapping, RelationshipMetadata, ResolvedLookupValue
from app.semantic_normalization.models import ResolvedNumericFilter
from app.sql.dialects import SQLDialect
from app.sql.validator import SQLValidator


ALLOWED = {
    "TEST_SCHEMA.TEST_TABLE",
    "TEST_SCHEMA.RELATED_TABLE",
}


def _validator() -> SQLValidator:
    return SQLValidator(max_rows=500, dialect=SQLDialect.ORACLE, allow_union=False, allow_select_without_from=False)


def test_accepts_valid_oracle_select():
    result = _validator().validate(
        "SELECT STATUS_FLAG FROM TEST_SCHEMA.TEST_TABLE",
        allowed_tables=ALLOWED,
    )
    assert result.sql.endswith("FETCH FIRST 500 ROWS ONLY")


def test_detects_schema_table():
    result = _validator().validate(
        "SELECT * FROM TEST_SCHEMA.TEST_TABLE",
        allowed_tables=ALLOWED,
    )
    assert "TEST_SCHEMA.TEST_TABLE" in result.used_tables


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM TEST_SCHEMA.TEST_TABLE",
        "UPDATE TEST_SCHEMA.TEST_TABLE SET VALUE_COL = 1",
        "DROP TABLE TEST_SCHEMA.TEST_TABLE",
        "MERGE INTO TEST_SCHEMA.TEST_TABLE t USING TEST_SCHEMA.RELATED_TABLE s ON (t.ID=s.ID) WHEN MATCHED THEN UPDATE SET t.VALUE_COL=1",
        "EXEC SOME_PROC",
    ],
)
def test_blocks_forbidden_keywords(sql: str):
    with pytest.raises(ValueError):
        _validator().validate(sql, allowed_tables=ALLOWED)


def test_blocks_multiple_statements():
    with pytest.raises(ValueError):
        _validator().validate(
            "SELECT * FROM TEST_SCHEMA.TEST_TABLE; SELECT * FROM TEST_SCHEMA.RELATED_TABLE",
            allowed_tables=ALLOWED,
        )


def test_blocks_table_outside_catalog():
    with pytest.raises(ValueError):
        _validator().validate("SELECT * FROM TEST_SCHEMA.UNKNOWN_TABLE", allowed_tables=ALLOWED)


def test_adds_fetch_first_when_missing():
    result = _validator().validate("SELECT * FROM TEST_SCHEMA.TEST_TABLE", allowed_tables=ALLOWED)
    assert result.sql.endswith("FETCH FIRST 500 ROWS ONLY")


def test_does_not_duplicate_fetch_first():
    sql = "SELECT * FROM TEST_SCHEMA.TEST_TABLE FETCH FIRST 500 ROWS ONLY"
    result = _validator().validate(sql, allowed_tables=ALLOWED)
    assert result.sql.upper().count("FETCH FIRST") == 1


def test_normalizes_fetch_next_without_duplicate_limit():
    sql = "SELECT * FROM TEST_SCHEMA.TEST_TABLE FETCH NEXT 1 ROW ONLY"
    result = _validator().validate(sql, allowed_tables=ALLOWED)
    assert "FETCH NEXT" not in result.sql.upper()
    assert result.sql.upper().count("FETCH FIRST") == 1
    assert "FETCH FIRST 1 ROW ONLY" in result.sql.upper()


def test_blocks_union_by_default():
    sql = "SELECT * FROM TEST_SCHEMA.TEST_TABLE UNION SELECT * FROM TEST_SCHEMA.RELATED_TABLE"
    with pytest.raises(ValueError):
        _validator().validate(sql, allowed_tables=ALLOWED)


def test_blocks_sensitive_column_selection():
    with pytest.raises(ValueError):
        _validator().validate(
            "SELECT SECRET_COL FROM TEST_SCHEMA.TEST_TABLE",
            allowed_tables=ALLOWED,
            disallowed_columns={"TEST_SCHEMA.TEST_TABLE.SECRET_COL"},
        )


def test_blocks_sensitive_column_with_alias():
    with pytest.raises(ValueError):
        _validator().validate(
            "SELECT t.SECRET_COL FROM TEST_SCHEMA.TEST_TABLE t",
            allowed_tables=ALLOWED,
            disallowed_columns={"TEST_SCHEMA.TEST_TABLE.SECRET_COL"},
        )


def test_does_not_block_qualified_non_sensitive_homonym():
    result = _validator().validate(
        "SELECT r.SECRET_COL FROM TEST_SCHEMA.TEST_TABLE t JOIN TEST_SCHEMA.RELATED_TABLE r ON t.ID = r.ID",
        allowed_tables=ALLOWED,
        disallowed_columns={"TEST_SCHEMA.TEST_TABLE.SECRET_COL"},
    )
    assert result.sql.endswith("FETCH FIRST 500 ROWS ONLY")


def test_blocks_parametric_magic_filter_without_lookup():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="STATUS_FLAG",
        lookup_table="TEST_SCHEMA.RELATED_TABLE",
        lookup_key="STATUS_CODE",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.RELATED_TABLE.TABLA = 'CLI_ESTADO'",
    )
    with pytest.raises(ValueError, match="PARAMETRIC_FILTER_WITHOUT_LOOKUP"):
        _validator().validate(
            "SELECT * FROM TEST_SCHEMA.TEST_TABLE T WHERE T.STATUS_FLAG = 1",
            allowed_tables=ALLOWED,
            approved_parametric_mappings=[mapping],
        )


def test_blocks_parametric_description_filter_missing_fixed_filter():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="STATUS_FLAG",
        lookup_table="TEST_SCHEMA.RELATED_TABLE",
        lookup_key="STATUS_CODE",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.RELATED_TABLE.TABLA = 'CLI_ESTADO'",
    )
    with pytest.raises(ValueError, match="PARAMETRIC_FILTER_WITHOUT_LOOKUP"):
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T "
            "JOIN TEST_SCHEMA.RELATED_TABLE MT ON T.STATUS_FLAG = MT.STATUS_CODE "
            "WHERE UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('Activo'))",
            allowed_tables=ALLOWED,
            approved_parametric_mappings=[mapping],
        )


def test_blocks_unapproved_multitabla_join():
    approved = [
        ParametricMapping(
            source_table="TEST_SCHEMA.TEST_TABLE",
            source_column="STATUS_FLAG",
            lookup_table="TEST_SCHEMA.MULTITABLA",
            lookup_key="STATUS_CODE",
            lookup_description="DESCRIPCION",
            fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'CLI_ESTADO'",
        )
    ]
    with pytest.raises(ValueError, match="UNAPPROVED_PARAMETRIC_JOIN"):
        _validator().validate(
            "SELECT MT.DESCRIPCION FROM TEST_SCHEMA.TEST_TABLE T "
            "JOIN TEST_SCHEMA.MULTITABLA MT ON T.OTHER_STATUS = MT.STATUS_CODE",
            allowed_tables=ALLOWED | {"TEST_SCHEMA.MULTITABLA"},
            approved_parametric_mappings=approved,
        )


def test_blocks_non_canonical_resolved_lookup_value():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="STATUS_FLAG",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_key="STATUS_CODE",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'PRO_ESTADO'",
    )
    resolved = ResolvedLookupValue(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="STATUS_FLAG",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_description="DESCRIPCION",
        fixed_filter_value="PRO_ESTADO",
        canonical_value="Tramite",
        matched_synonym="en tramite",
        valid_values=["Tramite", "Finalizado"],
    )
    with pytest.raises(ValueError, match="UNRESOLVED_LOOKUP_VALUE"):
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T "
            "JOIN TEST_SCHEMA.MULTITABLA MT ON T.STATUS_FLAG = MT.STATUS_CODE "
            "WHERE MT.TABLA = 'PRO_ESTADO' "
            "AND UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('tramite'))",
            allowed_tables=ALLOWED | {"TEST_SCHEMA.MULTITABLA"},
            approved_parametric_mappings=[mapping],
            resolved_lookup_values=[resolved],
        )


def test_accepts_canonical_resolved_lookup_value():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="STATUS_FLAG",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_key="STATUS_CODE",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'PRO_ESTADO'",
    )
    resolved = ResolvedLookupValue(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="STATUS_FLAG",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_description="DESCRIPCION",
        fixed_filter_value="PRO_ESTADO",
        canonical_value="Tramite",
        matched_synonym="tramite",
        valid_values=["Tramite", "Finalizado"],
    )
    result = _validator().validate(
        "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T "
        "JOIN TEST_SCHEMA.MULTITABLA MT ON T.STATUS_FLAG = MT.STATUS_CODE "
        "WHERE MT.TABLA = 'PRO_ESTADO' "
        "AND UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('Tramite'))",
        allowed_tables=ALLOWED | {"TEST_SCHEMA.MULTITABLA"},
        approved_parametric_mappings=[mapping],
        resolved_lookup_values=[resolved],
    )
    assert result.sql


def test_blocks_lookup_value_on_non_approved_column():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_key="CODIGO_CAR",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
    )
    resolved = ResolvedLookupValue(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_description="DESCRIPCION",
        fixed_filter_value="PED_SOLSRV_PRO",
        canonical_value="Conexion del Servicio",
        matched_synonym="conexion del servicio",
        code="4106",
        resolution_source="approved_lookup_values",
    )
    with pytest.raises(ValueError, match="INVALID_LOOKUP_VALUE_COLUMN"):
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T "
            "WHERE UPPER(TRIM(T.TIPO)) = UPPER(TRIM('Conexion del Servicio'))",
            allowed_tables=ALLOWED,
            approved_parametric_mappings=[mapping],
            resolved_lookup_values=[resolved],
        )


def test_blocks_lookup_value_text_compared_against_base_code_column():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_key="CODIGO_CAR",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
    )
    resolved = ResolvedLookupValue(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_description="DESCRIPCION",
        fixed_filter_value="PED_SOLSRV_PRO",
        canonical_value="Conexión del Servicio",
        matched_synonym="conexion del servicio",
        code="4106",
        resolution_source="approved_lookup_values",
    )
    with pytest.raises(ValueError, match="INVALID_LOOKUP_VALUE_COLUMN"):
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T "
            "WHERE UPPER(TRIM(T.PROCESO)) = UPPER(TRIM('Conexion del Servicio'))",
            allowed_tables=ALLOWED,
            approved_parametric_mappings=[mapping],
            resolved_lookup_values=[resolved],
        )


def test_accepts_generated_lookup_value_with_nlssort_accent_insensitive_filter():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_key="CODIGO_CAR",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
    )
    resolved = ResolvedLookupValue(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_description="DESCRIPCION",
        fixed_filter_value="PED_SOLSRV_PRO",
        canonical_value="Conexión del Servicio",
        matched_synonym="conexion del servicio",
        code="4106",
        resolution_source="approved_lookup_values",
    )
    result = _validator().validate(
        "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T "
        "JOIN TEST_SCHEMA.MULTITABLA MT ON T.PROCESO = MT.CODIGO_CAR "
        "WHERE MT.TABLA = 'PED_SOLSRV_PRO' "
        "AND NLSSORT(TRIM(MT.DESCRIPCION), 'NLS_SORT=BINARY_AI') = NLSSORT(TRIM('Conexion del Servicio'), 'NLS_SORT=BINARY_AI')",
        allowed_tables=ALLOWED | {"TEST_SCHEMA.MULTITABLA"},
        approved_parametric_mappings=[mapping],
        resolved_lookup_values=[resolved],
    )
    assert result.sql


def test_accepts_cardinality_pattern_structure_with_subquery():
    pattern = DetectedQueryPattern(
        type="entity_count_with_cardinality_condition",
        entity="clientes",
        related_entity="medidores",
        operator=">",
        threshold=2,
        sql_skeleton="",
    )
    sql = (
        "SELECT COUNT(*) AS TOTAL FROM ("
        " SELECT T.CLIENT_ID FROM TEST_SCHEMA.TEST_TABLE T "
        " GROUP BY T.CLIENT_ID HAVING COUNT(T.ID) > 2"
        ") Q"
    )
    result = _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)
    assert "FETCH FIRST 500 ROWS ONLY" in result.sql


def test_blocks_cardinality_pattern_without_subquery_structure():
    pattern = DetectedQueryPattern(
        type="entity_count_with_cardinality_condition",
        entity="clientes",
        related_entity="medidores",
        operator=">",
        threshold=2,
        sql_skeleton="",
    )
    sql = (
        "SELECT COUNT(DISTINCT T.CLIENT_ID) FROM TEST_SCHEMA.TEST_TABLE T "
        "GROUP BY T.CLIENT_ID HAVING COUNT(T.ID) > 2"
    )
    with pytest.raises(ValueError, match="INVALID_PATTERN_STRUCTURE"):
        _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)


def test_accepts_ranking_top_n_structure():
    pattern = DetectedQueryPattern(type="ranking_top_n", top_n=3, sql_skeleton="")
    sql = (
        "SELECT T.STATUS_FLAG, COUNT(*) AS TOTAL FROM TEST_SCHEMA.TEST_TABLE T "
        "GROUP BY T.STATUS_FLAG ORDER BY TOTAL DESC FETCH FIRST 3 ROWS ONLY"
    )
    result = _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)
    assert "FETCH FIRST 3 ROWS ONLY" in result.sql.upper()


def test_blocks_ranking_without_order_or_limit():
    pattern = DetectedQueryPattern(type="ranking_top_n", top_n=3, sql_skeleton="")
    sql = "SELECT T.STATUS_FLAG, COUNT(*) AS TOTAL FROM TEST_SCHEMA.TEST_TABLE T GROUP BY T.STATUS_FLAG"
    with pytest.raises(ValueError, match="INVALID_PATTERN_STRUCTURE"):
        _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)


def test_accepts_ranking_top_n_with_cardinality_having():
    pattern = DetectedQueryPattern(type="ranking_top_n", top_n=10, operator=">", threshold=2, sql_skeleton="")
    sql = (
        "SELECT T.STATUS_FLAG, COUNT(*) AS TOTAL FROM TEST_SCHEMA.TEST_TABLE T "
        "GROUP BY T.STATUS_FLAG HAVING COUNT(T.ID) > 2 "
        "ORDER BY TOTAL DESC FETCH FIRST 10 ROWS ONLY"
    )
    result = _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)
    assert "FETCH FIRST 10 ROWS ONLY" in result.sql.upper()


def test_blocks_ranking_top_n_with_cardinality_missing_having():
    pattern = DetectedQueryPattern(type="ranking_top_n", top_n=10, operator=">", threshold=2, sql_skeleton="")
    sql = (
        "SELECT T.STATUS_FLAG, COUNT(*) AS TOTAL FROM TEST_SCHEMA.TEST_TABLE T "
        "GROUP BY T.STATUS_FLAG ORDER BY TOTAL DESC FETCH FIRST 10 ROWS ONLY"
    )
    with pytest.raises(ValueError, match="INVALID_PATTERN_STRUCTURE"):
        _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)


def test_accepts_ranking_top_n_with_equivalent_in_subquery_cardinality():
    pattern = DetectedQueryPattern(type="ranking_top_n", top_n=10, operator=">", threshold=2, sql_skeleton="")
    sql = (
        "SELECT T.STATUS_FLAG, COUNT(DISTINCT T.CLIENT_ID) AS TOTAL "
        "FROM TEST_SCHEMA.TEST_TABLE T "
        "WHERE T.CLIENT_ID IN ("
        " SELECT R.CLIENT_ID FROM TEST_SCHEMA.RELATED_TABLE R "
        " GROUP BY R.CLIENT_ID HAVING COUNT(R.ID) > 2"
        ") "
        "GROUP BY T.STATUS_FLAG ORDER BY TOTAL DESC FETCH FIRST 10 ROWS ONLY"
    )
    result = _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)
    assert "FETCH FIRST 10 ROWS ONLY" in result.sql.upper()


def test_accepts_grouped_aggregation_pattern():
    pattern = DetectedQueryPattern(type="grouped_aggregation", sql_skeleton="")
    sql = "SELECT T.STATUS_FLAG, COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T GROUP BY T.STATUS_FLAG"
    result = _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)
    assert result.sql


def test_blocks_grouped_aggregation_without_group_by():
    pattern = DetectedQueryPattern(type="grouped_aggregation", sql_skeleton="")
    sql = "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE"
    with pytest.raises(ValueError, match="INVALID_PATTERN_STRUCTURE"):
        _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)


def test_accepts_municipality_filter_pattern():
    pattern = DetectedQueryPattern(type="municipality_filter", sql_skeleton="")
    sql = (
        "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE C "
        "JOIN TEST_SCHEMA.RELATED_TABLE MUNICIPIOS ON C.ID = MUNICIPIOS.ID "
        "WHERE UPPER(TRIM(MUNICIPIOS.DESCRIPCION)) = UPPER(TRIM('ARMENIA'))"
    )
    result = _validator().validate(sql, allowed_tables=ALLOWED, detected_query_pattern=pattern)
    assert result.sql


def test_accepts_resolved_numeric_filter_on_governed_column():
    resolved = ResolvedNumericFilter(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        operator="=",
        value="4106",
        value_type="string",
        entity="procesos",
        matched_text="procesos 4106",
        forbidden_columns=["CODIGO_CUENTA", "NUMERO_PROCESO", "TIPO_TRAMITE"],
    )
    result = _validator().validate(
        "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T WHERE T.PROCESO = '4106'",
        allowed_tables=ALLOWED,
        resolved_numeric_filters=[resolved],
    )
    assert result.sql


def test_blocks_forbidden_numeric_entity_column():
    resolved = ResolvedNumericFilter(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        operator="=",
        value="4106",
        value_type="string",
        entity="procesos",
        matched_text="procesos 4106",
        forbidden_columns=["CODIGO_CUENTA", "NUMERO_PROCESO", "TIPO_TRAMITE"],
    )
    with pytest.raises(ValueError, match="INVALID_NUMERIC_ENTITY_COLUMN"):
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T WHERE T.CODIGO_CUENTA = '4106'",
            allowed_tables=ALLOWED,
            resolved_numeric_filters=[resolved],
        )


def test_blocks_missing_or_wrongly_typed_resolved_numeric_filter():
    resolved = ResolvedNumericFilter(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        operator="=",
        value="4106",
        value_type="string",
        entity="procesos",
        matched_text="procesos 4106",
        forbidden_columns=["CODIGO_CUENTA", "NUMERO_PROCESO", "TIPO_TRAMITE"],
    )
    with pytest.raises(ValueError, match="UNRESOLVED_NUMERIC_FILTER"):
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.TEST_TABLE T WHERE T.PROCESO = 4106",
            allowed_tables=ALLOWED,
            resolved_numeric_filters=[resolved],
        )


def test_accepts_parametric_description_lookup_with_governed_base_code_filter():
    mapping = ParametricMapping(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        lookup_table="TEST_SCHEMA.MULTITABLA",
        lookup_key="CODIGO_CAR",
        lookup_description="DESCRIPCION",
        fixed_filter="TEST_SCHEMA.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
    )
    resolved = ResolvedNumericFilter(
        source_table="TEST_SCHEMA.TEST_TABLE",
        source_column="PROCESO",
        operator="=",
        value="4106",
        value_type="string",
        entity="procesos",
        matched_text="proceso 4106",
        forbidden_columns=["CODIGO_CUENTA", "NUMERO_PROCESO", "TIPO_TRAMITE"],
    )
    result = _validator().validate(
        "SELECT MT.DESCRIPCION FROM TEST_SCHEMA.TEST_TABLE T "
        "JOIN TEST_SCHEMA.MULTITABLA MT ON T.PROCESO = MT.CODIGO_CAR "
        "WHERE MT.TABLA = 'PED_SOLSRV_PRO' AND T.PROCESO = '4106'",
        allowed_tables=ALLOWED | {"TEST_SCHEMA.MULTITABLA"},
        approved_parametric_mappings=[mapping],
        resolved_numeric_filters=[resolved],
    )
    assert result.sql


def test_blocks_unapproved_join_path_and_exposes_candidate():
    approved_relationships = [
        RelationshipMetadata(
            left_table="TEST_SCHEMA.MEDIDORES",
            left_column="CLIENTE_ID",
            right_table="TEST_SCHEMA.CLIENTES",
            right_column="CLIENTE_ID",
        )
    ]
    with pytest.raises(ValueError, match="UNAPPROVED_JOIN_PATH") as exc_info:
        _validator().validate(
            "SELECT COUNT(*) FROM TEST_SCHEMA.CLIENTES C "
            "JOIN TEST_SCHEMA.TEST_TABLE P ON C.CLIENTE_ID = P.CODIGO_CUENTA",
            allowed_tables=ALLOWED | {"TEST_SCHEMA.CLIENTES"},
            approved_relationships=approved_relationships,
        )
    assert getattr(exc_info.value, "candidates")[0].from_table == "TEST_SCHEMA.CLIENTES"
