from __future__ import annotations

from app.query_patterns.models import DetectedQueryPattern


def build_skeleton(pattern_type: str, *, operator: str = "", threshold: int | None = None, top_n: int | None = None) -> str:
    if pattern_type == "entity_count_with_cardinality_condition":
        op = operator or ">"
        th = threshold if threshold is not None else 1
        return (
            "SELECT COUNT(*) AS TOTAL\n"
            "FROM (\n"
            "  SELECT C.CLIENTE_ID\n"
            "  FROM ...\n"
            "  WHERE ...\n"
            "  GROUP BY C.CLIENTE_ID\n"
            f"  HAVING COUNT(MED.MEDIDOR_ID) {op} {th}\n"
            ") Q"
        )
    if pattern_type == "ranking_top_n":
        n = top_n if top_n is not None else 1
        having_clause = ""
        if operator and threshold is not None:
            having_clause = f"\nHAVING COUNT(MED.MEDIDOR_ID) {operator} {threshold}"
        return (
            "SELECT <DIMENSION>, COUNT(*) AS TOTAL\n"
            "FROM ...\n"
            "WHERE ...\n"
            "GROUP BY <DIMENSION>\n"
            f"{having_clause}\n"
            "ORDER BY TOTAL DESC\n"
            f"FETCH FIRST {n} ROWS ONLY"
        )
    if pattern_type == "grouped_aggregation":
        return (
            "SELECT <DIMENSION>, COUNT(*) AS TOTAL\n"
            "FROM ...\n"
            "WHERE ...\n"
            "GROUP BY <DIMENSION>"
        )
    if pattern_type == "descriptive_lookup":
        return (
            "SELECT <DESCRIPTION_COLUMN>\n"
            "FROM ...\n"
            "WHERE <CODE_COLUMN> = <VALUE>"
        )
    if pattern_type == "municipality_filter":
        return (
            "SELECT ...\n"
            "FROM ...\n"
            "JOIN SAC.MUNICIPIOS M ON C.MUNICIPIO = M.MUNICIPIO\n"
            "WHERE UPPER(TRIM(M.DESCRIPCION)) = UPPER(TRIM('<municipio>'))"
        )
    if pattern_type == "parametric_status_filter":
        return (
            "SELECT ...\n"
            "FROM ...\n"
            "JOIN SAC.MULTITABLA MT ON <SOURCE_STATUS_COLUMN> = MT.CODIGO_NUM\n"
            "WHERE MT.TABLA = '<APPROVED_TABLE>'\n"
            "AND UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('<estado>'))"
        )
    return ""


def attach_skeleton(pattern: DetectedQueryPattern) -> DetectedQueryPattern:
    pattern.sql_skeleton = build_skeleton(
        pattern.type,
        operator=pattern.operator,
        threshold=pattern.threshold,
        top_n=pattern.top_n,
    )
    return pattern
