from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import oracledb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.sql.dialects import SQLDialect  # noqa: E402

TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")


def _mask_user(user: str) -> str:
    if not user:
        return "<empty>"
    if len(user) <= 2:
        return "*" * len(user)
    return user[0] + ("*" * (len(user) - 2)) + user[-1]


def _sanitize_error(message: str, password: str, user: str) -> str:
    clean = message
    if password:
        clean = clean.replace(password, "***")
    if user:
        clean = clean.replace(user, _mask_user(user))
    return clean


def _build_dsn(settings) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(
        settings.db_host,
        settings.db_port,
        service_name=settings.db_service_name,
    )


def _validate_table_name(table_name: str) -> str:
    if not TABLE_PATTERN.match(table_name):
        raise ValueError("--test-table debe tener formato SCHEMA.TABLE")
    return table_name


def run_health_check(test_table: str | None = None, sample_rows: int = 0) -> int:
    settings = get_settings()
    dsn = _build_dsn(settings)

    print("Estado: START")
    print(f"dialect: {settings.db_dialect.value if isinstance(settings.db_dialect, SQLDialect) else settings.db_dialect}")
    print(f"host: {settings.db_host}")
    print(f"port: {settings.db_port}")
    print(f"service_name: {settings.db_service_name}")

    conn = None
    cursor = None
    try:
        conn = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=dsn,
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        probe = cursor.fetchone()

        print("Estado: OK")
        print(f"user: {_mask_user(settings.db_user)}")
        print(f"oracle_version: {getattr(conn, 'version', 'unknown')}")
        print(f"probe_result: {probe[0] if probe else 'null'}")

        if test_table:
            safe_table = _validate_table_name(test_table)
            print(f"test_table: {safe_table}")
            cursor.execute(f"SELECT COUNT(*) FROM {safe_table} WHERE 1=0")
            no_data_probe = cursor.fetchone()
            print(f"safe_probe_result: {no_data_probe[0] if no_data_probe else 'null'}")

            if sample_rows > 0:
                print("WARNING: --sample-rows expone datos de negocio en consola.")
                cursor.execute(f"SELECT * FROM {safe_table} FETCH FIRST {sample_rows} ROWS ONLY")
                columns = [d[0] for d in (cursor.description or [])]
                rows = cursor.fetchmany(sample_rows)
                print(f"columns: {columns}")
                print("rows:")
                for row in rows:
                    print(list(row))

        return 0
    except Exception as exc:
        print("Estado: ERROR")
        print(_sanitize_error(str(exc), settings.db_password, settings.db_user))
        return 1
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida conexion Oracle de forma segura usando .env")
    parser.add_argument(
        "--test-table",
        dest="test_table",
        required=False,
        help="Tabla de prueba en formato SCHEMA.TABLE",
    )
    parser.add_argument(
        "--sample-rows",
        dest="sample_rows",
        type=int,
        default=0,
        help="Opcional: muestra N filas reales de --test-table (riesgo de exponer datos).",
    )
    args = parser.parse_args()

    if args.sample_rows < 0:
        raise SystemExit("--sample-rows debe ser >= 0")

    return run_health_check(test_table=args.test_table, sample_rows=args.sample_rows)


if __name__ == "__main__":
    raise SystemExit(main())
