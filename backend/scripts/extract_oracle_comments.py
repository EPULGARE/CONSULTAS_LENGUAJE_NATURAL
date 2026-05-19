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

SCHEMA_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
HINT_PATTERNS = [
    re.compile(r"\[([A-Z0-9_]+)\]"),
    re.compile(r"\bTABLA\s+([A-Z0-9_]+)\b"),
    re.compile(r"\bPARAMETRIZAD[OA]\s+EN\s+([A-Z0-9_]+)\b"),
]


def validate_schema_name(schema: str) -> str:
    value = schema.strip().upper()
    if not SCHEMA_PATTERN.fullmatch(value):
        raise ValueError("--schema invalido")
    return value


def parse_table_names(raw_tables: str) -> list[str]:
    items = [item.strip().upper() for item in raw_tables.split(",") if item.strip()]
    if not items:
        raise ValueError("--tables no puede estar vacio")
    for item in items:
        if not TABLE_PATTERN.fullmatch(item):
            raise ValueError("--tables invalido")
    return list(dict.fromkeys(items))


def resolve_output_path(output_arg: str, overwrite: bool = False) -> Path:
    target_root = (PROJECT_ROOT / "metadata" / "generated").resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    output = Path(output_arg)
    output = (PROJECT_ROOT / output).resolve() if not output.is_absolute() else output.resolve()
    if target_root != output and target_root not in output.parents:
        raise ValueError("--output debe estar dentro de metadata/generated/")
    if output.exists() and not overwrite:
        raise FileExistsError("El archivo de salida ya existe. Use --overwrite")
    return output


def _build_dsn(settings: Any) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(settings.db_host, settings.db_port, service_name=settings.db_service_name)


def _build_in_clause(values: list[str], prefix: str) -> tuple[str, dict[str, str]]:
    binds: dict[str, str] = {}
    placeholders: list[str] = []
    for i, value in enumerate(values):
        key = f"{prefix}{i}"
        placeholders.append(f":{key}")
        binds[key] = value
    return ", ".join(placeholders), binds


def detect_parametric_hint(comment: str) -> tuple[str | None, str]:
    text = (comment or "").upper()
    for pattern in HINT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1), "low"
    if "CODIGO" in text and "DESCRIP" in text:
        return "CODES_DESCRIPTIONS_HINT", "low"
    return None, "low"


def extract_comments(connection: Any, schema: str, tables: list[str]) -> dict[str, Any]:
    in_clause, table_binds = _build_in_clause(tables, "t")
    binds = {"owner": schema, **table_binds}
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"""
            SELECT OWNER, TABLE_NAME, COMMENTS
            FROM ALL_TAB_COMMENTS
            WHERE OWNER = :owner
              AND TABLE_NAME IN ({in_clause})
            ORDER BY TABLE_NAME
            """,
            binds,
        )
        table_rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT OWNER, TABLE_NAME, COLUMN_NAME, COMMENTS
            FROM ALL_COL_COMMENTS
            WHERE OWNER = :owner
              AND TABLE_NAME IN ({in_clause})
            ORDER BY TABLE_NAME, COLUMN_NAME
            """,
            binds,
        )
        col_rows = cursor.fetchall()
    finally:
        cursor.close()

    output: dict[str, Any] = {"tables": {}}
    for owner, table_name, comments in table_rows:
        full_name = f"{owner}.{table_name}"
        output["tables"][full_name] = {"table_comment": comments or "", "columns": {}}

    for owner, table_name, column_name, comments in col_rows:
        full_name = f"{owner}.{table_name}"
        if full_name not in output["tables"]:
            output["tables"][full_name] = {"table_comment": "", "columns": {}}
        hint, confidence = detect_parametric_hint(comments or "")
        output["tables"][full_name]["columns"][column_name] = {
            "comment": comments or "",
            "detected_parametric_hint": hint,
            "confidence": confidence,
        }
    return output


def run(schema: str, tables: list[str], output: str, overwrite: bool = False) -> int:
    settings = get_settings()
    safe_schema = validate_schema_name(schema)
    safe_tables = tables
    out_path = resolve_output_path(output, overwrite=overwrite)

    print("Estado: START")
    print(f"schema: {safe_schema}")
    print(f"tables: {','.join(safe_tables)}")
    connection = None
    try:
        connection = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=_build_dsn(settings),
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        payload = extract_comments(connection, safe_schema, safe_tables)
        out_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
        print("Estado: OK")
        print(f"output: {out_path}")
        return 0
    except Exception as exc:
        print("Estado: ERROR")
        print(str(exc).replace(settings.db_password, "***") if settings.db_password else str(exc))
        return 1
    finally:
        if connection is not None:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extrae comentarios Oracle (ALL_TAB_COMMENTS/ALL_COL_COMMENTS)")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--output", default="metadata/generated/oracle_comments.yml")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    return run(
        schema=args.schema,
        tables=parse_table_names(args.tables),
        output=args.output,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
