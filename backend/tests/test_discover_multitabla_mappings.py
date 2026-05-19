from pathlib import Path
import shutil
import uuid

import pytest
import yaml

from scripts import discover_multitabla_mappings as dmm


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def test_detecta_hints_en_formatos_requeridos():
    assert dmm.extract_multitabla_hint("Estado [ESTAD]") == "ESTAD"
    assert dmm.extract_multitabla_hint("TABLA ESTAD para estados") == "ESTAD"
    assert dmm.extract_multitabla_hint("parametrizado en ESTAD") == "ESTAD"


def test_bloquea_hint_invalido():
    assert dmm.extract_multitabla_hint("Estado [EST-AD]") is None


def test_confidence_high_si_existe_en_multitabla():
    payload = dmm.build_suggestions(
        hints=[{"source_table": "SAC.MEDIDORES", "source_column": "ESTADO", "hint": "ESTAD", "comment_hint": ""}],
        available_multitabla={"ESTAD"},
        key_stats={"ESTAD": {"cnt_num": 10, "cnt_car": 0}},
    )
    row = payload["suggested_parametric_mappings"][0]
    assert row["confidence"] == "high"
    assert row["reason"] == "oracle_comment_hint_exact_match"
    assert row["candidate_key"] == "CODIGO_NUM"
    assert row["approved"] is False


def test_confidence_low_si_no_existe():
    payload = dmm.build_suggestions(
        hints=[{"source_table": "SAC.MEDIDORES", "source_column": "ESTADO", "hint": "NOPE", "comment_hint": ""}],
        available_multitabla={"ESTAD"},
        key_stats={},
    )
    row = payload["suggested_parametric_mappings"][0]
    assert row["confidence"] == "low"
    assert row["reason"] == "hint_not_found_in_multitabla"


def test_output_fuera_generated_bloqueado():
    root = _mk_workspace_tmp()
    try:
        with pytest.raises(ValueError):
            dmm.resolve_output_path("metadata/out.yml", overwrite=False, project_root=root)
    finally:
        _cleanup(root)


def test_no_modifica_business_overrides_y_no_consulta_negocio(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        (root / "metadata" / "generated").mkdir(parents=True, exist_ok=True)
        (root / "metadata" / "curated").mkdir(parents=True, exist_ok=True)
        business = root / "metadata" / "curated" / "business_overrides.yml"
        business.write_text("approved_parametric_mappings: []\n", encoding="utf-8")
        comments = root / "metadata" / "generated" / "oracle_comments.yml"
        comments.write_text(
            yaml.safe_dump(
                {
                    "tables": {
                        "SAC.MEDIDORES": {"columns": {"ESTADO": {"comment": "Campo [ESTAD]"}}}
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        output = "metadata/generated/multitabla_mapping_suggestions.yml"
        executed_sql: list[str] = []

        class FakeCursor:
            def __init__(self):
                self._query = ""

            def execute(self, query, binds=None):
                self._query = " ".join(str(query).split()).upper()
                executed_sql.append(self._query)

            def fetchall(self):
                if "SELECT DISTINCT TABLA" in self._query:
                    return [("ESTAD",)]
                if "COUNT(CODIGO_NUM)" in self._query:
                    return [("ESTAD", 5, 0)]
                return []

            def close(self):
                return None

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def close(self):
                return None

        monkeypatch.setattr("scripts.discover_multitabla_mappings.get_settings", lambda: type("S", (), {
            "db_user": "u",
            "db_password": "p",
            "db_host": "h",
            "db_port": 1521,
            "db_sid": "",
            "db_service_name": "svc",
            "db_timeout_seconds": 5,
        })())
        monkeypatch.setattr("scripts.discover_multitabla_mappings.oracledb.connect", lambda **kwargs: FakeConnection())
        monkeypatch.setattr("scripts.discover_multitabla_mappings.oracledb.makedsn", lambda *args, **kwargs: "dsn")

        rc = dmm.run(
            schema="SAC",
            tables=["MEDIDORES"],
            output=output,
            overwrite=True,
            project_root=root,
        )
        assert rc == 0
        saved = yaml.safe_load((root / output).read_text(encoding="utf-8"))
        assert len(saved["suggested_parametric_mappings"]) == 1
        assert business.read_text(encoding="utf-8") == "approved_parametric_mappings: []\n"
        assert all("MULTITABLA" in sql for sql in executed_sql)
    finally:
        _cleanup(root)
