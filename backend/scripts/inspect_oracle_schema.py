from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oracledb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.sql.dialects import SQLDialect  # noqa: E402

SCHEMA_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def validate_schema_name(schema: str) -> str:
    value = schema.strip().upper()
    if not SCHEMA_PATTERN.fullmatch(value):
        raise ValueError("--schema invalido. Use solo letras, numeros y guion bajo")
    return value


def parse_table_names(raw_tables: str) -> list[str]:
    if not raw_tables.strip():
        raise ValueError("--tables no puede estar vacio")

    items = [item.strip().upper() for item in raw_tables.split(",") if item.strip()]
    if not items:
        raise ValueError("--tables no puede estar vacio")

    for table in items:
        if not TABLE_PATTERN.fullmatch(table):
            raise ValueError("--tables invalido. Solo se permiten nombres simples separados por coma")

    return list(dict.fromkeys(items))


def _mask_user(user: str) -> str:
    if not user:
        return "<empty>"
    if len(user) <= 2:
        return "*" * len(user)
    return user[0] + ("*" * (len(user) - 2)) + user[-1]


def sanitize_error(message: str, password: str, user: str) -> str:
    clean = message
    if password:
        clean = clean.replace(password, "***")
    if user:
        clean = clean.replace(user, _mask_user(user))
    return clean


def resolve_output_path(output_arg: str, *, project_root: Path = PROJECT_ROOT, overwrite: bool = False) -> Path:
    target_root = (project_root / "metadata" / "generated").resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    output_path = Path(output_arg)
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()
    else:
        output_path = output_path.resolve()

    if target_root != output_path and target_root not in output_path.parents:
        raise ValueError("--output debe estar dentro de metadata/generated/")

    if output_path.exists() and not overwrite:
        raise FileExistsError("El archivo de salida ya existe. Use --overwrite para reemplazar")

    return output_path


def _build_dsn(settings: Any) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(settings.db_host, settings.db_port, service_name=settings.db_service_name)


def _build_in_clause(values: list[str], prefix: str) -> tuple[str, dict[str, str]]:
    binds: dict[str, str] = {}
    placeholders = []
    for index, value in enumerate(values):
        key = f"{prefix}{index}"
        placeholders.append(f":{key}")
        binds[key] = value
    return ", ".join(placeholders), binds


