from typing import Any

from pydantic import BaseModel, Field

from app.semantic_catalog.models import ResolvedLookupValue
from app.semantic_normalization.models import ResolvedNumericFilter


class QueryResponse(BaseModel):
    conversation_id: str | None = None
    domain: str | None = None
    sql: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    question: str | None = None
    detected_domain: str | None = None
    retrieved_tables: list[str] = Field(default_factory=list)
    generated_sql: str | None = None
    validated_sql: str | None = None
    validation_status: str | None = None
    warnings: list[str] = Field(default_factory=list)
    execution_skipped: bool = False
    execution_skip_reason: str | None = None
    debug_prompt: str | None = None
    original_question: str | None = None
    enhanced_question: str | None = None
    normalized_terms: list[str] = Field(default_factory=list)
    applied_governed_rules: list[str] = Field(default_factory=list)
    skipped_normalizations: list[str] = Field(default_factory=list)
    ambiguity_detected: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    detected_entities: list[str] = Field(default_factory=list)
    detected_filters: list[str] = Field(default_factory=list)
    resolved_entities: list[str] = Field(default_factory=list)
    resolved_filters: list[str] = Field(default_factory=list)
    resolved_lookup_values: list[ResolvedLookupValue] = Field(default_factory=list)
    resolved_numeric_filters: list[ResolvedNumericFilter] = Field(default_factory=list)
    intent_guardrails: list[str] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    detected_query_pattern: str | None = None
    intent_confidence: float | None = None
    requires_user_confirmation: bool = False
