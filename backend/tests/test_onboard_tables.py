from pathlib import Path
import shutil
import uuid

import pytest
import yaml

from scripts import onboard_tables as onboarding


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _seed_workspace(root: Path) -> None:
    metadata = root / "metadata"
    (metadata / "generated").mkdir(parents=True, exist_ok=True)
    (metadata / "approvals").mkdir(parents=True, exist_ok=True)
    (metadata / "context" / "tables").mkdir(parents=True, exist_ok=True)
    (metadata / "curated").mkdir(parents=True, exist_ok=True)
    (metadata / "tables.yml").write_text("tables: []\n", encoding="utf-8")
    (metadata / "relationships.yml").write_text("relationships: []\n", encoding="utf-8")
    (metadata / "curated" / "business_overrides.yml").write_text("approved_parametric_mappings: []\n", encoding="utf-8")
    (metadata / "generated" / "oracle_comments.yml").write_text("tables: {}\n", encoding="utf-8")


def _write_generated(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "tables": [
                    {
                        "full_name": "TEST_SCHEMA.TEST_TABLE",
                        "description": "",
                        "columns": [
                            {"name": "ID", "data_type": "NUMBER", "business_description": ""},
                            {"name": "CLIENTE_ID", "data_type": "NUMBER", "business_description": ""},
                            {"name": "NOMBRE", "data_type": "VARCHAR2", "business_description": ""},
                        ],
                        "primary_keys": ["ID"],
                        "foreign_keys": [],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_auto_approve_safe_columns_blocks_sensitive_for_select():
    root = _mk_workspace_tmp()
    try:
        _seed_workspace(root)
        approval = root / "metadata" / "approvals" / "x_review.yml"
        approval.write_text(
            yaml.safe_dump(
                {
                    "tables": [
                        {
                            "full_name": "TEST_SCHEMA.TEST_TABLE",
                            "columns": [{"name": "NOMBRE"}, {"name": "ID"}],
                            "relationships": [],
                        }
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        payload = onboarding.apply_auto_approve_safe_columns(approval, "medidores")
        cols = {c["name"]: c for c in payload["tables"][0]["columns"]}
        assert payload["tables"][0]["domain"] == "medidores"
        assert cols["NOMBRE"]["allowed_for_select"] is False
        assert cols["NOMBRE"]["approved"] is False
        assert cols["ID"]["allowed_for_select"] is True
        assert cols["ID"]["approved"] is True
    finally:
        _cleanup(root)


def test_onboard_generates_generated_and_review_without_promote(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _seed_workspace(root)
        generated_file = root / "metadata" / "generated" / "test_table.yml"

        monkeypatch.setattr("scripts.onboard_tables.PROJECT_ROOT", root)
        monkeypatch.setattr("scripts.onboard_tables.inspect_oracle_schema.run_inspection", lambda **kwargs: (_write_generated(generated_file) or 0))
        monkeypatch.setattr("scripts.onboard_tables.extract_oracle_comments.run", lambda **kwargs: 0)
        monkeypatch.setattr("scripts.onboard_tables.build_context_from_catalog.run", lambda **kwargs: 0)

        code = onboarding.run_onboarding(
            schema="TEST_SCHEMA",
            tables=["TEST_TABLE"],
            domain="demo",
            project_root=root,
        )
        assert code == 0
        assert generated_file.exists()
        assert (root / "metadata" / "approvals" / "test_table_review.yml").exists()
    finally:
        _cleanup(root)


def test_onboard_promote_requires_valid_approval(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _seed_workspace(root)
        generated_file = root / "metadata" / "generated" / "test_table.yml"

        monkeypatch.setattr("scripts.onboard_tables.PROJECT_ROOT", root)
        monkeypatch.setattr("scripts.onboard_tables.inspect_oracle_schema.run_inspection", lambda **kwargs: (_write_generated(generated_file) or 0))
        monkeypatch.setattr("scripts.onboard_tables.extract_oracle_comments.run", lambda **kwargs: 0)
        monkeypatch.setattr("scripts.onboard_tables.build_context_from_catalog.run", lambda **kwargs: 0)

        with pytest.raises(ValueError):
            onboarding.run_onboarding(
                schema="TEST_SCHEMA",
                tables=["TEST_TABLE"],
                domain="demo",
                promote=True,
                project_root=root,
            )
    finally:
        _cleanup(root)


def test_onboard_promote_calls_promote_when_approval_valid(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        _seed_workspace(root)
        generated_file = root / "metadata" / "generated" / "test_table.yml"
        calls = {"promote": 0}

        monkeypatch.setattr("scripts.onboard_tables.PROJECT_ROOT", root)
        monkeypatch.setattr("scripts.onboard_tables.inspect_oracle_schema.run_inspection", lambda **kwargs: (_write_generated(generated_file) or 0))
        monkeypatch.setattr("scripts.onboard_tables.extract_oracle_comments.run", lambda **kwargs: 0)
        monkeypatch.setattr("scripts.onboard_tables.build_context_from_catalog.run", lambda **kwargs: 0)
        monkeypatch.setattr("scripts.onboard_tables.promote_oracle_catalog.promote_catalog", lambda **kwargs: calls.__setitem__("promote", calls["promote"] + 1))
        monkeypatch.setattr(
            "scripts.onboard_tables.subprocess.run",
            lambda *args, **kwargs: type("R", (), {"returncode": 0, "stdout": "ok"})(),
        )

        onboarding.run_onboarding(
            schema="TEST_SCHEMA",
            tables=["TEST_TABLE"],
            domain="demo",
            promote=False,
            auto_approve_safe_columns=True,
            project_root=root,
        )
        onboarding.run_onboarding(
            schema="TEST_SCHEMA",
            tables=["TEST_TABLE"],
            domain="demo",
            promote=True,
            auto_approve_safe_columns=True,
            overwrite=True,
            project_root=root,
        )

        assert calls["promote"] == 1
    finally:
        _cleanup(root)


def test_checklist_output_path_blocked_outside_outputs():
    root = _mk_workspace_tmp()
    try:
        with pytest.raises(ValueError):
            onboarding.resolve_checklist_output_path("metadata/no.md", project_root=root)
    finally:
        _cleanup(root)


def test_onboard_writes_checklist_markdown_and_detects_key_and_sensitive(monkeypatch, capsys):
    root = _mk_workspace_tmp()
    try:
        _seed_workspace(root)
        generated_file = root / "metadata" / "generated" / "test_table.yml"
        comments_file = root / "metadata" / "generated" / "oracle_comments.yml"

        def _fake_extract(**kwargs):
            comments_file.write_text(
                yaml.safe_dump(
                    {
                        "tables": {
                            "TEST_SCHEMA.TEST_TABLE": {
                                "columns": {"ESTADO_CLIENTE": {"comment": "Catalogo de estado"}}
                            }
                        }
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            return 0

        monkeypatch.setattr("scripts.onboard_tables.PROJECT_ROOT", root)
        monkeypatch.setattr("scripts.onboard_tables.inspect_oracle_schema.run_inspection", lambda **kwargs: (_write_generated(generated_file) or 0))
        monkeypatch.setattr("scripts.onboard_tables.extract_oracle_comments.run", _fake_extract)
        monkeypatch.setattr("scripts.onboard_tables.build_context_from_catalog.run", lambda **kwargs: 0)

        code = onboarding.run_onboarding(
            schema="TEST_SCHEMA",
            tables=["TEST_TABLE"],
            domain="demo",
            auto_approve_safe_columns=True,
            checklist_output="outputs/onboarding_checklist_demo.md",
            project_root=root,
        )
        assert code == 0
        output = root / "outputs" / "onboarding_checklist_demo.md"
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "TEST_SCHEMA.TEST_TABLE" in content
        assert "Columnas sensibles detectadas" in content
        assert "TEST_SCHEMA.TEST_TABLE.NOMBRE" in content
        assert "Columnas candidatas a llaves de negocio" in content
        assert "TEST_SCHEMA.TEST_TABLE.CLIENTE_ID" in content
        assert "NO mapping aprobado" in content
        assert "SAC.MUNICIPIOS" not in content

        console = capsys.readouterr().out
        assert "=== CHECKLIST MINIMO ===" in console
    finally:
        _cleanup(root)
