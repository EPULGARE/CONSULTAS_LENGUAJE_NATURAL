from app.query_patterns.patterns import detect_query_pattern


def test_closed_actions_by_named_workers_is_not_grouping():
    assert detect_query_pattern(
        r"cantidad de acciones de proceso cerrada por los usuarios EDEQ\AOSPINMA y AOSPINMA en el año 2026"
    ) is None


def test_actor_filter_preserves_explicit_month_grouping():
    pattern = detect_query_pattern(
        "cantidad de acciones cerradas por el trabajador AOSPINMA por mes"
    )
    assert pattern is not None
    assert pattern.type == "grouped_aggregation"


def test_actions_grouped_by_worker_still_requires_grouping():
    pattern = detect_query_pattern("cantidad de acciones por usuario del sistema")
    assert pattern is not None
    assert pattern.type == "grouped_aggregation"


def test_detect_cardinality_pattern_more_than_two():
    pattern = detect_query_pattern("cantidad de usuarios de armenia con mas de dos medidores retirados")
    assert pattern is not None
    assert pattern.type == "entity_count_with_cardinality_condition"
    assert pattern.operator == ">"
    assert pattern.threshold == 2
    assert "COUNT(*) AS TOTAL" in pattern.sql_skeleton


def test_detect_ranking_top_n_pattern():
    pattern = detect_query_pattern("top 3 municipios con mas medidores")
    assert pattern is not None
    assert pattern.type == "ranking_top_n"
    assert pattern.top_n == 3
    assert "FETCH FIRST 3 ROWS ONLY" in pattern.sql_skeleton


def test_detect_grouped_aggregation_pattern():
    pattern = detect_query_pattern("cantidad de clientes por municipio")
    assert pattern is not None
    assert pattern.type == "grouped_aggregation"


def test_detect_municipality_filter_pattern():
    pattern = detect_query_pattern("usuarios de armenia")
    assert pattern is not None
    assert pattern.type == "municipality_filter"


def test_detect_parametric_status_filter_pattern():
    pattern = detect_query_pattern("cantidad de clientes activos")
    assert pattern is not None
    assert pattern.type == "parametric_status_filter"


def test_detect_composite_ranking_with_cardinality_pattern():
    pattern = detect_query_pattern("top 10 clientes activos por municipio con mas de dos medidores retirados")
    assert pattern is not None
    assert pattern.type == "ranking_top_n"
    assert pattern.top_n == 10
    assert pattern.operator == ">"
    assert pattern.threshold == 2
    assert "HAVING COUNT(MED.MEDIDOR_ID) > 2" in pattern.sql_skeleton
    assert "FETCH FIRST 10 ROWS ONLY" in pattern.sql_skeleton
