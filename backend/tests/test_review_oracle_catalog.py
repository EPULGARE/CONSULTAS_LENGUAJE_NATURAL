from pathlib import Path
import shutil
import uuid

import pytest
import yaml

from scripts.review_oracle_catalog import (
    build_review_payload,
    resolve_approval_output,
    resolve_generated_input,
)


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def test_review_generates_pending_and_no_auto_approval():
    payload = {
        "tables": [
            {
                "full_name": "TEST_SCHEMA.TEST_TABLE",
                "description": "",
                "columns": [{"name": "ID", "business_description": ""}],
                "foreign_keys": [],
            }
        ]
    }
    review = build_review_payload(source_file="metadata/generated/x.yml", generated_payload=payload)
    assert review["status"] == "pending"
    assert review["tables"][0]["approved"] is False
    assert review["tables"][0]["allowed_for_query"] is False
    assert review["tables"][0]["columns"][0]["approved"] is False


def test_review_output_blocked_outside_approvals():
    root = _mk_workspace_tmp()
    try:
        (root / "metadata" / "approvals").mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError):
            resolve_approval_output("metadata/generated/wrong.yml", project_root=root)
    finally:
        _cleanup(root)
