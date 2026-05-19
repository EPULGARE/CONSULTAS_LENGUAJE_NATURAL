from __future__ import annotations

from pydantic import BaseModel, Field

from app.semantic_catalog.models import ResolvedLookupValue
from app.semantic_normalization.models import ResolvedNumericFilter


class EnhancedIntentResult(BaseModel):
    original_question: str
    enhanced_question: str
    ambiguity_detected: bool
    normalized_terms: list[str] = Field(default_factory=list)
    applied_governed_rules: list[str] = Field(default_factory=list)
    skipped_normalizations: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    detected_entities: list[str] = Field(default_factory=list)
    detected_filters: list[str] = Field(default_factory=list)
    resolved_entities: list[str] = Field(default_factory=list)
    resolved_filters: list[str] = Field(default_factory=list)
    resolved_lookup_values: list[ResolvedLookupValue] = Field(default_factory=list)
    resolved_numeric_filters: list[ResolvedNumericFilter] = Field(default_factory=list)
    intent_guardrails: list[str] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    confidence: float
    requires_user_confirmation: bool


class ClarificationResolutionRequest(BaseModel):
    original_question: str
    enhanced_question: str
    clarification_answer: str
    previous_intent_result: EnhancedIntentResult | None = None
