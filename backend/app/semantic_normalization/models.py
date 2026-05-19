from __future__ import annotations

from pydantic import BaseModel, Field

from app.semantic_catalog.models import ResolvedLookupValue


class BusinessTermRule(BaseModel):
    canonical_term: str
    applies_to_domains: list[str] = Field(default_factory=list)
    source_table: str = ""
    source_column: str = ""
    canonical_value: str = ""
    synonyms: list[str] = Field(default_factory=list)
    entity_terms: list[str] = Field(default_factory=list)
    operational_verbs: list[str] = Field(default_factory=list)


class NumericEntityDescriptionLookup(BaseModel):
    enabled: bool = False
    use_approved_parametric_mapping_only: bool = True
    source_column: str = ""
    preferred_description_column: str = ""
    required_fixed_filter: str = ""


class NumericEntityBehavior(BaseModel):
    filter_by_code_when_user_provides_code: bool = True
    show_description_when_user_asks_description: bool = False
    default_select_code_and_description_if_grouping_by_entity: bool = False


class ExplicitNumericColumnRule(BaseModel):
    source_column: str
    code_type: str = "string"
    terms: list[str] = Field(default_factory=list)


class NumericEntityMapping(BaseModel):
    entity: str
    source_table: str
    default_code_column: str
    code_type: str = "string"
    business_terms: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    forbidden_columns_for_entity_code: list[str] = Field(default_factory=list)
    explicit_column_terms: list[ExplicitNumericColumnRule] = Field(default_factory=list)
    description_lookup: NumericEntityDescriptionLookup = Field(default_factory=NumericEntityDescriptionLookup)
    behavior: NumericEntityBehavior = Field(default_factory=NumericEntityBehavior)


class ResolvedNumericFilter(BaseModel):
    source_table: str
    source_column: str
    operator: str
    value: str
    value_type: str
    entity: str
    matched_text: str
    confidence: float = 1.0
    description_lookup_available: bool = False
    lookup_table: str = ""
    lookup_description: str = ""
    fixed_filter_value: str = ""
    forbidden_columns: list[str] = Field(default_factory=list)

    @property
    def sql_literal(self) -> str:
        if self.value_type.lower() == "number":
            return str(self.value)
        return f"'{self.value}'"

    @property
    def sql_predicate(self) -> str:
        return f"{self.source_table}.{self.source_column} {self.operator} {self.sql_literal}"

    @property
    def as_text(self) -> str:
        return self.sql_predicate


class SemanticNormalizationResult(BaseModel):
    original_question: str
    normalized_question: str
    detected_domain: str | None = None
    domain_confidence: float = 0.0
    normalized_terms: list[str] = Field(default_factory=list)
    applied_governed_rules: list[str] = Field(default_factory=list)
    skipped_normalizations: list[str] = Field(default_factory=list)
    resolved_entities: list[str] = Field(default_factory=list)
    resolved_filters: list[str] = Field(default_factory=list)
    resolved_lookup_values: list[ResolvedLookupValue] = Field(default_factory=list)
    resolved_numeric_filters: list[ResolvedNumericFilter] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
