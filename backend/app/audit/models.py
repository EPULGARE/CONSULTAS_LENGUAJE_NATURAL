from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class QueryAuditEntry(BaseModel):
    user_id: str
    question: str
    normalized_question: str
    domain: str | None = None
    generated_sql: str | None = None
    validated_sql: str | None = None
    success: bool
    error: str | None = None
    result_count: int = 0
    created_at: datetime
    extra: dict[str, Any] = {}
