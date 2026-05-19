from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from app.query_patterns.models import DetectedQueryPattern


class ColumnMetadata(BaseModel):
    name: str
    type: str = "text"
    description: str = ""
    sensitive: bool = False
    allowed_for_select: bool = True


class TableMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(alias="schema")
    name: str
    description: str = ""
    domain: str
    synonyms: list[str] = Field(default_factory=list)
    allowed_for_query: bool = True
    sensitive_columns: list[str] = Field(default_factory=list)
    default_filters: list[str] = Field(default_factory=list)
    example_questions: list[str] = Field(default_factory=list)
    columns: list[ColumnMetadata] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.name}"


class RelationshipMetadata(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    description: str = ""
    fixed_filter: str = ""

    @property
    def as_text(self) -> str:
        base = (
            f"{self.left_table}.{self.left_column} = "
            f"{self.right_table}.{self.right_column} ({self.description})"
        )
        if self.fixed_filter:
            return f"{base} | fixed_filter: {self.fixed_filter}"
        return base


class ParametricMapping(BaseModel):
    source_table: str
    source_column: str
    lookup_table: str
    lookup_key: str
    lookup_description: str
    fixed_filter: str = ""

    @property
    def as_text(self) -> str:
        text = (
            f"{self.source_table}.{self.source_column} -> "
            f"{self.lookup_table}.{self.lookup_key} => {self.lookup_table}.{self.lookup_description}"
        )
        if self.fixed_filter:
            return f"{text} | fixed_filter: {self.fixed_filter}"
        return text


class LookupCanonicalValue(BaseModel):
    synonyms: list[str] = Field(default_factory=list)


class LookupValueNormalization(BaseModel):
    source_table: str
    source_column: str
    fixed_filter_value: str = ""
    canonical_values: dict[str, LookupCanonicalValue] = Field(default_factory=dict)


class ApprovedLookupValueItem(BaseModel):
    code: str
    description: str
    normalized_description: str
    synonyms: list[str] = Field(default_factory=list)


class ApprovedLookupValuesEntry(BaseModel):
    source_table: str
    source_column: str
    lookup_table: str
    lookup_key: str
    lookup_description: str
    fixed_filter_value: str = ""
    values: list[ApprovedLookupValueItem] = Field(default_factory=list)


class ResolvedLookupValue(BaseModel):
    source_table: str
    source_column: str
    lookup_table: str
    lookup_description: str
    fixed_filter_value: str = ""
    canonical_value: str
    matched_synonym: str
    code: str = ""
    resolution_source: str = ""
    valid_values: list[str] = Field(default_factory=list)

    @property
    def as_text(self) -> str:
        fixed = f" | fixed_filter_value: {self.fixed_filter_value}" if self.fixed_filter_value else ""
        code = f" | code: '{self.code}'" if self.code else ""
        source = f" | resolution_source: {self.resolution_source}" if self.resolution_source else ""
        return (
            f"{self.source_table}.{self.source_column} -> "
            f"{self.lookup_table}.{self.lookup_description} = '{self.canonical_value}'"
            f"{fixed}{code} | matched_synonym: {self.matched_synonym}{source}"
        )


class StaticMappingValue(BaseModel):
    label: str
    synonyms: list[str] = Field(default_factory=list)


class StaticValueMapping(BaseModel):
    table: str
    column: str
    values: dict[str, StaticMappingValue] = Field(default_factory=dict)

    @property
    def as_text(self) -> str:
        chunks: list[str] = []
        for code, value in self.values.items():
            syn = ", ".join(value.synonyms) if value.synonyms else ""
            if syn:
                chunks.append(f"{code} => {value.label} | synonyms: {syn}")
            else:
                chunks.append(f"{code} => {value.label}")
        rendered = "; ".join(chunks) if chunks else "sin valores"
        return f"{self.table}.{self.column}: {rendered}"


class DomainCatalog(BaseModel):
    name: str
    description: str
    keywords: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    domain: str
    tables: list[TableMetadata]
    relationships: list[RelationshipMetadata]
    examples: list[str] = Field(default_factory=list)
    disallowed_columns: set[str] = Field(default_factory=set)
    parametric_mappings: list[ParametricMapping] = Field(default_factory=list)
    static_value_mappings: list[StaticValueMapping] = Field(default_factory=list)
    resolved_lookup_values: list[ResolvedLookupValue] = Field(default_factory=list)
    resolved_numeric_filters: list[object] = Field(default_factory=list)
    intent_guardrails: list[str] = Field(default_factory=list)
    auxiliary_semantic_context: list[str] = Field(default_factory=list)
    detected_query_pattern: DetectedQueryPattern | None = None

    @property
    def relationships_text(self) -> list[str]:
        return [r.as_text for r in self.relationships]
