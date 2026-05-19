from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from datetime import datetime, timezone

from app.conversation_state.models import ClarificationAnswerRecord, ConversationState
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_catalog.models import ResolvedLookupValue

if TYPE_CHECKING:
    from app.intent_enhancer import IntentEnhancer


def looks_like_clarification_answer(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    tokens = normalized.split()
    token_count = len(tokens)
    if token_count > 8 and "me refiero" not in normalized and "quiero decir" not in normalized:
        return False
    if any(token in normalized for token in ("cuantos", "cantidad", "numero", "listar", "muestre", "muestrame", "dame", "estado cliente", "estado actual", "usuarios conectados", "clientes por", "medidores por")):
        return False
    governed_terms = {
        "cliente",
        "clientes",
        "usuario",
        "usuarios",
        "abonado",
        "abonados",
        "medidor",
        "medidores",
        "contador",
        "contadores",
        "proceso",
        "procesos",
        "activo",
        "activos",
        "inactivo",
        "inactivos",
        "conectado",
        "conectados",
        "instalado",
        "instalados",
        "retirado",
        "retirados",
        "municipio",
        "departamento",
        "ranking",
        "top",
    }
    if token_count <= 3 and any(term in tokens for term in governed_terms):
        return True
    if normalized.startswith("me refiero a ") or normalized.startswith("quiero decir "):
        return any(term in tokens for term in governed_terms)
    return False


def resolve_state_clarification(
    *,
    state: ConversationState,
    answer: str,
    intent_enhancer: IntentEnhancer,
) -> tuple[ConversationState, bool]:
    normalized_answer = _normalize_text(answer)
    if not normalized_answer:
        return state, False

    updated_state = state.model_copy(deep=True)
    unresolved = list(updated_state.unresolved_ambiguities)
    resolved_as: str | None = None

    for item in list(unresolved):
        if item in {"activos => cliente o medidor", "conectados => cliente o medidor"}:
            target = _resolve_entity_scope_answer(normalized_answer)
            if target is None:
                continue
            resolved_question = intent_enhancer.resolve_clarification(
                updated_state.original_question,
                updated_state.to_intent_result(),
                target,
            )
            updated_state.enhanced_question = resolved_question
            unresolved.remove(item)
            resolved_as = f"{item.split(' => ', 1)[0]} => {target}"
            break
        if item.startswith("lookup_value_unresolved:"):
            resolved_lookup = _resolve_lookup_value_answer(
                raw_item=item,
                answer=normalized_answer,
                loader=intent_enhancer.loader,
            )
            if resolved_lookup is None:
                continue
            updated_state.resolved_lookup_values.append(resolved_lookup)
            updated_state.resolved_filters.append(resolved_lookup.as_text)
            updated_state.enhanced_question = _append_lookup_resolution_hint(
                updated_state.enhanced_question,
                resolved_lookup,
            )
            unresolved.remove(item)
            resolved_as = f"{resolved_lookup.source_column} => {resolved_lookup.canonical_value}"
            break

    updated_state.unresolved_ambiguities = unresolved
    updated_state.clarification_answers.append(
        ClarificationAnswerRecord(
            question=updated_state.clarification_questions[0] if updated_state.clarification_questions else "pending_clarification",
            answer=answer,
            resolved_as=resolved_as,
        )
    )
    if not unresolved:
        updated_state.clarification_questions = []
        updated_state.intent_guardrails = []
        updated_state.sql_generation_ready = True
    updated_state.updated_at = datetime.now(timezone.utc)
    return updated_state, not unresolved


def _resolve_entity_scope_answer(answer: str) -> str | None:
    if any(token in answer.split() for token in ("cliente", "clientes", "usuario", "usuarios", "abonado", "abonados")):
        return "clientes"
    if any(token in answer.split() for token in ("medidor", "medidores", "contador", "contadores")):
        return "medidores"
    if any(token in answer.split() for token in ("proceso", "procesos", "pqr", "pqrs")):
        return "procesos"
    return None


def _resolve_lookup_value_answer(
    *,
    raw_item: str,
    answer: str,
    loader: SemanticCatalogLoader,
) -> ResolvedLookupValue | None:
    _, source_table, source_column, fixed_filter_value, _candidate_text, valid_values = raw_item.split(":", 5)
    valid_value_set = {_normalize_text(value) for value in valid_values.split("|") if value}
    if valid_value_set and _normalize_text(answer) not in valid_value_set:
        matched_from_rule = _lookup_canonical_from_rule(
            answer=answer,
            loader=loader,
            source_table=source_table,
            source_column=source_column,
            fixed_filter_value=fixed_filter_value,
        )
        if matched_from_rule is None:
            return None
        canonical_value, matched_synonym = matched_from_rule
    else:
        canonical_value = next(
            (value for value in valid_values.split("|") if _normalize_text(value) == _normalize_text(answer)),
            answer,
        )
        matched_synonym = answer

    approved_mapping = next(
        (
            mapping
            for mapping in loader.load_parametric_mappings()
            if mapping.source_table.upper() == source_table.upper()
            and mapping.source_column.upper() == source_column.upper()
        ),
        None,
    )
    if approved_mapping is None:
        return None
    return ResolvedLookupValue(
        source_table=approved_mapping.source_table,
        source_column=approved_mapping.source_column,
        lookup_table=approved_mapping.lookup_table,
        lookup_description=approved_mapping.lookup_description,
        fixed_filter_value=fixed_filter_value,
        canonical_value=canonical_value,
        matched_synonym=matched_synonym,
        valid_values=[value for value in valid_values.split("|") if value],
    )


def _lookup_canonical_from_rule(
    *,
    answer: str,
    loader: SemanticCatalogLoader,
    source_table: str,
    source_column: str,
    fixed_filter_value: str,
) -> tuple[str, str] | None:
    normalized_answer = _normalize_text(answer)
    for rule in loader.load_lookup_value_normalizations():
        if (
            rule.source_table.upper() != source_table.upper()
            or rule.source_column.upper() != source_column.upper()
            or rule.fixed_filter_value.upper() != fixed_filter_value.upper()
        ):
            continue
        matches: list[tuple[str, str]] = []
        for canonical_value, details in rule.canonical_values.items():
            for candidate in [canonical_value, *(details.synonyms or [])]:
                if _normalize_text(candidate) == normalized_answer:
                    matches.append((canonical_value, candidate))
                    break
        if len(matches) == 1:
            return matches[0]
    return None


def _append_lookup_resolution_hint(question: str, resolved_lookup: ResolvedLookupValue) -> str:
    hint = (
        f"Usar valor canonico gobernado para {resolved_lookup.source_table}.{resolved_lookup.source_column}: "
        f"{resolved_lookup.canonical_value}"
    )
    if hint in question:
        return question
    return f"{question}. {hint}."


def _normalize_text(value: str) -> str:
    lowered = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(lowered.split())
