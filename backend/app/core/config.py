from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.sql.dialects import SQLDialect


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "Text2SQL Secure Backend"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    project_root: Path = Path(__file__).resolve().parents[2]
    metadata_path: Path = project_root / "metadata"
    audit_log_path: Path = project_root / "logs" / "audit.log"

    openrouter_api_key: str = ""
    openrouter_model_classifier: str = "openai/gpt-4o-mini"
    openrouter_model_sql: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = 30
    openrouter_proxy_enabled: bool = False
    openrouter_proxy_host: str = ""
    openrouter_proxy_port: int = 8080
    openrouter_proxy_user: str = ""
    openrouter_proxy_password: str = ""
    openrouter_ca_cert_path: str = ""
    openrouter_insecure: bool = False

    db_dialect: SQLDialect = SQLDialect.ORACLE
    db_host: str = "localhost"
    db_port: int = 1521
    db_service_name: str = "ORCLPDB1"
    db_sid: str = ""
    db_user: str = "readonly_user"
    db_password: str = "change_me"
    db_timeout_seconds: int = 30
    # Zero disables the automatic row limit; explicit query limits still apply.
    db_max_rows: int = Field(default=0, ge=0, le=10000)
    db_read_only: bool = True

    db_url: str = f"sqlite:///{(project_root / 'data' / 'local.db').as_posix()}"

    sql_allow_union: bool = False
    sql_allow_select_without_from: bool = False
    sql_allow_sensitive_columns: bool = False
    catalog_require_approval: bool = True
    query_dry_run_default: bool = True
    query_allow_execution: bool = False
    query_include_llm_prompt_in_debug: bool = False
    enable_intent_enhancer: bool = True
    intent_enhancer_auto_accept_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    intent_enhancer_model: str = ""
    conversation_state_enabled: bool = True
    conversation_state_ttl_minutes: int = Field(default=30, ge=1, le=1440)
    max_pending_clarifications: int = Field(default=5, ge=1, le=20)
    conversation_storage_backend: str = "memory"
    conversation_sqlite_path: Path = project_root / "data" / "conversation_state.sqlite3"
    conversation_cleanup_interval_minutes: int = Field(default=5, ge=1, le=1440)
    max_tables_in_sql_context: int = Field(default=5, ge=1, le=20)
    max_columns_per_table_in_sql_context: int = Field(default=25, ge=1, le=200)
    use_llm_context_selector: bool = True
    use_llm_table_selector: bool = True
    enable_llm_table_selection_fallback: bool = True
    table_selector_min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    table_selector_timeout_seconds: int = Field(default=30, ge=5, le=120)
    local_table_selection_confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)

    def model_post_init(self, __context: object) -> None:
        if not self.intent_enhancer_model.strip():
            self.intent_enhancer_model = self.openrouter_model_classifier
        self.metadata_path = self._resolve_project_path(self.metadata_path)
        self.audit_log_path = self._resolve_project_path(self.audit_log_path)
        self.conversation_sqlite_path = self._resolve_project_path(self.conversation_sqlite_path)
        if self.openrouter_ca_cert_path.strip():
            self.openrouter_ca_cert_path = str(self._resolve_project_path(Path(self.openrouter_ca_cert_path)))

    def _resolve_project_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        parts = list(path.parts)
        if parts and parts[0].lower() == "backend":
            path = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        return (self.project_root / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    loaded = Settings()
    loaded.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    if loaded.db_url.startswith("sqlite:///"):
        sqlite_path = Path(loaded.db_url.replace("sqlite:///", "", 1))
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    loaded.conversation_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return loaded


settings = get_settings()
