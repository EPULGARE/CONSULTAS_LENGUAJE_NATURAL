from scripts.check_oracle_connection import run_health_check


def test_health_check_does_not_use_select_star_by_default(monkeypatch):
    executed_sql: list[str] = []

    class FakeCursor:
        description = [("DUMMY",)]

        def execute(self, sql):
            executed_sql.append(sql)

        def fetchone(self):
            return [1]

        def fetchmany(self, n):
            return []

        def close(self):
            return None

    class FakeConn:
        version = "test"

        def cursor(self):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr("scripts.check_oracle_connection.oracledb.connect", lambda **kwargs: FakeConn())
    exit_code = run_health_check(test_table="TEST_SCHEMA.TEST_TABLE")
    assert exit_code == 0
    assert any("WHERE 1=0" in sql for sql in executed_sql)
    assert not any("SELECT *" in sql.upper() for sql in executed_sql)
