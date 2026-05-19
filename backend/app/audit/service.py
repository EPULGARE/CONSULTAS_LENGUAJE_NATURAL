from __future__ import annotations

import json
from datetime import datetime, timezone

from app.audit.models import QueryAuditEntry
from app.core.config import settings


class AuditService:
    def __init__(self, path=None) -> None:
        self.path = path or settings.audit_log_path

    def log(self, entry: QueryAuditEntry) -> None:
        serializable = entry.model_dump()
        serializable["created_at"] = entry.created_at.isoformat()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(serializable, ensure_ascii=False) + "\n")

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
