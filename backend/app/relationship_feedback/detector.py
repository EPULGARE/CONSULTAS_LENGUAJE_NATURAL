from __future__ import annotations

from sqlglot import exp

from app.relationship_feedback.models import DetectedRelationshipJoin
from app.semantic_catalog.models import ParametricMapping, RelationshipMetadata


def detect_unapproved_join_candidates(
    statement: exp.Select,
    *,
    alias_map: dict[str, str],
    approved_relationships: list[RelationshipMetadata] | None = None,
    approved_parametric_mappings: list[ParametricMapping] | None = None,
) -> list[DetectedRelationshipJoin]:
    approved_pairs = _approved_relationship_pairs(approved_relationships or [])
    approved_parametric_pairs = _approved_parametric_pairs(approved_parametric_mappings or [])
    lookup_tables = {
        _normalize_table_name(mapping.lookup_table)
        for mapping in (approved_parametric_mappings or [])
        if mapping.lookup_table
    }

    detected: list[DetectedRelationshipJoin] = []
    seen: set[tuple[str, str, str, str]] = set()
    for eq_node in statement.find_all(exp.EQ):
        if not isinstance(eq_node.left, exp.Column) or not isinstance(eq_node.right, exp.Column):
            continue
        left_table = alias_map.get((eq_node.left.table or "").upper(), (eq_node.left.table or "").upper())
        right_table = alias_map.get((eq_node.right.table or "").upper(), (eq_node.right.table or "").upper())
        left_norm = _normalize_table_name(left_table)
        right_norm = _normalize_table_name(right_table)
        left_col = (eq_node.left.name or "").upper()
        right_col = (eq_node.right.name or "").upper()
        if not left_norm or not right_norm or not left_col or not right_col:
            continue
        if left_norm == right_norm:
            continue
        pair = (left_norm, left_col, right_norm, right_col)
        reverse_pair = (right_norm, right_col, left_norm, left_col)
        if pair in approved_pairs or reverse_pair in approved_pairs:
            continue
        if pair in approved_parametric_pairs or reverse_pair in approved_parametric_pairs:
            continue
        if left_norm in lookup_tables or right_norm in lookup_tables:
            continue
        if pair in seen or reverse_pair in seen:
            continue
        seen.add(pair)
        detected.append(
            DetectedRelationshipJoin(
                from_table=left_norm,
                from_column=left_col,
                to_table=right_norm,
                to_column=right_col,
            )
        )
    return detected


def _approved_relationship_pairs(relationships: list[RelationshipMetadata]) -> set[tuple[str, str, str, str]]:
    output: set[tuple[str, str, str, str]] = set()
    for rel in relationships:
        output.add(
            (
                _normalize_table_name(rel.left_table),
                rel.left_column.upper(),
                _normalize_table_name(rel.right_table),
                rel.right_column.upper(),
            )
        )
    return output


def _approved_parametric_pairs(mappings: list[ParametricMapping]) -> set[tuple[str, str, str, str]]:
    output: set[tuple[str, str, str, str]] = set()
    for mapping in mappings:
        output.add(
            (
                _normalize_table_name(mapping.source_table),
                mapping.source_column.upper(),
                _normalize_table_name(mapping.lookup_table),
                mapping.lookup_key.upper(),
            )
        )
        output.add(
            (
                _normalize_table_name(mapping.lookup_table),
                mapping.lookup_key.upper(),
                _normalize_table_name(mapping.source_table),
                mapping.source_column.upper(),
            )
        )
    return output


def _normalize_table_name(table: str) -> str:
    return table.replace('"', "").replace("[", "").replace("]", "").strip().upper()
