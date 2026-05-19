from pathlib import Path

from app.core.config import Settings


def test_settings_resolve_metadata_path_from_backend_relative_value():
    project_root = Path(__file__).resolve().parents[1]
    settings = Settings(metadata_path=Path("backend/metadata"), audit_log_path=Path("backend/logs/audit.log"))
    assert settings.metadata_path == (project_root / "metadata").resolve()
    assert settings.audit_log_path == (project_root / "logs" / "audit.log").resolve()
