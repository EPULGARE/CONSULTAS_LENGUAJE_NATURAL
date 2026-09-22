from pathlib import Path
import shutil
import uuid

import yaml

from scripts import build_context_from_catalog as builder


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _seed_metadata(root: Path) -> None:
    metadata = root / "metadata"
    (metadata / "curated").mkdir(parents=True, exist_ok=True)
    (metadata / "generated").mkdir(parents=True, exist_ok=True)
    (metadata / "context" / "tables").mkdir(parents=True, exist_ok=True)
    (metadata / "tables.yml").write_text(
        yaml.safe_dump(
            {
                "tables": [
                    {
                        "schema": "TEST_SCHEMA",
                        "name": "TEST_TABLE",
                        "domain": "demo",
                        "description": "Tabla demo",
                        "allowed_for_query": True,
                        "synonyms": ["demo"],
                        "columns": [
                            {"name": "ID", "type": "NUMBER", "allowed_for_select": True, "sensitive": False},
                            {"name": "SECRET_COL", "type": "VARCHAR2", "allowed_for_select": True, "sensitive": False},
                        ],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (metadata / "relationships.yml").write_text(
        yaml.safe_dump(
            {
                "relationships": [
                    {
                        "left_table": "TEST_SCHEMA.TEST_TABLE",
                        "left_column": "ID",
                        "right_table": "TEST_SCHEMA.OTHER_TABLE",
                        "right_column": "ID",
                        "join_type": "inner",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (metadata / "curated" / "business_overrides.yml").write_text(
        yaml.safe_dump(
            {
                "tables": {
                    "TEST_SCHEMA.TEST_TABLE": {
                        "sensitive_columns": ["SECRET_COL"],
                        "columns": {"SECRET_COL": {"allowed_for_select": False}},
                    }
                },
                "approved_parametric_mappings": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (metadata / "generated" / "oracle_comments.yml").write_text(
        yaml.safe_dump({"tables": {"TEST_SCHEMA.TEST_TABLE": {"columns": {"ID": {"comment": "id"}}}}}, sort_keys=False),
        encoding="utf-8",
    )


def test_build_context_script_generates_directory_and_table_files():
    root = _mk_workspace_tmp()
    try:
        _seed_metadata(root)
        code = builder.run(overwrite=True, project_root=root)
        assert code == 0

        directory = yaml.safe_load((root / "metadata" / "context" / "table_directory.yml").read_text(encoding="utf-8"))
        assert len(directory["tables"]) == 1
        assert directory["tables"][0]["table"] == "TEST_SCHEMA.TEST_TABLE"

        table_context = yaml.safe_load(
            (root / "metadata" / "context" / "tables" / "TEST_SCHEMA.TEST_TABLE.yml").read_text(encoding="utf-8")
        )
        assert table_context["table"] == "TEST_SCHEMA.TEST_TABLE"
        assert table_context["columns"][0]["name"] == "ID"
        secret = next(column for column in table_context["columns"] if column["name"] == "SECRET_COL")
        assert secret["sensitive"] is True
        assert secret["selectable"] is False
        rel_index = yaml.safe_load((root / "metadata" / "context" / "relationship_index.yml").read_text(encoding="utf-8"))
        assert rel_index["relationships"][0]["from_table"] == "TEST_SCHEMA.TEST_TABLE"
        assert rel_index["relationships"][0]["approved"] is True
    finally:
        _cleanup(root)
