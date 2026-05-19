from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import oracledb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from scripts import build_context_from_catalog  # noqa: E402
from scripts.inspect_oracle_schema import parse_table_names, validate_schema_name  # noqa: E402

SAFE_HINT_PATTERN = re.compile(r"^[A-Z0-9_]+$")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _build_dsn(settings: Any) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(settings.db_host, settings.db_port, service_name=settings.db_service_name)


def resolve_output_path(output_arg: str, overwrite: bool = False, project_root: Path = PROJECT_ROOT) -> Path:
    target_root = (project_root / "metadata" / "generated").resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    output = Path(output_arg)
    output = (project_root / output).resolve() if not output.is_absolute() else output.resolve()
    if target_root != output and target_root not in output.parents:
        raise ValueError("--output debe estar dentro de metadata/generated/")
    if output.exists() and not overwrite:
        raise FileExistsError("El archivo de salida ya existe. Use --overwrite")
    return output


def _extract_hint(comment_hint: str) -> str | None:
    raw = (comment_hint or "").strip().upper()
    if not raw:
        return None
    return raw if SAFE_HINT_PATTERN.fullmatch(raw) else None


def _column_type_index(metadata_root: Path) -> dict[tuple[str, str], str]:
    tables = (_load_yaml(metadata_root / "tables.yml").get("tables") or [])
    idx: dict[tuple[str, str], str] = {}
    for t in tables:
        full = f"{t.get('schema')}.{t.get('name')}".upper()
        for c in (t.get("columns") or []):
            idx[(full, str(c.get("name", "")).upper())] = str(c.get("type", "")).upper()
    return idx


def _collect_candidates(metadata_root: Path, schema: str, tables: list[str]) -> list[dict[str, str]]:
    comments = _load_yaml(metadata_root / "generated" / "oracle_comments.yml")
    selected_tables = {f"{schema}.{t}".upper() for t in tables}
    out: list[dict[str, str]] = []
    for full_name, table_info in (comments.get("tables") or {}).items():
        full_up = str(full_name).upper()
        if full_up not in selected_tables:
            continue
        for col_name, col_info in ((table_info or {}).get("columns") or {}).items():
            hint = _extract_hint(str((col_info or {}).get("detected_parametric_hint") or ""))
            if not hint:
                continue
            out.append(
                {
                    "source_table": full_up,
                    "source_column": str(col_name).upper(),
                    "hint": hint,
                }
            )
    return out


def _count(cursor: Any, sql: str, binds: dict[str, Any]) -> int:
    cursor.execute(sql, binds)
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _safe_join_condition(source_column: str, lookup_key: str, source_type: str) -> str:
    source_is_number = "NUMBER" in (source_type or "").upper()
    if lookup_key == "CODIGO_NUM":
        mt_num = (
            "CASE "
            "WHEN REGEXP_LIKE(TRIM(TO_CHAR(mt.CODIGO_NUM)), '^[+-]?\\d+(\\.\\d+)?$') "
            "THEN TO_NUMBER(TRIM(TO_CHAR(mt.CODIGO_NUM))) "
            "END"
        )
        if source_is_number:
            return f"t.{source_column} = {mt_num}"
        # Evita ORA-01722 cuando la columna origen textual trae valores no numericos.
        source_num = (
            f"CASE "
            f"WHEN REGEXP_LIKE(TRIM(t.{source_column}), '^[+-]?\\d+(\\.\\d+)?$') "
            f"THEN TO_NUMBER(TRIM(t.{source_column})) "
            f"END"
        )
        return f"{source_num} = {mt_num}"
    if source_is_number:
        return f"TO_CHAR(t.{source_column}) = TO_CHAR(mt.CODIGO_CAR)"
    return f"TO_CHAR(t.{source_column}) = TO_CHAR(mt.CODIGO_CAR)"


