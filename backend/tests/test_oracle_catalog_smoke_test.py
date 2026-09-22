from pathlib import Path

import pytest

from app.semantic_catalog.models import ColumnMetadata, DomainCatalog, TableMetadata
from scripts.oracle_catalog_smoke_test import _resolve_json_output, run_smoke_test


def _mock_catalog(monkeypatch, tables):
    monkeypatch.setattr(
        "scripts.oracle_catalog_smoke_test.SemanticCatalogLoader.load_domains",
        lambda self: [DomainCatalog(name="domain_alpha", description="d")],
    )
    monkeypatch.setattr("scripts.oracle_catalog_smoke_test.SemanticCatalogLoader.load_tables", lambda self: tables)


def test_json_output_outside_outputs_blocked():
    with pytest.raises(ValueError):
        _resolve_json_output("metadata/out.json")


def test_catalog_not_ready_fails_before_connect(monkeypatch):
    _mock_catalog(monkeypatch, [])
    called = {"connect": False}

    def fake_connect(**kwargs):
        called["connect"] = True
        raise AssertionError("should not connect")

    monkeypatch.setattr("scripts.oracle_catalog_smoke_test.oracledb.connect", fake_connect)
    result = run_smoke_test()
    assert result == 1
    assert called["connect"] is False


def test_smoke_test_no_select_star_and_uses_where_zero(monkeypatch):
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            columns=[ColumnMetadata(name="ID", type="number", allowed_for_select=True)],
        )
    ]
    _mock_catalog(monkeypatch, tables)
    executed_sql: list[str] = []

    class FakeCursor:
        def execute(self, sql, binds=None):
            executed_sql.append(sql)

        def fetchall(self):
            last = executed_sql[-1]
            if "ALL_TAB_COLUMNS" in last:
                return [("ID",)]
            return []

        def close(self):
            return None

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr("scripts.oracle_catalog_smoke_test.oracledb.connect", lambda **kwargs: FakeConn())
    result = run_smoke_test()
    assert result == 0
    joined = "\n".join(executed_sql).upper()
    assert "SELECT *" not in joined
    assert "WHERE 1=0" in joined


def test_sensitive_selectable_column_fails_catalog_smoke_test(monkeypatch):
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="SAFE_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            columns=[ColumnMetadata(name="PUBLIC_COL", type="varchar", allowed_for_select=True, sensitive=False)],
        ),
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            sensitive_columns=["SECRET_COL"],
            columns=[ColumnMetadata(name="SECRET_COL", type="varchar", allowed_for_select=True, sensitive=True)],
        )
    ]
    _mock_catalog(monkeypatch, tables)

    class FakeCursor:
        def execute(self, sql, binds=None):
            return None

        def fetchall(self):
            return [("PUBLIC_COL",), ("SECRET_COL",)]

        def close(self):
            return None

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr("scripts.oracle_catalog_smoke_test.oracledb.connect", lambda **kwargs: FakeConn())
    result = run_smoke_test()
    assert result == 1
