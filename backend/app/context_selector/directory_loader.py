from __future__ import annotations

from pathlib import Path

import yaml

from app.context_selector.models import DirectoryEntry, TableContext
from app.core.config import settings


class ContextDirectoryLoader:
    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = self._resolve_metadata_path(metadata_path)
        self.context_root = self.metadata_path / "context"

    @staticmethod
    def _resolve_metadata_path(metadata_path: Path) -> Path:
        if metadata_path.is_absolute():
            return metadata_path
        candidate = metadata_path.resolve()
        if candidate.exists():
            return candidate
        configured = settings.metadata_path
        if configured.exists():
            return configured
        fallback = (settings.project_root / metadata_path).resolve()
        return fallback

    def load_directory(self) -> list[DirectoryEntry]:
        target = self.context_root / "table_directory.yml"
        if not target.exists():
            return []
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        entries = [DirectoryEntry(**item) for item in payload.get("tables", [])]
        for entry in entries:
            if not entry.context_path and entry.has_detailed_context_path:
                entry.context_path = entry.has_detailed_context_path
            if not entry.has_detailed_context_path and entry.context_path:
                entry.has_detailed_context_path = entry.context_path
        return entries

    def load_table_context(self, relative_path: str) -> TableContext | None:
        target = (self.metadata_path.parent / relative_path).resolve() if relative_path.startswith("metadata/") else (self.metadata_path / relative_path).resolve()
        if not target.exists():
            return None
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return TableContext(**payload)
