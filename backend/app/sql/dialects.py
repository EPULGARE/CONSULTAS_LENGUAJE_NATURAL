from __future__ import annotations

import re
from enum import Enum


class SQLDialect(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgresql"
    MSSQL = "mssql"
    ORACLE = "oracle"


_FETCH_FIRST_RE = re.compile(r"\bFETCH\s+FIRST\s+(\d+)\s+ROW(?:S)?\s+ONLY\b", re.IGNORECASE)
_FETCH_NEXT_RE = re.compile(r"\bFETCH\s+NEXT\s+(\d+)\s+ROW(?:S)?\s+ONLY\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)


def ensure_row_limit(sql: str, *, dialect: SQLDialect, max_rows: int) -> tuple[str, bool]:
    stripped = sql.strip()
    if dialect == SQLDialect.ORACLE:
        fetch_first_match = _FETCH_FIRST_RE.search(stripped)
        if fetch_first_match:
            count = int(fetch_first_match.group(1))
            normalized = _FETCH_FIRST_RE.sub(
                f"FETCH FIRST {count} {'ROW' if count == 1 else 'ROWS'} ONLY",
                stripped,
                count=1,
            )
            return normalized, False
        fetch_next_match = _FETCH_NEXT_RE.search(stripped)
        if fetch_next_match:
            count = int(fetch_next_match.group(1))
            normalized = _FETCH_NEXT_RE.sub(
                f"FETCH FIRST {count} {'ROW' if count == 1 else 'ROWS'} ONLY",
                stripped,
                count=1,
            )
            return normalized, False
        if max_rows == 0:
            return stripped, False
        return f"{stripped} FETCH FIRST {max_rows} ROWS ONLY", True

    if _LIMIT_RE.search(stripped):
        return stripped, False
    if max_rows == 0:
        return stripped, False
    return f"{stripped} LIMIT {max_rows}", True
