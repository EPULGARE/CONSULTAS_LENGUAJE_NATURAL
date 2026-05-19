from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import oracledb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_catalog.models import TableMetadata
from app.semantic_catalog.readiness import validate_catalog_ready

IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _build_dsn(settings: Any) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(settings.db_host, settings.db_port, service_name=settings.db_service_name)


def _normalize_identifier(value: str) -> str:
    normalized = value.strip().upper()
    if not IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"Identificador invalido en catalogo: {value}")
    return normalized


def _resolve_json_output(path_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    outputs_root = (project_root / "outputs").resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(path_arg)
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()
    else:
        output_path = output_path.resolve()
    if outputs_root != output_path and outputs_root not in output_path.parents:
        raise ValueError("--json-output debe estar dentro de outputs/")
    return output_path


def _select_non_sensitive_columns(table: TableMetadata) -> list[str]:
    sensitive_names = {col.upper() for col in table.sensitive_columns}
    selectable = []
    for col in table.columns:
        name = _normalize_identifier(col.name)
        if not col.allowed_for_select:
            continue
        if col.sensitive:
            continue
        if name in sensitive_names:
            continue
        selectable.append(name)
    return selectable


def _fetch_oracle_columns(cursor: Any, schema_name: str, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM ALL_TAB_COLUMNS
        WHERE OWNER = :owner
          AND TABLE_NAME = :table_name
        """,
        {"owner": schema_name, "table_name": table_name},
    )
    return {str(row[0]).upper() for row in cursor.fetchall()}


def run_smoke_test(
    *,
    domain: str | None = None,
    max_tables: int = 20,
    fail_fast: bool = False,
    json_output: Path | None = None,
) -> int:
    settings = get_settings()
    loader = SemanticCatalogLoader(settings.metadata_path)
    domains = loader.load_domains()
    tables = loader.load_tables()
    if domain:
        tables = [table for table in tables if table.domain == domain]

    readiness = validate_catalog_ready(domains=domains, tables=tables)
    if not readiness.ready:
        print("Estado: ERROR")
        print("Semantic catalog is not ready for query generation.")
        for err in readiness.errors:
            print(f"- {err}")
        return 1

    allowed_tables = [table for table in tables if table.allowed_for_query][:max_tables]
    report: dict[str, Any] = {
        "status": "OK",
        "domain": domain or "",
        "tables_validated": 0,
        "columns_validated": 0,
        "tables_missing": [],
        "columns_missing": [],
        "warnings": [],
    }

    connection = None
    cursor = None
    try:
        dsn = _build_dsn(settings)
        connection = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=dsn,
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        cursor = connection.cursor()

        for table in allowed_tables:
            schema_name = _normalize_identifier(table.schema_name)
            table_name = _normalize_identifier(table.name)
            full_name = f"{schema_name}.{table_name}"
            oracle_columns = _fetch_oracle_columns(cursor, schema_name, table_name)
            if not oracle_columns:
                report["tables_missing"].append(full_name)
                report["status"] = "ERROR"
                if fail_fast:
                    break
                continue

            selected_columns = _select_non_sensitive_columns(table)
            if not selected_columns:
                report["warnings"].append(f"{full_name}: sin columnas no sensibles seleccionables")
                continue

            missing_columns = [col for col in selected_columns if col not in oracle_columns]
            if missing_columns:
                for col in missing_columns:
                    report["columns_missing"].append(f"{full_name}.{col}")
                report["status"] = "ERROR"
                if fail_fast:
                    break
                continue

            projection = ", ".join(selected_columns)
            probe_sql = f"SELECT {projection} FROM {full_name} WHERE 1=0"
            cursor.execute(probe_sql)
            cursor.fetchall()
            report["tables_validated"] += 1
            report["columns_validated"] += len(selected_columns)

        if report["tables_missing"] or report["columns_missing"]:
            report["status"] = "ERROR"

        print(f"Estado: {report['status']}")
        print(f"tablas_validadas: {report['tables_validated']}")
        print(f"columnas_validadas: {report['columns_validated']}")
        print(f"tablas_faltantes: {len(report['tables_missing'])}")
        print(f"columnas_faltantes: {len(report['columns_missing'])}")
        if report["warnings"]:
            print(f"warnings: {len(report['warnings'])}")

        if json_output is not None:
            json_output.parent.mkdir(parents=True, exist_ok=True)
            json_output.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
            print(f"json_output: {json_output}")
        return 0 if report["status"] == "OK" else 1
    except Exception as exc:
        message = str(exc).replace(settings.db_password, "***") if settings.db_password else str(exc)
        print("Estado: ERROR")
        print(message)
        return 1
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Valida catalogo promovido contra Oracle sin consultar datos de negocio")
    parser.add_argument("--domain", required=False, help="Filtra tablas por dominio")
    parser.add_argument("--max-tables", type=int, default=20, help="Maximo de tablas allowed_for_query a validar")
    parser.add_argument("--fail-fast", action="store_true", help="Detenerse en el primer error")
    parser.add_argument("--json-output", required=False, help="Salida JSON dentro de outputs/")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.max_tables <= 0:
        raise SystemExit("--max-tables debe ser mayor que 0")

    json_output = _resolve_json_output(args.json_output) if args.json_output else None
    return run_smoke_test(
        domain=args.domain,
        max_tables=args.max_tables,
        fail_fast=args.fail_fast,
        json_output=json_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
