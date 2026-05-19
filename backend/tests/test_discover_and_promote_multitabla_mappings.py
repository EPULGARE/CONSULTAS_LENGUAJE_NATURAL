from pathlib import Path
import shutil
import uuid

import yaml

from scripts import discover_and_promote_multitabla_mappings as dap


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _seed_metadata(root: Path) -> None:
    (root / "metadata" / "generated").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "curated").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "tables.yml").write_text(
        yaml.safe_dump(
            {
                "tables": [
                    {
                        "schema": "SAC",
                        "name": "CLIENTES",
                        "domain": "clientes",
                        "columns": [{"name": "ESTADO_SUMINISTRO", "type": "NUMBER"}],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "metadata" / "generated" / "oracle_comments.yml").write_text(
        yaml.safe_dump(
            {
                "tables": {
                    "SAC.CLIENTES": {
                        "columns": {
                            "ESTADO_SUMINISTRO": {"detected_parametric_hint": "CLI_SUMINISTRO"}
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "metadata" / "curated" / "business_overrides.yml").write_text(
        yaml.safe_dump({"approved_parametric_mappings": []}, sort_keys=False),
        encoding="utf-8",
    )


class FakeCursor:
    def __init__(self, coverage_ok: bool):
        self.sql = ""
        self.coverage_ok = coverage_ok

    def execute(self, sql, binds=None):
        self.sql = " ".join(str(sql).split()).upper()

    def fetchone(self):
        if "COUNT(*) FROM SAC.MULTITABLA WHERE TABLA" in self.sql:
            return (10,)
        if "COUNT(DISTINCT T.ESTADO_SUMINISTRO)" in self.sql and "JOIN" not in self.sql:
            return (10,)
        if "COUNT(DISTINCT T.ESTADO_SUMINISTRO)" in self.sql and "JOIN" in self.sql:
            return (10 if self.coverage_ok else 5,)
        if "MT.DESCRIPCION IS NULL" in self.sql:
            return (0,)
        return (0,)

    def close(self):
        return None


class FakeConn:
    def __init__(self, coverage_ok: bool):
        self.coverage_ok = coverage_ok

    def cursor(self):
        return FakeCursor(self.coverage_ok)

    def close(self):
        return None


def test_no_autoapprove_when_coverage_low(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.get_settings", lambda: type("S", (), {
            "db_user": "u",
            "db_password": "p",
            "db_host": "h",
            "db_port": 1521,
            "db_sid": "",
            "db_service_name": "svc",
            "db_timeout_seconds": 5,
        })())
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.oracledb.connect", lambda **kwargs: FakeConn(False))
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.oracledb.makedsn", lambda *args, **kwargs: "dsn")
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.build_context_from_catalog.run", lambda **kwargs: 0)
        rc = dap.run(schema="SAC", tables=["CLIENTES"], min_coverage=0.95, output="metadata/generated/multitabla_mapping_evidence.yml", overwrite=True, project_root=root)
        assert rc == 0
        evidence = yaml.safe_load((root / "metadata" / "generated" / "multitabla_mapping_evidence.yml").read_text(encoding="utf-8"))
        assert evidence["mappings"][0]["auto_approved"] is False
    finally:
        _cleanup(root)


def test_autoapprove_when_coverage_high_and_no_duplicates(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.get_settings", lambda: type("S", (), {
            "db_user": "u",
            "db_password": "p",
            "db_host": "h",
            "db_port": 1521,
            "db_sid": "",
            "db_service_name": "svc",
            "db_timeout_seconds": 5,
        })())
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.oracledb.connect", lambda **kwargs: FakeConn(True))
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.oracledb.makedsn", lambda *args, **kwargs: "dsn")
        monkeypatch.setattr("scripts.discover_and_promote_multitabla_mappings.build_context_from_catalog.run", lambda **kwargs: 0)
        rc1 = dap.run(schema="SAC", tables=["CLIENTES"], min_coverage=0.95, output="metadata/generated/multitabla_mapping_evidence.yml", overwrite=True, project_root=root)
        rc2 = dap.run(schema="SAC", tables=["CLIENTES"], min_coverage=0.95, output="metadata/generated/multitabla_mapping_evidence.yml", overwrite=True, project_root=root)
        assert rc1 == 0
        assert rc2 == 0
        overrides = yaml.safe_load((root / "metadata" / "curated" / "business_overrides.yml").read_text(encoding="utf-8"))
        rows = overrides.get("approved_parametric_mappings", [])
        assert len(rows) == 1
        assert rows[0]["source_column"] == "ESTADO_SUMINISTRO"
        assert rows[0]["fixed_filter"] == "SAC.MULTITABLA.TABLA = 'CLI_SUMINISTRO'"
    finally:
        _cleanup(root)