def _build_evidence_rows(
    *,
    conn: Any,
    schema: str,
    candidates: list[dict[str, str]],
    col_types: dict[tuple[str, str], str],
    min_coverage: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = conn.cursor()
    try:
        for item in candidates:
            source_table = item["source_table"]
            source_column = item["source_column"]
            hint = item["hint"]
            source_type = col_types.get((source_table, source_column), "")
            lookup_key = "CODIGO_NUM" if "NUMBER" in source_type else "CODIGO_CAR"
            fixed_filter = f"SAC.MULTITABLA.TABLA = '{hint}'"
            join_condition = _safe_join_condition(source_column, lookup_key, source_type)

            multitabla_count = _count(
                cursor,
                f"SELECT COUNT(*) FROM {schema}.MULTITABLA WHERE TABLA = :hint",
                {"hint": hint},
            )
            source_distinct_values = _count(
                cursor,
                f"SELECT COUNT(DISTINCT t.{source_column}) FROM {source_table} t WHERE t.{source_column} IS NOT NULL",
                {},
            )
            matched_distinct_values = _count(
                cursor,
                (
                    f"SELECT COUNT(DISTINCT t.{source_column}) "
                    f"FROM {source_table} t "
                    f"JOIN {schema}.MULTITABLA mt ON {join_condition} AND mt.TABLA = :hint "
                    f"WHERE t.{source_column} IS NOT NULL"
                ),
                {"hint": hint},
            )
            null_desc_count = _count(
                cursor,
                (
                    f"SELECT COUNT(*) "
                    f"FROM {source_table} t "
                    f"JOIN {schema}.MULTITABLA mt ON {join_condition} AND mt.TABLA = :hint "
                    f"WHERE t.{source_column} IS NOT NULL AND mt.DESCRIPCION IS NULL"
                ),
                {"hint": hint},
            )
            coverage = 0.0 if source_distinct_values == 0 else float(matched_distinct_values) / float(source_distinct_values)
            auto_approved = (
                multitabla_count > 0
                and source_distinct_values > 0
                and coverage >= min_coverage
                and null_desc_count == 0
            )
            rows.append(
                {
                    "source_table": source_table,
                    "source_column": source_column,
                    "lookup_table": "SAC.MULTITABLA",
                    "lookup_key": lookup_key,
                    "lookup_description": "DESCRIPCION",
                    "fixed_filter": fixed_filter,
                    "multitabla_count": multitabla_count,
                    "source_distinct_values": source_distinct_values,
                    "matched_distinct_values": matched_distinct_values,
                    "coverage": round(coverage, 6),
                    "confidence": "high" if auto_approved else "low",
                    "auto_approved": auto_approved,
                }
            )
    finally:
        cursor.close()
    return rows


def _mapping_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item.get("source_table", "")).upper(),
        str(item.get("source_column", "")).upper(),
        str(item.get("lookup_table", "")).upper(),
        str(item.get("lookup_key", "")).upper(),
        str(item.get("fixed_filter", "")).upper(),
    )


def _promote_approved(metadata_root: Path, evidence_rows: list[dict[str, Any]]) -> int:
    overrides_path = metadata_root / "curated" / "business_overrides.yml"
    overrides = _load_yaml(overrides_path)
    approved = list(overrides.get("approved_parametric_mappings") or [])
    existing = {_mapping_key(x) for x in approved}
    added = 0
    for row in evidence_rows:
        if not row.get("auto_approved"):
            continue
        candidate = {
            "source_table": row["source_table"],
            "source_column": row["source_column"],
            "lookup_table": row["lookup_table"],
            "lookup_key": row["lookup_key"],
            "lookup_description": row["lookup_description"],
            "fixed_filter": row["fixed_filter"],
        }
        key = _mapping_key(candidate)
        if key in existing:
            continue
        approved.append(candidate)
        existing.add(key)
        added += 1
    overrides["approved_parametric_mappings"] = approved
    _write_yaml(overrides_path, overrides)
    return added


def run(
    *,
    schema: str,
    tables: list[str],
    min_coverage: float,
    output: str,
    overwrite: bool = False,
    project_root: Path = PROJECT_ROOT,
) -> int:
    safe_schema = validate_schema_name(schema)
    metadata_root = project_root / "metadata"
    output_path = resolve_output_path(output, overwrite=overwrite, project_root=project_root)
    candidates = _collect_candidates(metadata_root, safe_schema, tables)
    col_types = _column_type_index(metadata_root)
    settings = get_settings()
    conn = None
    try:
        conn = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=_build_dsn(settings),
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        rows = _build_evidence_rows(
            conn=conn,
            schema=safe_schema,
            candidates=candidates,
            col_types=col_types,
            min_coverage=min_coverage,
        )
        payload = {"mappings": rows}
        _write_yaml(output_path, payload)
        promoted = _promote_approved(metadata_root, rows)
        if promoted > 0:
            build_context_from_catalog.run(overwrite=True, project_root=project_root)
        print("Estado: OK")
        print(f"candidates: {len(candidates)}")
        print(f"auto_approved: {sum(1 for r in rows if r.get('auto_approved'))}")
        print(f"promoted: {promoted}")
        print(f"output: {output_path}")
        return 0
    except Exception as exc:
        msg = str(exc)
        if settings.db_password:
            msg = msg.replace(settings.db_password, "***")
        print("Estado: ERROR")
        print(msg)
        return 1
    finally:
        if conn is not None:
            conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Descubre y promueve mappings de MULTITABLA por evidencia fuerte")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--min-coverage", type=float, default=0.95)
    parser.add_argument("--output", default="metadata/generated/multitabla_mapping_evidence.yml")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(
        schema=args.schema,
        tables=parse_table_names(args.tables),
        min_coverage=float(args.min_coverage),
        output=args.output,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
