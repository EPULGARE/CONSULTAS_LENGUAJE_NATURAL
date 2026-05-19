from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.semantic_catalog.models import ResolvedLookupValue
from app.semantic_normalization.models import ResolvedNumericFilter

if TYPE_CHECKING:
    from app.intent_enhancer.models import EnhancedIntentResult


class ClarificationAnswerRecord(BaseModel):
    question: str
    answer: str
    resolved_as: str | None = None
    answered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationState(BaseModel):
    conversation_id: str
    user_id: str | None = None
    original_question: str
    enhanced_question: str
    detected_domain: str | None = None
    normalized_terms: list[str] = Field(default_factory=list)
    applied_governed_rules: list[str] = Field(default_factory=list)
    skipped_normalizations: list[str] = Field(default_factory=list)
    resolved_entities: list[str] = Field(default_factory=list)
    resolved_filters: list[str] = Field(default_factory=list)
    resolved_lookup_values: list[ResolvedLookupValue] = Field(default_factory=list)
    resolved_numeric_filters: list[ResolvedNumericFilter] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_answers: list[ClarificationAnswerRecord] = Field(default_factory=list)
    detected_query_pattern: str | None = None
    selected_tables: list[str] = Field(default_factory=list)
    approved_join_paths: list[str] = Field(default_factory=list)
    intent_guardrails: list[str] = Field(default_factory=list)
    sql_generation_ready: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_intent_result(self) -> EnhancedIntentResult:
        from app.intent_enhancer.models import EnhancedIntentResult

        return EnhancedIntentResult(
            original_question=self.original_question,
            enhanced_question=self.enhanced_question,
            ambiguity_detected=bool(self.clarification_questions),
            normalized_terms=list(self.normalized_terms),
            applied_governed_rules=list(self.applied_governed_rules),
            skipped_normalizations=list(self.skipped_normalizations),
            clarification_questions=list(self.clarification_questions),
            detected_entities=list(self.resolved_entities),
            detected_filters=list(self.resolved_filters),
            resolved_entities=list(self.resolved_entities),
            resolved_filters=list(self.resolved_filters),
            resolved_lookup_values=list(self.resolved_lookup_values),
            resolved_numeric_filters=list(self.resolved_numeric_filters),
            intent_guardrails=list(self.intent_guardrails),
            unresolved_ambiguities=list(self.unresolved_ambiguities),
            confidence=1.0 if self.sql_generation_ready else 0.5,
            requires_user_confirmation=not self.sql_generation_ready,
        )


class ClarificationResolution(BaseModel):
    matched_pending_state: bool = False
    resolved: bool = False
    conversation_state: ConversationState | None = None
    resumed_intent_result: object | None = None
    clarification_answer: str | None = None
