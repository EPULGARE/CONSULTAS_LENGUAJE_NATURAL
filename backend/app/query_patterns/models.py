from __future__ import annotations

from pydantic import BaseModel


class DetectedQueryPattern(BaseModel):
    type: str
    entity: str = ""
    related_entity: str = ""
    operator: str = ""
    threshold: int | None = None
    top_n: int | None = None
    sql_skeleton: str = ""

