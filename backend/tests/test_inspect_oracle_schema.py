from pathlib import Path
import shutil
import uuid

import pytest

from scripts.inspect_oracle_schema import (
    build_table_diagnostics,
    build_catalog_proposal,
    build_parser,
    parse_table_names,
    resolve_output_path,
    validate_schema_name,
    write_yaml,
)


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def test_validate_schema_name():
    assert validate_schema_name("test_schema") == "TEST_SCHEMA"
    with pytest.raises(ValueError):
        validate_schema_name("BAD-SCHEMA")


def test_parse_tables_validation():
    assert parse_table_names("TEST_TABLE,RELATED_TABLE") == [
        "TEST_TABLE",
        "RELATED_TABLE",
    ]
    with pytest.raises(ValueError):
        parse_table_names("TEST_SCHEMA.TEST_TABLE")


def test_introspection_requires_mandatory_parameters():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_output_must_stay_inside_generated():
    project_root = _mk_workspace_tmp()
    try:
        (project_root / "metadata" / "generated").mkdir(parents=True, exist_ok=True)

        with pytest.raises(ValueError):
            resolve_output_path("metadata/outside.yml", project_root=project_root)
    finally:
        _cleanup(project_root)


def test_no_overwrite_without_flag():
    project_root = _mk_workspace_tmp()
    try:
        target = project_root / "metadata" / "generated" / "oracle_catalog_proposal.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("existing", encoding="utf-8")

        with pytest.raises(FileExistsError):
            resolve_output_path(str(target.resolve()), project_root=project_root, overwrite=False)
    finally:
        _cleanup(project_root)


def test_yaml_generation_with_mocked_metadata():
    project_root = _mk_workspace_tmp()
    try:
        metadata = {
            "objects": [("TEST_SCHEMA", "TEST_TABLE", "TABLE")],
            "columns": [
                (
                    "TEST_SCHEMA",
                    "TEST_TABLE",
                    "ID",
                    "NUMBER",
                    "N",
                    22,
                    10,
                    0,
                )
            ],
            "primary_keys": [("TEST_SCHEMA", "TEST_TABLE", "PK_TEST", "ID", 1)],
            "foreign_keys": [],
        }
        payload = build_catalog_proposal(
            schema="TEST_SCHEMA",
            tables=["TEST_TABLE"],
            metadata=metadata,
        )

        output = project_root / "metadata" / "generated" / "oracle_catalog_proposal.yml"
        write_yaml(output, payload)

        text = output.read_text(encoding="utf-8")
        assert "TEST_SCHEMA.TEST_TABLE" in text
        assert "ID" in text
        assert "primary_keys" in text
    finally:
        _cleanup(project_root)


def test_table_diagnostics_reports_visibility_states():
    metadata = {
        "objects": [
            ("TEST_SCHEMA", "VISIBLE_TABLE", "TABLE"),
            ("TEST_SCHEMA", "ONLY_SYN", "SYNONYM"),
        ],
        "columns": [
            ("TEST_SCHEMA", "VISIBLE_TABLE", "ID", "NUMBER", "N", 22, 10, 0),
        ],
        "primary_keys": [],
        "foreign_keys": [],
    }

    diagnostics = build_table_diagnostics(
        schema="TEST_SCHEMA",
        requested_tables=["VISIBLE_TABLE", "ONLY_SYN", "MISSING_TBL"],
        metadata=metadata,
    )
    by_name = {item["full_name"]: item for item in diagnostics}

    assert by_name["TEST_SCHEMA.VISIBLE_TABLE"]["status"] == "INTROSPECTABLE"
    assert by_name["TEST_SCHEMA.ONLY_SYN"]["status"] == "VISIBLE_WITHOUT_COLUMNS"
    assert by_name["TEST_SCHEMA.MISSING_TBL"]["status"] == "NOT_VISIBLE"
