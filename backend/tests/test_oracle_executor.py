from unittest.mock import patch

from app.core.config import settings
from app.sql.dialects import SQLDialect
from app.sql.executor import SQLExecutor


def test_builds_dsn_with_service_name():
    with patch("app.sql.executor.oracledb.makedsn", return_value="dsn_service") as mock_makedsn:
        SQLExecutor(dialect=SQLDialect.ORACLE)
        mock_makedsn.assert_called_once()
        kwargs = mock_makedsn.call_args.kwargs
        assert kwargs.get("service_name") == settings.db_service_name


def test_supports_sid_when_configured(monkeypatch):
    monkeypatch.setattr("app.sql.executor.settings.db_sid", "ORCLCDB")
    with patch("app.sql.executor.oracledb.makedsn", return_value="dsn_sid") as mock_makedsn:
        SQLExecutor(dialect=SQLDialect.ORACLE)
        kwargs = mock_makedsn.call_args.kwargs
        assert kwargs.get("sid") == "ORCLCDB"


def test_does_not_expose_password_in_error(monkeypatch):
    monkeypatch.setattr("app.sql.executor.settings.db_password", "secret_pwd")

    class FakeOracleError(Exception):
        pass

    def _raise_connect(**kwargs):
        raise FakeOracleError("cannot connect with secret_pwd")

    with patch("app.sql.executor.oracledb.connect", side_effect=_raise_connect):
        executor = SQLExecutor(dialect=SQLDialect.ORACLE)
        try:
            executor.execute("SELECT 1 FROM DUAL")
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "secret_pwd" not in str(exc)


def test_executor_is_mockable_without_real_connection(monkeypatch):
    class FakeCursor:
        description = [("COL1",)]

        def execute(self, sql):
            return None

        def fetchall(self):
            return [(1,), (2,)]

        def close(self):
            return None

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr("app.sql.executor.oracledb.connect", lambda **kwargs: FakeConn())
    executor = SQLExecutor(dialect=SQLDialect.ORACLE)
    result = executor.execute("SELECT COL1 FROM DUAL FETCH FIRST 2 ROWS ONLY")
    assert result["columns"] == ["COL1"]
    assert result["row_count"] == 2
