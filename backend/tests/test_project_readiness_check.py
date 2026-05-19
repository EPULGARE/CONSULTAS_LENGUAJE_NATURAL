from pathlib import Path
import shutil
import uuid

from scripts.project_readiness_check import evaluate_project_readiness, resolve_output_path


class FakeSettings:
    def __init__(self):
        self.db_dialect = "oracle"
        self.db_host = "localhost"
        self.db_port = 1521
        self.db_service_name = "ORCL"
        self.db_sid = ""
        self.db_user = "real_user"
        self.db_password = "real_password"
        self.catalog_require_approval = True
        self.query_dry_run_default = True
        self.query_allow_execution = False


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _seed_project(root: Path) -> None:
    (root / ".env").write_text("DB_DIALECT=oracle\n", encoding="utf-8")
    (root / "metadata" / "generated").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "approvals").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "evaluation").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "evaluation" / "questions.yml").write_text("questions: []\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in [
        "check_oracle_connection.py",
        "inspect_oracle_schema.py",
        "review_oracle_catalog.py",
        "promote_oracle_catalog.py",
        "oracle_catalog_smoke_test.py",
        "evaluate_text_to_sql.py",
        "bootstrap_real_catalog.py",
    ]:
        (scripts / name).write_text("# ok\n", encoding="utf-8")


def test_readiness_passes_with_valid_mock_config():
    root = _mk_workspace_tmp()
    try:
        _seed_project(root)
        report = evaluate_project_readiness(project_root=root, settings=FakeSettings())
        assert report.ok is True
        assert report.summary["error"] == 0
    finally:
        _cleanup(root)


def test_fails_if_env_missing():
    root = _mk_workspace_tmp()
    try:
        (root / "metadata" / "generated").mkdir(parents=True, exist_ok=True)
        (root / "metadata" / "approvals").mkdir(parents=True, exist_ok=True)
        (root / "metadata" / "evaluation").mkdir(parents=True, exist_ok=True)
        (root / "metadata" / "evaluation" / "questions.yml").write_text("questions: []\n", encoding="utf-8")
        scripts = root / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        for name in [
            "check_oracle_connection.py",
            "inspect_oracle_schema.py",
            "review_oracle_catalog.py",
            "promote_oracle_catalog.py",
            "oracle_catalog_smoke_test.py",
            "evaluate_text_to_sql.py",
            "bootstrap_real_catalog.py",
        ]:
            (scripts / name).write_text("# ok\n", encoding="utf-8")
        report = evaluate_project_readiness(project_root=root, settings=FakeSettings())
        assert report.ok is False
        assert any(i.name == ".env exists" and i.status == "ERROR" for i in report.items)
    finally:
        _cleanup(root)


def test_fails_if_db_user_placeholder():
    root = _mk_workspace_tmp()
    try:
        _seed_project(root)
        settings = FakeSettings()
        settings.db_user = "readonly_user"
        report = evaluate_project_readiness(project_root=root, settings=settings)
        assert report.ok is False
        assert any(i.name == "DB_USER valid" and i.status == "ERROR" for i in report.items)
    finally:
        _cleanup(root)


def test_fails_if_db_password_placeholder():
    root = _mk_workspace_tmp()
    try:
        _seed_project(root)
        settings = FakeSettings()
        settings.db_password = "change_me"
        report = evaluate_project_readiness(project_root=root, settings=settings)
        assert report.ok is False
        assert any(i.name == "DB_PASSWORD valid" and i.status == "ERROR" for i in report.items)
    finally:
        _cleanup(root)


def test_warning_if_query_allow_execution_true():
    root = _mk_workspace_tmp()
    try:
        _seed_project(root)
        settings = FakeSettings()
        settings.query_allow_execution = True
        report = evaluate_project_readiness(project_root=root, settings=settings)
        item = next(i for i in report.items if i.name == "QUERY_ALLOW_EXECUTION=false")
        assert item.status == "WARNING"
    finally:
        _cleanup(root)


def test_blocks_json_output_outside_outputs():
    try:
        resolve_output_path("metadata/readiness.json")
        assert False, "Expected ValueError"
    except ValueError:
        assert True


def test_import_promote_script_no_global_settings_side_effect():
    import importlib

    module = importlib.import_module("scripts.promote_oracle_catalog")
    assert hasattr(module, "promote_catalog")
    assert not hasattr(module, "settings")
