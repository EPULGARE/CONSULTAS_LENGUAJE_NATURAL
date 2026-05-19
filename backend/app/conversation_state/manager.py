from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from app.conversation_state.models import ClarificationResolution, ConversationState
from app.conversation_state.resolver import looks_like_clarification_answer, resolve_state_clarification
from app.conversation_state.storage_providers.base import ConversationStorageProvider
from app.core.config import settings

if TYPE_CHECKING:
    from app.intent_enhancer import IntentEnhancer
    from app.intent_enhancer.models import EnhancedIntentResult

logger = logging.getLogger(__name__)


class ConversationStateManager:
    def __init__(self, storage: ConversationStorageProvider) -> None:
        self.storage = storage
        self._last_cleanup_at: datetime | None = None

    def create_state(
        self,
        *,
        user_id: str,
        intent_result: EnhancedIntentResult,
        conversation_id: str | None = None,
        detected_domain: str | None = None,
        detected_query_pattern: str | None = None,
        selected_tables: list[str] | None = None,
        approved_join_paths: list[str] | None = None,
    ) -> ConversationState:
        now = datetime.now(timezone.utc)
        state = ConversationState(
            conversation_id=conversation_id or str(uuid4()),
            user_id=user_id,
            original_question=intent_result.original_question,
            enhanced_question=intent_result.enhanced_question,
            detected_domain=detected_domain,
            normalized_terms=list(intent_result.normalized_terms),
            applied_governed_rules=list(intent_result.applied_governed_rules),
            skipped_normalizations=list(intent_result.skipped_normalizations),
            resolved_entities=list(intent_result.resolved_entities),
            resolved_filters=list(intent_result.resolved_filters),
            resolved_lookup_values=list(intent_result.resolved_lookup_values),
            resolved_numeric_filters=list(intent_result.resolved_numeric_filters),
            unresolved_ambiguities=list(intent_result.unresolved_ambiguities),
            clarification_questions=list(intent_result.clarification_questions),
            clarification_answers=[],
            detected_query_pattern=detected_query_pattern,
            selected_tables=list(selected_tables or []),
            approved_join_paths=list(approved_join_paths or []),
            intent_guardrails=list(intent_result.intent_guardrails),
            sql_generation_ready=not intent_result.requires_user_confirmation,
            created_at=now,
            updated_at=now,
        )
        logger.info("clarification detected conversation_id=%s ambiguities=%s", state.conversation_id, state.unresolved_ambiguities)
        saved = self.storage.save_state(state)
        self._enforce_pending_limit(user_id)
        return saved

    def get_state(self, conversation_id: str) -> ConversationState | None:
        return self.storage.get_state(conversation_id)

    def update_state(self, state: ConversationState) -> ConversationState:
        state.updated_at = datetime.now(timezone.utc)
        return self.storage.update_state(state)

    def clear_state(self, conversation_id: str) -> None:
        self.storage.delete_state(conversation_id)

    def expire_old_states(self) -> int:
        now = datetime.now(timezone.utc)
        if self._last_cleanup_at is not None:
            elapsed = now - self._last_cleanup_at
            if elapsed.total_seconds() < settings.conversation_cleanup_interval_minutes * 60:
                return 0
        removed = self.storage.cleanup_expired_states()
        self._last_cleanup_at = now
        return removed

    def resolve_pending_clarification(
        self,
        *,
        conversation_id: str | None,
        user_id: str,
        incoming_text: str,
        intent_enhancer: IntentEnhancer,
        allow_implicit_resume: bool = True,
    ) -> ClarificationResolution:
        state = self._select_pending_state(
            conversation_id=conversation_id,
            user_id=user_id,
            incoming_text=incoming_text,
            allow_implicit_resume=allow_implicit_resume,
        )
        if state is None:
            return ClarificationResolution(matched_pending_state=False, clarification_answer=incoming_text)

        logger.info("state resumed conversation_id=%s", state.conversation_id)
        updated_state, resolved = resolve_state_clarification(
            state=state,
            answer=incoming_text,
            intent_enhancer=intent_enhancer,
        )
        stored = self.update_state(updated_state)
        if resolved:
            logger.info("clarification resolved conversation_id=%s", stored.conversation_id)
            logger.info("ambiguity cleared conversation_id=%s", stored.conversation_id)
        return ClarificationResolution(
            matched_pending_state=True,
            resolved=resolved,
            conversation_state=stored,
            resumed_intent_result=stored.to_intent_result() if resolved else None,
            clarification_answer=incoming_text,
        )

    def _select_pending_state(
        self,
        *,
        conversation_id: str | None,
        user_id: str,
        incoming_text: str,
        allow_implicit_resume: bool,
    ) -> ConversationState | None:
        if conversation_id:
            state = self.get_state(conversation_id)
            if state and state.user_id == user_id and not state.sql_generation_ready:
                return state
            return None
        if not allow_implicit_resume:
            return None
        if not looks_like_clarification_answer(incoming_text):
            return None
        pending = self.storage.list_pending_for_user(user_id)
        return pending[0] if pending else None

    def _enforce_pending_limit(self, user_id: str) -> None:
        pending = self.storage.list_pending_for_user(user_id)
        for state in pending[settings.max_pending_clarifications :]:
            self.clear_state(state.conversation_id)
