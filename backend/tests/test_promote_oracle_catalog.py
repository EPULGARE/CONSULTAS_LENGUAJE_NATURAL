from pathlib import Path
import shutil
import uuid

import pytest
import yaml

from scripts.promote_oracle_catalog import build_parser, promote_catalog, resolve_generated_input


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _seed_metadata(root: Path) -> None:
    metadata = root / "metadata"
    (metadata / "generated").mkdir(parents=True, exist_ok=True)
    (metadata / "approvals").mkdir(parents=True, exist_ok=True)
    (metadata / "tables.yml").write_text("tables: []\n", encoding="utf-8")
    (metadata / "relationships.yml").write_text("relationships: []\n", encoding="utf-8")
    (metadata / "domains.yml").write_text("domains: []\n", encoding="utf-8")
    (metadata / "business_terms.yml").write_text("business_terms: []\n", encoding="utf-8")


def _write_generated(root: Path) -> Path:
    generated_file = root / "metadata" / "generated" / "oracle_generated.yml"
    payload = {
        "tables": [
            {
                "full_name": "TEST_SCHEMA.TEST_TABLE",
                "description": "",
                "columns": [
                    {"name": "ID", "data_type": "NUMBER", "business_description": ""},
                    {"name": "SECRET", "data_type": "VARCHAR2", "business_description": ""},
                ],
                "foreign_keys": [
                    {
                        "references_table": "TEST_SCHEMA.RELATED_TABLE",
                        "column_mappings": [{"source_column": "ID", "target_column": "ID"}],
                    }
                ],
            }
        ]
    }
    generated_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return generated_file


def _write_approval(root: Path, generated_path: Path, approved: bool = True, source_override: str | None = None) -> Path:
    approval_file = root / "metadata" / "approvals" / "oracle_review.yml"
    payload = {
        "source_file": source_override or str(generated_path),
        "generated_at": "2026-05-12T00:00:00Z",
        "reviewer": "qa",
        "status": "pending",
        "tables": [
            {
                "full_name": "TEST_SCHEMA.TEST_TABLE",
                "approved": approved,
                "allowed_for_query": approved,
                "domain": "domain_test",
                "business_description": "",
                "columns": [
                    {"name": "ID", "approved": approved, "business_description": "", "sensitive": False, "allowed_for_select": True},
                    {"name": "SECRET", "approved": False, "business_description": "", "sensitive": True, "allowed_for_select": False},
                ],
                "relationships": [
                    {
                        "approved": approved,
                        "references_table": "TEST_SCHEMA.RELATED_TABLE",
                        "column_mappings": [{"source_column": "ID", "target_column": "ID"}],
                    }
                ],
            }
        ],
    }
    approval_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return approval_file


def test_promote_dry_run_does_not_write():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        generated = _write_generated(root)

        result = promote_catalog(
            input_path=generated,
            domain="domain_test",
            promote_tables=True,
            promote_relationships=True,
            dry_run=True,
            overwrite=False,
            project_root=root,
        )
        assert result["dry_run"] is True
        assert result["added_tables"] == 1

        tables_data = yaml.safe_load((root / "metadata" / "tables.yml").read_text(encoding="utf-8"))
        assert tables_data["tables"] == []
    finally:
        _cleanup(root)


def test_promote_require_approval_without_approval_fails():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        generated = _write_generated(root)
        with pytest.raises(ValueError):
            promote_catalog(
                input_path=generated,
                domain="domain_test",
                promote_tables=True,
                promote_relationships=True,
                dry_run=False,
                overwrite=True,
                require_approval=True,
                project_root=root,
            )
    finally:
        _cleanup(root)


def test_promote_with_approval_only_approved():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        generated = _write_generated(root)
        approval = _write_approval(root, generated, approved=True)

        promote_catalog(
            input_path=generated,
            domain="domain_test",
            promote_tables=True,
            promote_relationships=True,
            dry_run=False,
            overwrite=True,
            approval_path=approval,
            require_approval=True,
            project_root=root,
        )

        tables_data = yaml.safe_load((root / "metadata" / "tables.yml").read_text(encoding="utf-8"))
        assert len(tables_data["tables"]) == 1
        col_names = [c["name"] for c in tables_data["tables"][0]["columns"]]
        assert col_names == ["ID"]

        rel_data = yaml.safe_load((root / "metadata" / "relationships.yml").read_text(encoding="utf-8"))
        assert len(rel_data["relationships"]) == 1
    finally:
        _cleanup(root)


def test_promote_fails_when_approval_table_not_in_generated():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        generated = _write_generated(root)
        approval = root / "metadata" / "approvals" / "oracle_review.yml"
        payload = {
            "source_file": str(generated),
            "generated_at": "x",
            "reviewer": "qa",
            "status": "pending",
            "tables": [{"full_name": "TEST_SCHEMA.UNKNOWN", "approved": True, "allowed_for_query": True, "columns": [], "relationships": []}],
        }
        approval.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        with pytest.raises(ValueError):
            promote_catalog(
                input_path=generated,
                domain="domain_test",
                promote_tables=True,
                promote_relationships=False,
                dry_run=False,
                overwrite=True,
                approval_path=approval,
                require_approval=True,
                project_root=root,
            )
    finally:
        _cleanup(root)


def test_promote_fails_when_source_file_mismatch():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        generated = _write_generated(root)
        approval = _write_approval(root, generated, approved=True, source_override="metadata/generated/other.yml")

        with pytest.raises(ValueError):
            promote_catalog(
                input_path=generated,
                domain="domain_test",
                promote_tables=True,
                promote_relationships=False,
                dry_run=False,
                overwrite=True,
                approval_path=approval,
                require_approval=True,
                project_root=root,
            )
    finally:
        _cleanup(root)


def test_block_input_outside_generated():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        outside = root / "metadata" / "outside.yml"
        outside.write_text("tables: []\n", encoding="utf-8")

        with pytest.raises(ValueError):
            resolve_generated_input(str(outside), project_root=root)
    finally:
        _cleanup(root)


def test_block_promotion_without_domain_parse_level():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--input", "metadata/generated/x.yml", "--promote-tables"])
