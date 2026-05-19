from __future__ import annotations

from typing import Any

import oracledb
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.sql.dialects import SQLDialect


class SQLExecutor:
    def __init__(
        self,
        *,
        dialect: SQLDialect | None = None,
        timeout_seconds: int | None = None,
        db_url: str | None = None,
    ) -> None:
        self.dialect = dialect or settings.db_dialect
        self.timeout_seconds = timeout_seconds or settings.db_timeout_seconds
        self._db_url = db_url or settings.db_url

        if self.dialect == SQLDialect.ORACLE:
            self.dsn = self._build_oracle_dsn(
                host=settings.db_host,
                port=settings.db_port,
                service_name=settings.db_service_name,
                sid=settings.db_sid,
            )
            self._engine = None
        else:
            connect_args: dict[str, Any] = {}
            if self._db_url.startswith("sqlite"):
                connect_args["timeout"] = self.timeout_seconds
            self._engine = create_engine(self._db_url, connect_args=connect_args, pool_pre_ping=True)
            self.dsn = None

    @staticmethod
    def _build_oracle_dsn(*, host: str, port: int, service_name: str, sid: str = "") -> str:
        if sid:
            return oracledb.makedsn(host, port, sid=sid)
        return oracledb.makedsn(host, port, service_name=service_name)

    def execute(self, sql: str) -> dict[str, Any]:
        if self.dialect == SQLDialect.ORACLE:
            return self._execute_oracle(sql)
        return self._execute_sqlalchemy(sql)

    def _execute_oracle(self, sql: str) -> dict[str, Any]:
        connection = None
        cursor = None
        try:
            connection = oracledb.connect(
                user=settings.db_user,
                password=settings.db_password,
                dsn=self.dsn,
                tcp_connect_timeout=self.timeout_seconds,
            )
            cursor = connection.cursor()
            cursor.execute(sql)
            columns = [d[0] for d in (cursor.description or [])]
            fetched = cursor.fetchall()
            rows = [dict(zip(columns, row)) for row in fetched]
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "limited": "FETCH FIRST" in sql.upper(),
            }
        except Exception as exc:
            message = str(exc).replace(settings.db_password, "***") if settings.db_password else str(exc)
            raise RuntimeError(f"Error ejecutando consulta Oracle: {message}") from exc
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

    def _execute_sqlalchemy(self, sql: str) -> dict[str, Any]:
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = [dict(row._mapping) for row in result.fetchall()]
                columns = list(rows[0].keys()) if rows else []
                return {
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "limited": "LIMIT" in sql.upper() or "FETCH FIRST" in sql.upper(),
                }
        except SQLAlchemyError as exc:
            raise RuntimeError("Error ejecutando consulta") from exc
