from __future__ import annotations

from pydantic import BaseModel, Field


class DirectoryEntry(BaseModel):
    table: str
    domain: str
    short_description: str = ""
    keywords: list[str] = Field(default_factory=list)
    business_terms: list[str] = Field(default_factory=list)
    allowed_for_query: bool = True
    context_path: str = ""
    has_detailed_context_path: str = ""


class TableContextColumn(BaseModel):
    name: str
    type: str = "text"
    business_description: str = ""
    selectable: bool = True
    sensitive: bool = False
    synonyms: list[str] = Field(default_factory=list)
    comments_auxiliary: str = ""


class TableContext(BaseModel):
    table: str
    domain: str
    business_description: str = ""
    display_column: str = ""
    columns: list[TableContextColumn] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    approved_parametric_mappings: list[dict] = Field(default_factory=list)


class SelectedTableContext(BaseModel):
    table: str
    selected_columns: list[str] = Field(default_factory=list)


class TableSelectionDiagnostics(BaseModel):
    strategy: str = "LOCAL_PLUS_LLM"
    local_selection_confidence: float = 0.0
    local_selection_reason: str = ""
    used_llm_table_selection: bool = False
