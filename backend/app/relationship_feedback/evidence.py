from __future__ import annotations

import re
from typing import Any

from app.relationship_feedback.models import RelationshipCandidate, RelationshipEvidence

_SAFE_NAME = re.compile(r"^[A-Z0-9_$.]+$")


def build_distinct_count_query(table_name: str, column_name: str) -> str:
    safe_table = _safe_identifier(table_name)
    safe_column = _safe_identifier(column_name)
    return f"SELECT COUNT(DISTINCT {safe_column}) AS DISTINCT_COUNT FROM {safe_table} WHERE {safe_column} IS NOT NULL"


def build_null_rate_query(table_name: str, column_name: str) -> str:
    safe_table = _safe_identifier(table_name)
    safe_column = _safe_identifier(column_name)
    return f"SELECT COUNT(*) AS TOTAL_COUNT, COUNT({safe_column}) AS NON_NULL_COUNT FROM {safe_table}"


def build_match_distinct_query(
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    *,
    distinct_side: str,
) -> str:
    safe_from_table = _safe_identifier(from_table)
    safe_from_column = _safe_identifier(from_column)
    safe_to_table = _safe_identifier(to_table)
    safe_to_column = _safe_identifier(to_column)
    if distinct_side == "to":
        distinct_expr = f"t.{safe_to_column}"
    else:
        distinct_expr = f"f.{safe_from_column}"
    return (
        f"SELECT COUNT(DISTINCT {distinct_expr}) AS MATCHED_DISTINCT_COUNT "
        f"FROM {safe_from_table} f "
        f"JOIN {safe_to_table} t ON f.{safe_from_column} = t.{safe_to_column} "
        f"WHERE f.{safe_from_column} IS NOT NULL AND t.{safe_to_column} IS NOT NULL"
    )


def build_sample_query(from_table: str, from_column: str, to_table: str, to_column: str) -> str:
    safe_from_table = _safe_identifier(from_table)
    safe_from_column = _safe_identifier(from_column)
    safe_to_table = _safe_identifier(to_table)
    safe_to_column = _safe_identifier(to_column)
    return (
        f"SELECT f.{safe_from_column} AS FROM_VALUE, COUNT(*) AS MATCHES "
        f"FROM {safe_from_table} f "
        f"JOIN {safe_to_table} t ON f.{safe_from_column} = t.{safe_to_column} "
        f"WHERE f.{safe_from_column} IS NOT NULL "
        f"GROUP BY f.{safe_from_column} "
        f"FETCH FIRST 20 ROWS ONLY"
    )


def collect_candidate_evidence(
    connection: Any,
    candidate: RelationshipCandidate,
    *,
    from_column_type: str | None = None,
    to_column_type: str | None = None,
) -> RelationshipEvidence:
    cursor = connection.cursor()
    try:
        source_distinct_count = _run_scalar(cursor, build_distinct_count_query(candidate.from_table, candidate.from_column))
        target_distinct_count = _run_scalar(cursor, build_distinct_count_query(candidate.to_table, candidate.to_column))
        matched_distinct_count = _run_scalar(
            cursor,
            build_match_distinct_query(
                candidate.from_table,
                candidate.from_column,
                candidate.to_table,
                candidate.to_column,
                distinct_side="from",
            ),
        )
        reverse_matched_distinct_count = _run_scalar(
            cursor,
            build_match_distinct_query(
                candidate.from_table,
                candidate.from_column,
                candidate.to_table,
                candidate.to_column,
                distinct_side="to",
            ),
        )
        total_from, non_null_from = _run_pair(cursor, build_null_rate_query(candidate.from_table, candidate.from_column))
        total_to, non_null_to = _run_pair(cursor, build_null_rate_query(candidate.to_table, candidate.to_column))
        cursor.execute(build_sample_query(candidate.from_table, candidate.from_column, candidate.to_table, candidate.to_column))
        sample_matches = [
            {"from_value": row[0], "matches": int(row[1])}
            for row in cursor.fetchall()
        ]
    finally:
        cursor.close()

    return RelationshipEvidence(
        sampled=True,
        source_distinct_count=source_distinct_count,
        target_distinct_count=target_distinct_count,
        matched_distinct_count=matched_distinct_count,
        reverse_matched_distinct_count=reverse_matched_distinct_count,
        coverage_percent=_safe_percent(matched_distinct_count, source_distinct_count),
        reverse_coverage_percent=_safe_percent(reverse_matched_distinct_count, target_distinct_count),
        null_rate_from=_safe_percent(total_from - non_null_from, total_from),
        null_rate_to=_safe_percent(total_to - non_null_to, total_to),
        from_column_type=from_column_type,
        to_column_type=to_column_type,
        sample_matches=sample_matches,
    )


def _run_scalar(cursor: Any, sql: str) -> int:
    cursor.execute(sql)
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _run_pair(cursor: Any, sql: str) -> tuple[int, int]:
    cursor.execute(sql)
    row = cursor.fetchone()
    total = int(row[0]) if row and row[0] is not None else 0
    non_null = int(row[1]) if row and row[1] is not None else 0
    return total, non_null


def _safe_percent(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 4)


def _safe_identifier(value: str) -> str:
    clean = value.strip().upper()
    if not _SAFE_NAME.fullmatch(clean):
        raise ValueError(f"Identificador Oracle inseguro: {value}")
    return clean
