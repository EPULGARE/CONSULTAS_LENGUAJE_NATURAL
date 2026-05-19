from pathlib import Path
import shutil
import uuid

import pytest
import yaml

from scripts.bootstrap_real_catalog import build_parser, run_bootstrap, validate_non_placeholder


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def test_fails_without_schema():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--tables",
            "TABLA1",
            "--domain",
            "dominio",
            "--generated-output",
            "metadata/generated/x.yml",
            "--approval-output",
            "metadata/approvals/x.yml",
        ])


def test_fails_without_tables():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--schema",
            "SCHEMA1",
            "--domain",
            "dominio",
            "--generated-output",
            "metadata/generated/x.yml",
            "--approval-output",
            "metadata/approvals/x.yml",
        ])


def test_fails_without_domain():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--schema",
            "SCHEMA1",
            "--tables",
            "TABLA1",
            "--generated-output",
            "metadata/generated/x.yml",
            "--approval-output",
            "metadata/approvals/x.yml",
        ])


def test_blocks_generated_output_outside(monkeypatch):
    with pytest.raises(ValueError, match="metadata/generated"):
        run_bootstrap(
            schema="SCHEMA1",
            tables_raw="TABLA1",
            domain="dominio",
            generated_output="metadata/outside.yml",
            approval_output="metadata/approvals/review.yml",
            dry_run=True,
            overwrite=False,
        )


def test_blocks_approval_output_outside(monkeypatch):
    with pytest.raises(ValueError, match="metadata/approvals"):
        run_bootstrap(
            schema="SCHEMA1",
            tables_raw="TABLA1",
            domain="dominio",
            generated_output="metadata/generated/proposal.yml",
            approval_output="metadata/review.yml",
            dry_run=True,
            overwrite=False,
        )


def test_no_promotion_automatic_and_no_auto_approval(monkeypatch):
    root = _mk_workspace_tmp()
    try:
        generated = root / "metadata" / "generated" / "proposal.yml"
        approval = root / "metadata" / "approvals" / "review.yml"
        generated.parent.mkdir(parents=True, exist_ok=True)
        approval.parent.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("scripts.bootstrap_real_catalog.resolve_output_path", lambda *args, **kwargs: generated)
        monkeypatch.setattr("scripts.bootstrap_real_catalog.resolve_approval_output", lambda *args, **kwargs: approval)

        def fake_inspection(*args, **kwargs):
            payload = {
                "tables": [
                    {
                        "full_name": "SCHEMA1.TABLA1",
                        "columns": [{"name": "ID"}],
                        "foreign_keys": [],
                    }
                ]
            }
            generated.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            return 0

        monkeypatch.setattr("scripts.bootstrap_real_catalog.run_inspection", fake_inspection)

        result = run_bootstrap(
            schema="SCHEMA1",
            tables_raw="TABLA1",
            domain="dominio",
            generated_output="metadata/generated/proposal.yml",
            approval_output="metadata/approvals/review.yml",
            dry_run=False,
            overwrite=True,
        )
        assert result == 0
        assert (root / "metadata" / "tables.yml").exists() is False

        approval_data = yaml.safe_load(approval.read_text(encoding="utf-8"))
        assert approval_data["tables"][0]["approved"] is False
    finally:
        _cleanup(root)


def test_generates_next_steps_instructions(monkeypatch, capsys):
    result = run_bootstrap(
        schema="SCHEMA1",
        tables_raw="TABLA1",
        domain="dominio",
        generated_output="metadata/generated/proposal.yml",
        approval_output="metadata/approvals/review.yml",
        dry_run=True,
        overwrite=False,
    )
    out = capsys.readouterr().out
    assert result == 0
    assert "Proximos pasos manuales" in out
    assert "promote_oracle_catalog.py" in out


def test_rejects_placeholders():
    with pytest.raises(ValueError, match="no acepta placeholders"):
        validate_non_placeholder("<ESQUEMA_REAL>", "--schema")