def fetch_metadata(connection: Any, *, schema: str, tables: list[str]) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        in_clause, table_binds = _build_in_clause(tables, "t")
        binds = {"owner": schema, **table_binds}

        cursor.execute(
            f"""
            SELECT OWNER, OBJECT_NAME, OBJECT_TYPE
            FROM (
                SELECT OWNER, TABLE_NAME AS OBJECT_NAME, 'TABLE' AS OBJECT_TYPE
                FROM ALL_TABLES
                WHERE OWNER = :owner
                  AND TABLE_NAME IN ({in_clause})
                UNION ALL
                SELECT OWNER, VIEW_NAME AS OBJECT_NAME, 'VIEW' AS OBJECT_TYPE
                FROM ALL_VIEWS
                WHERE OWNER = :owner
                  AND VIEW_NAME IN ({in_clause})
                UNION ALL
                SELECT OWNER, SYNONYM_NAME AS OBJECT_NAME, 'SYNONYM' AS OBJECT_TYPE
                FROM ALL_SYNONYMS
                WHERE OWNER = :owner
                  AND SYNONYM_NAME IN ({in_clause})
            )
            ORDER BY OBJECT_NAME, OBJECT_TYPE
            """,
            binds,
        )
        object_rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE, NULLABLE, DATA_LENGTH, DATA_PRECISION, DATA_SCALE
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = :owner
              AND TABLE_NAME IN ({in_clause})
            ORDER BY TABLE_NAME, COLUMN_ID
            """,
            binds,
        )
        column_rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT ac.OWNER, ac.TABLE_NAME, ac.CONSTRAINT_NAME, acc.COLUMN_NAME, acc.POSITION
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
              ON ac.OWNER = acc.OWNER
             AND ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
            WHERE ac.OWNER = :owner
              AND ac.TABLE_NAME IN ({in_clause})
              AND ac.CONSTRAINT_TYPE = 'P'
            ORDER BY ac.TABLE_NAME, ac.CONSTRAINT_NAME, acc.POSITION
            """,
            binds,
        )
        pk_rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT ac.OWNER,
                   ac.TABLE_NAME,
                   ac.CONSTRAINT_NAME,
                   acc.COLUMN_NAME,
                   rcc.OWNER AS REF_OWNER,
                   rcc.TABLE_NAME AS REF_TABLE,
                   rcc.COLUMN_NAME AS REF_COLUMN,
                   acc.POSITION
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
              ON ac.OWNER = acc.OWNER
             AND ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
            JOIN ALL_CONSTRAINTS rc
              ON ac.R_OWNER = rc.OWNER
             AND ac.R_CONSTRAINT_NAME = rc.CONSTRAINT_NAME
            JOIN ALL_CONS_COLUMNS rcc
              ON rc.OWNER = rcc.OWNER
             AND rc.CONSTRAINT_NAME = rcc.CONSTRAINT_NAME
             AND acc.POSITION = rcc.POSITION
            WHERE ac.OWNER = :owner
              AND ac.TABLE_NAME IN ({in_clause})
              AND ac.CONSTRAINT_TYPE = 'R'
            ORDER BY ac.TABLE_NAME, ac.CONSTRAINT_NAME, acc.POSITION
            """,
            binds,
        )
        fk_rows = cursor.fetchall()

        return {
            "objects": object_rows,
            "columns": column_rows,
            "primary_keys": pk_rows,
            "foreign_keys": fk_rows,
        }
    finally:
        cursor.close()


def build_catalog_proposal(*, schema: str, tables: list[str], metadata: dict[str, Any]) -> dict[str, Any]:
    object_lookup = {f"{row[0]}.{row[1]}": row for row in metadata["objects"]}

    column_map: dict[str, list[dict[str, Any]]] = {}
    for row in metadata["columns"]:
        full_name = f"{row[0]}.{row[1]}"
        column_map.setdefault(full_name, []).append(
            {
                "name": row[2],
                "data_type": row[3],
                "nullable": row[4],
                "data_length": row[5],
                "data_precision": row[6],
                "data_scale": row[7],
                "business_description": "TODO: describir uso de negocio",
            }
        )

    pk_map: dict[str, dict[str, list[str]]] = {}
    for row in metadata["primary_keys"]:
        full_name = f"{row[0]}.{row[1]}"
        constraint_name = row[2]
        pk_map.setdefault(full_name, {}).setdefault(constraint_name, []).append(row[3])

    fk_map: dict[str, dict[str, dict[str, Any]]] = {}
    for row in metadata["foreign_keys"]:
        full_name = f"{row[0]}.{row[1]}"
        constraint_name = row[2]
        source_column = row[3]
        ref_full_name = f"{row[4]}.{row[5]}"
        ref_column = row[6]

        fk_map.setdefault(full_name, {}).setdefault(
            constraint_name,
            {
                "references_table": ref_full_name,
                "column_mappings": [],
            },
        )
        fk_map[full_name][constraint_name]["column_mappings"].append(
            {
                "source_column": source_column,
                "target_column": ref_column,
            }
        )

    output_tables = []
    for table in tables:
        full_name = f"{schema}.{table}"
        if full_name not in object_lookup:
            continue

        output_tables.append(
            {
                "full_name": full_name,
                "description": "TODO: describir tabla en lenguaje de negocio",
                "domain_suggested": "TODO: asignar dominio",
                "synonyms": [],
                "columns": column_map.get(full_name, []),
                "primary_keys": [
                    {"constraint_name": name, "columns": cols}
                    for name, cols in pk_map.get(full_name, {}).items()
                ],
                "foreign_keys": [
                    {"constraint_name": name, **info}
                    for name, info in fk_map.get(full_name, {}).items()
                ],
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema": schema,
        "tables": output_tables,
    }


def build_table_diagnostics(*, schema: str, requested_tables: list[str], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    objects_by_name: dict[str, list[str]] = {}
    for owner, object_name, object_type in metadata["objects"]:
        objects_by_name.setdefault(f"{owner}.{object_name}", []).append(object_type)

    columns_by_name: dict[str, int] = {}
    for owner, table_name, *_ in metadata["columns"]:
        key = f"{owner}.{table_name}"
        columns_by_name[key] = columns_by_name.get(key, 0) + 1

    diagnostics: list[dict[str, Any]] = []
    for table in requested_tables:
        full_name = f"{schema}.{table}"
        object_types = sorted(set(objects_by_name.get(full_name, [])))
        column_count = columns_by_name.get(full_name, 0)
        status = "NOT_VISIBLE"
        if object_types and column_count > 0:
            status = "INTROSPECTABLE"
        elif object_types:
            status = "VISIBLE_WITHOUT_COLUMNS"

        diagnostics.append(
            {
                "full_name": full_name,
                "status": status,
                "object_types": object_types,
                "column_count": column_count,
            }
        )
    return diagnostics


def write_yaml(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, sort_keys=False, allow_unicode=False)


def run_inspection(*, schema: str, tables: list[str], output: str, overwrite: bool = False) -> int:
    settings = get_settings()
    safe_schema = validate_schema_name(schema)
    safe_tables = tables
    output_path = resolve_output_path(output, overwrite=overwrite)

    print("Estado: START")
    print(f"dialect: {settings.db_dialect.value if isinstance(settings.db_dialect, SQLDialect) else settings.db_dialect}")
    print(f"host: {settings.db_host}")
    print(f"port: {settings.db_port}")
    print(f"service_name: {settings.db_service_name}")
    print(f"schema: {safe_schema}")

    connection = None
    try:
        dsn = _build_dsn(settings)
        connection = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=dsn,
            tcp_connect_timeout=settings.db_timeout_seconds,
        )

        metadata = fetch_metadata(connection, schema=safe_schema, tables=safe_tables)
        proposal = build_catalog_proposal(schema=safe_schema, tables=safe_tables, metadata=metadata)
        diagnostics = build_table_diagnostics(schema=safe_schema, requested_tables=safe_tables, metadata=metadata)
        write_yaml(output_path, proposal)

        table_count = len(proposal["tables"])
        column_count = sum(len(t["columns"]) for t in proposal["tables"])
        pk_count = sum(len(t["primary_keys"]) for t in proposal["tables"])
        fk_count = sum(len(t["foreign_keys"]) for t in proposal["tables"])

        print("Estado: OK")
        print(f"tablas_inspeccionadas: {table_count}")
        print(f"columnas: {column_count}")
        print(f"pk_detectadas: {pk_count}")
        print(f"fk_detectadas: {fk_count}")
        print("diagnostico_tablas:")
        for item in diagnostics:
            object_types = ",".join(item["object_types"]) if item["object_types"] else "NONE"
            print(
                f"- {item['full_name']} status={item['status']} "
                f"tipos={object_types} columnas={item['column_count']}"
            )
        print(f"output: {output_path}")
        return 0
    except Exception as exc:
        print("Estado: ERROR")
        print(sanitize_error(str(exc), settings.db_password, settings.db_user))
        return 1
    finally:
        if connection is not None:
            connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspecciona metadata Oracle y genera propuesta YAML de catalogo")
    parser.add_argument("--schema", required=True, help="Schema Oracle objetivo")
    parser.add_argument("--tables", required=True, help="Lista separada por comas de tablas")
    parser.add_argument("--output", required=True, help="Ruta de salida dentro de metadata/generated/")
    parser.add_argument("--overwrite", action="store_true", help="Permite sobrescribir archivo de salida")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    parsed_tables = parse_table_names(args.tables)
    return run_inspection(schema=args.schema, tables=parsed_tables, output=args.output, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
