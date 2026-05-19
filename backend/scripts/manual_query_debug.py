from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.security import normalize_question  # noqa: E402
from app.conversation_state import get_conversation_state_manager  # noqa: E402
from app.context_selector.directory_loader import ContextDirectoryLoader  # noqa: E402
from app.context_selector.selector import SemanticContextSelector  # noqa: E402
from app.llm.classifier import DomainClassifier  # noqa: E402
from app.intent_enhancer import EnhancedIntentResult, IntentEnhancer  # noqa: E402
from app.llm.sql_generator import SQLGenerator  # noqa: E402
from app.relationship_feedback import generated_candidates_path, record_relationship_candidates  # noqa: E402
from app.semantic_catalog.loader import SemanticCatalogLoader  # noqa: E402
from app.semantic_catalog.readiness import validate_catalog_ready  # noqa: E402
from app.semantic_catalog.retriever import SemanticRetriever  # noqa: E402
from app.semantic_catalog.models import ParametricMapping  # noqa: E402
from app.sql.validator import SQLValidator  # noqa: E402

OUTPUTS_ROOT = (PROJECT_ROOT / "outputs").resolve()


def detect_missing_context_table_warning(question: str, loader: ContextDirectoryLoader, final_selected_tables: list[str]) -> list[str]:
    q = f" {question.lower()} "
    warnings: list[str] = []
    directory = loader.load_directory()
    selected_set = {t.upper() for t in final_selected_tables}
    for entry in directory:
        keywords = [k.lower().strip() for k in (entry.keywords + entry.business_terms) if k]
        if any(f" {kw} " in q for kw in keywords):
            if entry.table.upper() not in selected_set:
                warnings.append(
                    f"Posible tabla faltante en contexto: {entry.table}. Revise table_directory/context."
                )
    return warnings


def detect_missing_relation_warning(question: str, retrieval_tables: list[str], relationship_pairs: set[tuple[str, str]]) -> list[str]:
    q = question.lower()
    wants_municipio = "municipio" in q or "ciudad" in q or "localidad" in q
    has_medidores = any(t.upper() == "SAC.MEDIDORES" for t in retrieval_tables)
    if not wants_municipio or not has_medidores:
        return []
    graph: dict[str, set[str]] = {}
    for left, right in relationship_pairs:
        l = left.upper()
        r = right.upper()
        graph.setdefault(l, set()).add(r)
        graph.setdefault(r, set()).add(l)
    start = "SAC.MEDIDORES"
    target = "SAC.MUNICIPIOS"
    if start in graph and target in graph:
        queue = [start]
        visited = {start}
        while queue:
            current = queue.pop(0)
            if current == target:
                return []
            for nxt in graph.get(current, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
    return ["Falta relacion aprobada entre SAC.MEDIDORES y SAC.MUNICIPIOS para agrupar medidores por municipio."]


def detect_ambiguous_connected_warning(question: str, parametric_mappings: list[ParametricMapping]) -> list[str]:
    q = question.lower()
    if "conectado" not in q and "conectados" not in q:
        return []
    has_explicit_connected_mapping = any(
        "CONECT" in mapping.as_text.upper() for mapping in parametric_mappings
    )
    if has_explicit_connected_mapping:
        return []
    return ["Termino ambiguo: conectados. No existe mapping aprobado para cliente conectado."]


def resolve_output_path(output_arg: str) -> Path:
    OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_arg)
    output_path = (PROJECT_ROOT / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
    if OUTPUTS_ROOT != output_path and OUTPUTS_ROOT not in output_path.parents:
        raise ValueError("--save-output debe estar dentro de outputs/")
    return output_path


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value
    for secret in (
        settings.openrouter_api_key,
        settings.openrouter_proxy_password,
        settings.openrouter_proxy_user,
        settings.db_password,
    ):
        if secret:
            clean = clean.replace(secret, "***")
    clean = re.sub(r"sk-[A-Za-z0-9_\-]+", "***", clean)
    return clean


def force_debug_mode() -> None:
    settings.app_env = "development"
    settings.query_include_llm_prompt_in_debug = True


def run_single_question(
    question: str,
    *,
    show_prompt: bool = True,
    forced_domain: str | None = None,
    auto_accept_enhanced_intent: bool = False,
    conversation_id: str | None = None,
    clarification_answer: str | None = None,
    dump_state: bool = False,
) -> dict[str, Any]:
    force_debug_mode()
    loader = SemanticCatalogLoader(settings.metadata_path)
    domains = loader.load_domains()
    tables = loader.load_tables()
    relationships = loader.load_relationships()
    examples = loader.load_examples()
    parametric_mappings = loader.load_parametric_mappings()
    static_value_mappings = loader.load_static_value_mappings()
    oracle_comments = loader.load_oracle_comments()
    context_selector = SemanticContextSelector(ContextDirectoryLoader(settings.metadata_path))

    readiness = validate_catalog_ready(domains=domains, tables=tables)
    if not readiness.ready:
        return {
            "question": question,
            "warnings_or_errors": ["Semantic catalog is not ready for query generation."],
            "execution_skipped": True,
            "execution_reason": "dry_run_manual_debug",
        }

    classifier = DomainClassifier()
    intent_enhancer = IntentEnhancer()
    retriever = SemanticRetriever(
        tables=tables,
        relationships=relationships,
        examples=examples,
        parametric_mappings=parametric_mappings,
        static_value_mappings=static_value_mappings,
        oracle_comments=oracle_comments,
        context_selector=context_selector,
    )
    generator = SQLGenerator()
    validator = SQLValidator(max_rows=settings.db_max_rows, dialect=settings.db_dialect)
    conversation_manager = get_conversation_state_manager()
    if settings.conversation_state_enabled:
        conversation_manager.expire_old_states()

    normalized = normalize_question(question)
    warnings_or_errors: list[str] = []
    intent_result = EnhancedIntentResult(
        original_question=question,
        enhanced_question=question,
        ambiguity_detected=False,
        clarification_questions=[],
        detected_entities=[],
        detected_filters=[],
        resolved_entities=[],
        resolved_filters=[],
        resolved_lookup_values=[],
        resolved_numeric_filters=[],
        intent_guardrails=[],
        unresolved_ambiguities=[],
        confidence=1.0,
        requires_user_confirmation=False,
    )
    detected_domain: str | None = None
    retrieval_tables: list[str] = []
    selection_debug: dict[str, Any] = {}
    raw_openrouter_response: str | None = None
    extracted_sql: str | None = None
    prompt_sent_to_openrouter: str | None = None
    clarification_resolution: str | None = None
    state_dump: dict[str, Any] | None = None
    detected_query_pattern_type: str | None = None
    detected_query_pattern_skeleton: str | None = None
    relationship_candidates: list[dict[str, Any]] = []
    relationship_candidates_output_file: str | None = None
    relationship_candidates_review_file: str | None = None
    try:
        effective_question = normalized
        if settings.enable_intent_enhancer:
            pending_answer = clarification_answer or question
            if settings.conversation_state_enabled and pending_answer:
                if conversation_id:
                    existing_state = conversation_manager.get_state(conversation_id)
                    if existing_state is None:
                        backend = settings.conversation_storage_backend.strip().lower()
                        warning = (
                            f"conversation_id no encontrado usando backend '{backend}'. "
                            "Verifique TTL, archivo SQLite configurado o que la conversacion exista en el provider actual. "
                            "Si usa backend memory, recuerde que no sobrevive entre ejecuciones separadas del script."
                        )
                        return {
                            "question": question,
                            "conversation_id": conversation_id,
                            "detected_domain": None,
                            "retrieved_tables": [],
                            "table_selection_strategy": None,
                            "used_llm_table_selection": None,
                            "local_selection_confidence": None,
                            "local_selection_reason": None,
                            "local_selected_tables": [],
                            "llm_selected_tables": [],
                            "final_selected_tables": [],
                            "table_selection_reason": None,
                            "table_selection_confidence": None,
                            "approved_join_paths": [],
                            "enhanced_question": question,
                            "normalized_terms": [],
                            "applied_governed_rules": [],
                            "skipped_normalizations": [],
                            "clarification_questions": [],
                            "ambiguity_detected": False,
                            "intent_confidence": None,
                            "requires_user_confirmation": False,
                            "resolved_entities": [],
                            "resolved_filters": [],
                            "resolved_lookup_values": [],
                            "resolved_numeric_filters": [],
                            "intent_guardrails": [],
                            "unresolved_ambiguities": [],
                            "warnings_or_errors": [warning],
                            "execution_skipped": True,
                            "execution_reason": "conversation_state_not_found",
                            "state_dump": state_dump,
                        }
                pending_resolution = conversation_manager.resolve_pending_clarification(
                    conversation_id=conversation_id,
                    user_id="manual_debug_user",
                    incoming_text=pending_answer,
                    intent_enhancer=intent_enhancer,
                )
                if pending_resolution.matched_pending_state:
                    if pending_resolution.conversation_state:
                        conversation_id = pending_resolution.conversation_state.conversation_id
                    if pending_resolution.conversation_state and dump_state:
                        state_dump = pending_resolution.conversation_state.model_dump(mode="json")
                    if pending_resolution.resolved and pending_resolution.resumed_intent_result and pending_resolution.conversation_state:
                        intent_result = pending_resolution.resumed_intent_result
                        clarification_resolution = (
                            pending_resolution.conversation_state.clarification_answers[-1].resolved_as
                            if pending_resolution.conversation_state.clarification_answers
                            else None
                        )
                        question = pending_resolution.conversation_state.original_question
                    else:
                        state = pending_resolution.conversation_state
                        return {
                            "question": state.original_question if state else question,
                            "conversation_id": state.conversation_id if state else conversation_id,
                            "detected_domain": state.detected_domain if state else None,
                            "retrieved_tables": list(state.selected_tables) if state else [],
                            "table_selection_strategy": None,
                            "used_llm_table_selection": None,
                            "local_selection_confidence": None,
                            "local_selection_reason": None,
                            "local_selected_tables": [],
                            "llm_selected_tables": [],
                            "final_selected_tables": list(state.selected_tables) if state else [],
                            "table_selection_reason": None,
                            "table_selection_confidence": None,
                            "approved_join_paths": list(state.approved_join_paths) if state else [],
                            "enhanced_question": state.enhanced_question if state else question,
                            "normalized_terms": list(state.normalized_terms) if state else [],
                            "applied_governed_rules": list(state.applied_governed_rules) if state else [],
                            "skipped_normalizations": list(state.skipped_normalizations) if state else [],
                            "clarification_questions": list(state.clarification_questions) if state else [],
                            "ambiguity_detected": True,
                            "intent_confidence": 0.5,
                            "requires_user_confirmation": True,
                            "resolved_entities": list(state.resolved_entities) if state else [],
                            "resolved_filters": list(state.resolved_filters) if state else [],
                            "resolved_lookup_values": [item.model_dump() for item in (state.resolved_lookup_values if state else [])],
                            "resolved_numeric_filters": [item.model_dump() for item in (state.resolved_numeric_filters if state else [])],
                            "intent_guardrails": list(state.intent_guardrails) if state else [],
                            "unresolved_ambiguities": list(state.unresolved_ambiguities) if state else [],
                            "warnings_or_errors": warnings_or_errors,
                            "execution_skipped": True,
                            "execution_reason": "requires_user_confirmation",
                            "state_dump": state_dump,
                        }
                else:
                    intent_result = asyncio.run(intent_enhancer.enhance(question))
            else:
                intent_result = asyncio.run(intent_enhancer.enhance(question))
            if clarification_answer and not conversation_id:
                resolved_question = intent_enhancer.resolve_clarification(question, intent_result, clarification_answer)
                if resolved_question != intent_result.enhanced_question:
                    clarification_resolution = f"legacy => {clarification_answer.strip().lower()}"
                    intent_result.enhanced_question = resolved_question
                    intent_result.requires_user_confirmation = False
                    intent_result.ambiguity_detected = False
                    intent_result.clarification_questions = []
                    intent_result.unresolved_ambiguities = []
            effective_question = normalize_question(intent_result.enhanced_question)
            if intent_result.requires_user_confirmation and not auto_accept_enhanced_intent:
                detected_domain = forced_domain or asyncio.run(classifier.classify(effective_question, domains))
                retrieval = retriever.retrieve(
                    domain=detected_domain,
                    question=effective_question,
                    resolved_lookup_values=intent_result.resolved_lookup_values,
                    resolved_numeric_filters=intent_result.resolved_numeric_filters,
                    intent_guardrails=intent_result.intent_guardrails,
                    unresolved_ambiguities=intent_result.unresolved_ambiguities,
                )
                detected_query_pattern_type = retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None
                detected_query_pattern_skeleton = retrieval.detected_query_pattern.sql_skeleton if retrieval.detected_query_pattern else None
                retrieval_tables = [t.full_name for t in retrieval.tables]
                selection_debug = context_selector.last_selection_debug if hasattr(context_selector, "last_selection_debug") else {}
                state = None
                if settings.conversation_state_enabled:
                    state = conversation_manager.create_state(
                        user_id="manual_debug_user",
                        intent_result=intent_result,
                        conversation_id=conversation_id,
                        detected_domain=detected_domain,
                        detected_query_pattern=retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None,
                        selected_tables=selection_debug.get("final_selected_tables", retrieval_tables),
                        approved_join_paths=selection_debug.get("approved_join_paths", []),
                    )
                    if dump_state:
                        state_dump = state.model_dump(mode="json")
                    return {
                        "question": question,
                        "conversation_id": state.conversation_id if state else conversation_id,
                        "detected_domain": detected_domain,
                        "retrieved_tables": retrieval_tables,
                        "table_selection_strategy": selection_debug.get("strategy"),
                        "used_llm_table_selection": selection_debug.get("used_llm_table_selection"),
                        "local_selection_confidence": selection_debug.get("local_selection_confidence"),
                        "local_selection_reason": selection_debug.get("local_selection_reason"),
                        "local_selected_tables": selection_debug.get("local_selected_tables", []),
                        "llm_selected_tables": selection_debug.get("llm_selected_tables", []),
                        "final_selected_tables": selection_debug.get("final_selected_tables", []),
                    "table_selection_reason": selection_debug.get("table_selection_reason"),
                    "table_selection_confidence": selection_debug.get("confidence"),
                    "approved_join_paths": selection_debug.get("approved_join_paths", []),
                    "detected_query_pattern_type": retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None,
                    "detected_query_pattern_skeleton": retrieval.detected_query_pattern.sql_skeleton if retrieval.detected_query_pattern else None,
                    "enhanced_question": intent_result.enhanced_question,
                    "normalized_terms": intent_result.normalized_terms,
                    "applied_governed_rules": intent_result.applied_governed_rules,
                    "skipped_normalizations": intent_result.skipped_normalizations,
                    "clarification_questions": intent_result.clarification_questions,
                    "ambiguity_detected": intent_result.ambiguity_detected,
                    "intent_confidence": intent_result.confidence,
                    "requires_user_confirmation": True,
                    "resolved_entities": intent_result.resolved_entities,
                    "resolved_filters": intent_result.resolved_filters,
                    "resolved_lookup_values": [item.model_dump() for item in intent_result.resolved_lookup_values],
                    "resolved_numeric_filters": [item.model_dump() for item in intent_result.resolved_numeric_filters],
                    "intent_guardrails": intent_result.intent_guardrails,
                    "unresolved_ambiguities": intent_result.unresolved_ambiguities,
                    "warnings_or_errors": warnings_or_errors,
                    "execution_skipped": True,
                    "execution_reason": "requires_user_confirmation",
                    "state_dump": state_dump,
                }

        detected_domain = forced_domain or asyncio.run(classifier.classify(effective_question, domains))
        retrieval = retriever.retrieve(
            domain=detected_domain,
            question=effective_question,
            resolved_lookup_values=intent_result.resolved_lookup_values,
            resolved_numeric_filters=intent_result.resolved_numeric_filters,
            intent_guardrails=intent_result.intent_guardrails,
            unresolved_ambiguities=intent_result.unresolved_ambiguities,
        )
        detected_query_pattern_type = retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None
        detected_query_pattern_skeleton = retrieval.detected_query_pattern.sql_skeleton if retrieval.detected_query_pattern else None
        retrieval_tables = [t.full_name for t in retrieval.tables]
        selection_debug = context_selector.last_selection_debug if hasattr(context_selector, "last_selection_debug") else {}
        directory_loader = getattr(context_selector, "loader", None)
        if directory_loader is not None:
            missing_context_warnings = detect_missing_context_table_warning(
                question=effective_question,
                loader=directory_loader,
                final_selected_tables=selection_debug.get("final_selected_tables", []),
            )
            warnings_or_errors.extend(missing_context_warnings)
        relationship_pairs = {(r.left_table, r.right_table) for r in retrieval.relationships}
        warnings_or_errors.extend(
            detect_missing_relation_warning(
                question=effective_question,
                retrieval_tables=[t.full_name for t in retrieval.tables],
                relationship_pairs=relationship_pairs,
            )
        )
        if "conectados => cliente o medidor" in intent_result.unresolved_ambiguities:
            warnings_or_errors.extend(detect_ambiguous_connected_warning(effective_question, retrieval.parametric_mappings))
        trace = asyncio.run(generator.generate_with_trace(effective_question, retrieval))
        raw_openrouter_response = sanitize_text(trace.raw_llm_response)
        prompt_sent_to_openrouter = sanitize_text(trace.debug_llm_prompt) if show_prompt else None

        generated_sql = trace.extracted_sql
        extracted_sql = sanitize_text(generated_sql)
        if trace.extraction_error or not generated_sql:
            warnings_or_errors.append(trace.extraction_error or "LLM_NO_SQL_FOUND")
            return {
                "question": question,
                "conversation_id": conversation_id,
                "detected_domain": detected_domain,
                "retrieved_tables": [t.full_name for t in retrieval.tables],
                "table_selection_strategy": selection_debug.get("strategy"),
                "used_llm_table_selection": selection_debug.get("used_llm_table_selection"),
                "local_selection_confidence": selection_debug.get("local_selection_confidence"),
                "local_selection_reason": selection_debug.get("local_selection_reason"),
                "local_selected_tables": selection_debug.get("local_selected_tables", []),
                "llm_selected_tables": selection_debug.get("llm_selected_tables", []),
                "final_selected_tables": selection_debug.get("final_selected_tables", []),
                "table_selection_reason": selection_debug.get("table_selection_reason"),
                "table_selection_confidence": selection_debug.get("confidence"),
                "approved_join_paths": selection_debug.get("approved_join_paths", []),
                "prompt_sent_to_openrouter": prompt_sent_to_openrouter,
                "raw_openrouter_response": sanitize_text(trace.raw_llm_response),
                "sql_generated_or_extracted": None,
                "sql_validated_final": None,
                "detected_query_pattern_type": retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None,
                "detected_query_pattern_skeleton": retrieval.detected_query_pattern.sql_skeleton if retrieval.detected_query_pattern else None,
                "warnings_or_errors": warnings_or_errors,
                "execution_skipped": True,
                "execution_reason": "dry_run_manual_debug",
                "enhanced_question": intent_result.enhanced_question,
                "normalized_terms": intent_result.normalized_terms,
                "applied_governed_rules": intent_result.applied_governed_rules,
                "skipped_normalizations": intent_result.skipped_normalizations,
                "clarification_questions": intent_result.clarification_questions,
                "ambiguity_detected": intent_result.ambiguity_detected,
                "intent_confidence": intent_result.confidence,
                "requires_user_confirmation": intent_result.requires_user_confirmation,
                "resolved_entities": intent_result.resolved_entities,
                "resolved_filters": intent_result.resolved_filters,
                "resolved_lookup_values": [item.model_dump() for item in intent_result.resolved_lookup_values],
                "intent_guardrails": intent_result.intent_guardrails,
                "unresolved_ambiguities": intent_result.unresolved_ambiguities,
                "clarification_resolution": clarification_resolution,
                "state_dump": state_dump,
            }

        validated = validator.validate(
            generated_sql,
            allowed_tables={t.full_name for t in retrieval.tables},
            disallowed_columns=retrieval.disallowed_columns,
            approved_relationships=retrieval.relationships,
            approved_parametric_mappings=retrieval.parametric_mappings,
            resolved_lookup_values=retrieval.resolved_lookup_values,
            resolved_numeric_filters=retrieval.resolved_numeric_filters,
            detected_query_pattern=retrieval.detected_query_pattern,
        )
        return {
            "question": question,
            "conversation_id": conversation_id,
            "detected_domain": detected_domain,
            "retrieved_tables": [t.full_name for t in retrieval.tables],
            "table_selection_strategy": selection_debug.get("strategy"),
            "used_llm_table_selection": selection_debug.get("used_llm_table_selection"),
            "local_selection_confidence": selection_debug.get("local_selection_confidence"),
            "local_selection_reason": selection_debug.get("local_selection_reason"),
            "local_selected_tables": selection_debug.get("local_selected_tables", []),
            "llm_selected_tables": selection_debug.get("llm_selected_tables", []),
            "final_selected_tables": selection_debug.get("final_selected_tables", []),
            "table_selection_reason": selection_debug.get("table_selection_reason"),
            "table_selection_confidence": selection_debug.get("confidence"),
            "approved_join_paths": selection_debug.get("approved_join_paths", []),
            "prompt_sent_to_openrouter": prompt_sent_to_openrouter,
            "raw_openrouter_response": sanitize_text(trace.raw_llm_response),
            "sql_generated_or_extracted": sanitize_text(generated_sql),
            "sql_validated_final": sanitize_text(validated.sql),
            "detected_query_pattern_type": retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None,
            "detected_query_pattern_skeleton": retrieval.detected_query_pattern.sql_skeleton if retrieval.detected_query_pattern else None,
            "warnings_or_errors": warnings_or_errors,
            "execution_skipped": True,
            "execution_reason": "dry_run_manual_debug",
            "enhanced_question": intent_result.enhanced_question,
            "normalized_terms": intent_result.normalized_terms,
            "applied_governed_rules": intent_result.applied_governed_rules,
            "skipped_normalizations": intent_result.skipped_normalizations,
            "clarification_questions": intent_result.clarification_questions,
            "ambiguity_detected": intent_result.ambiguity_detected,
            "intent_confidence": intent_result.confidence,
            "requires_user_confirmation": intent_result.requires_user_confirmation,
            "resolved_entities": intent_result.resolved_entities,
            "resolved_filters": intent_result.resolved_filters,
            "resolved_lookup_values": [item.model_dump() for item in intent_result.resolved_lookup_values],
            "resolved_numeric_filters": [item.model_dump() for item in intent_result.resolved_numeric_filters],
            "intent_guardrails": intent_result.intent_guardrails,
            "unresolved_ambiguities": intent_result.unresolved_ambiguities,
            "clarification_resolution": clarification_resolution,
            "state_dump": state_dump,
            "relationship_candidates": relationship_candidates,
            "relationship_candidates_output_file": relationship_candidates_output_file,
            "relationship_candidates_review_file": relationship_candidates_review_file,
        }
    except Exception as exc:
        if getattr(exc, "error_code", "") == "UNAPPROVED_JOIN_PATH" and getattr(exc, "candidates", None):
            write_result = record_relationship_candidates(
                exc.candidates,
                question=question,
                blocked_reason=getattr(exc, "error_code", "UNAPPROVED_JOIN_PATH"),
            )
            relationship_candidates = [item.model_dump(mode="json") for item in write_result.candidates]
            relationship_candidates_output_file = write_result.output_path
            relationship_candidates_review_file = write_result.review_path
        warnings_or_errors.append(sanitize_text(str(exc)) or "unknown_error")
        return {
            "question": question,
            "conversation_id": conversation_id,
            "detected_domain": detected_domain,
            "retrieved_tables": retrieval_tables,
            "table_selection_strategy": selection_debug.get("strategy"),
            "used_llm_table_selection": selection_debug.get("used_llm_table_selection"),
            "local_selection_confidence": selection_debug.get("local_selection_confidence"),
            "local_selection_reason": selection_debug.get("local_selection_reason"),
            "local_selected_tables": selection_debug.get("local_selected_tables", []),
            "llm_selected_tables": selection_debug.get("llm_selected_tables", []),
            "final_selected_tables": selection_debug.get("final_selected_tables", []),
            "table_selection_reason": selection_debug.get("table_selection_reason"),
            "table_selection_confidence": selection_debug.get("confidence"),
            "approved_join_paths": selection_debug.get("approved_join_paths", []),
            "prompt_sent_to_openrouter": prompt_sent_to_openrouter,
            "raw_openrouter_response": raw_openrouter_response,
            "sql_generated_or_extracted": extracted_sql,
            "sql_validated_final": None,
            "detected_query_pattern_type": detected_query_pattern_type,
            "detected_query_pattern_skeleton": detected_query_pattern_skeleton,
            "warnings_or_errors": warnings_or_errors,
            "execution_skipped": True,
            "execution_reason": "dry_run_manual_debug",
            "enhanced_question": intent_result.enhanced_question,
            "normalized_terms": intent_result.normalized_terms,
            "applied_governed_rules": intent_result.applied_governed_rules,
            "skipped_normalizations": intent_result.skipped_normalizations,
            "clarification_questions": intent_result.clarification_questions,
            "ambiguity_detected": intent_result.ambiguity_detected,
            "intent_confidence": intent_result.confidence,
            "requires_user_confirmation": intent_result.requires_user_confirmation,
            "resolved_entities": intent_result.resolved_entities,
            "resolved_filters": intent_result.resolved_filters,
            "resolved_lookup_values": [item.model_dump() for item in intent_result.resolved_lookup_values],
            "resolved_numeric_filters": [item.model_dump() for item in intent_result.resolved_numeric_filters],
            "intent_guardrails": intent_result.intent_guardrails,
            "unresolved_ambiguities": intent_result.unresolved_ambiguities,
            "clarification_resolution": clarification_resolution,
            "state_dump": state_dump,
            "relationship_candidates": relationship_candidates,
            "relationship_candidates_output_file": relationship_candidates_output_file,
            "relationship_candidates_review_file": relationship_candidates_review_file,
        }


def print_report(report: dict[str, Any], *, show_prompt: bool) -> None:
    approved_lookup_matches = []
    for item in report.get("resolved_lookup_values", []):
        if isinstance(item, dict) and item.get("resolution_source") == "approved_lookup_values":
            approved_lookup_matches.append(item)
    print("=== PREGUNTA ===")
    print(report.get("question", ""))
    print("\n=== DOMINIO DETECTADO ===")
    print(report.get("detected_domain"))
    print("\n=== CONVERSATION ID ===")
    print(report.get("conversation_id"))
    print("\n=== ENHANCED QUESTION ===")
    print(report.get("enhanced_question"))
    print("\n=== SEMANTIC NORMALIZATION ===")
    print(f"normalized_terms={report.get('normalized_terms', [])}")
    print(f"applied_governed_rules={report.get('applied_governed_rules', [])}")
    print(f"skipped_normalizations={report.get('skipped_normalizations', [])}")
    print("\n=== CLARIFICATIONS ===")
    clarifications = report.get("clarification_questions", [])
    if clarifications:
        for question in clarifications:
            print(f"- {question}")
    else:
        print("[]")
    print("\n=== RESOLVED ENTITIES ===")
    print(report.get("resolved_entities", []))
    print("\n=== RESOLVED FILTERS ===")
    print(report.get("resolved_filters", []))
    print("\n=== RESOLVED LOOKUP VALUES ===")
    print(report.get("resolved_lookup_values", []))
    print("\n=== APPROVED LOOKUP VALUES MATCHES ===")
    if approved_lookup_matches:
        for item in approved_lookup_matches:
            print(
                f"- {item.get('matched_synonym')} -> {item.get('source_table')}.{item.get('source_column')} / "
                f"{item.get('fixed_filter_value')} / {item.get('canonical_value')} / code={item.get('code')}"
            )
    else:
        print("[]")
    print("\n=== RESOLVED NUMERIC FILTERS ===")
    print(report.get("resolved_numeric_filters", []))
    print("\n=== RELATIONSHIP CANDIDATES ===")
    candidates = report.get("relationship_candidates", [])
    if candidates:
        for item in candidates:
            print(
                f"- {item.get('from_table')}.{item.get('from_column')} = "
                f"{item.get('to_table')}.{item.get('to_column')}"
            )
            print(f"  status=blocked")
            print(f"  review_file={report.get('relationship_candidates_output_file') or str(generated_candidates_path())}")
    else:
        print("[]")
    print("\n=== INTENT GUARDRAILS ===")
    print(report.get("intent_guardrails", []))
    print("\n=== UNRESOLVED AMBIGUITIES ===")
    print(report.get("unresolved_ambiguities", []))
    print("\n=== CLARIFICATION RESOLUTION ===")
    print(report.get("clarification_resolution"))
    if report.get("state_dump") is not None:
        print("\n=== STATE DUMP ===")
        print(json.dumps(report.get("state_dump"), indent=2, ensure_ascii=False))
    print("\n=== TABLAS RECUPERADAS ===")
    print(", ".join(report.get("retrieved_tables", [])))
    print("\n=== QUERY PATTERN ===")
    print(report.get("detected_query_pattern_type"))
    print(report.get("detected_query_pattern_skeleton"))
    print("\n=== TABLE SELECTION STRATEGY ===")
    print(f"strategy={report.get('table_selection_strategy')}")
    print(f"used_llm_table_selection={report.get('used_llm_table_selection')}")
    print(f"confidence={report.get('local_selection_confidence')}")
    print(f"reason={report.get('local_selection_reason')}")
    print("\n=== SELECCION DE TABLAS ===")
    print(f"local_selected_tables={report.get('local_selected_tables', [])}")
    print(f"llm_selected_tables={report.get('llm_selected_tables', [])}")
    print(f"final_selected_tables={report.get('final_selected_tables', [])}")
    print(f"table_selection_reason={report.get('table_selection_reason')}")
    print(f"confidence={report.get('table_selection_confidence')}")
    print("\n=== JOIN PATHS APROBADOS ===")
    for path in report.get("approved_join_paths", []):
        print(f"- {path}")
    if show_prompt:
        print("\n=== PROMPT ENVIADO A OPENROUTER ===")
        print(report.get("prompt_sent_to_openrouter"))
    print("\n=== RESPUESTA RAW OPENROUTER ===")
    print(report.get("raw_openrouter_response"))
    print("\n=== SQL GENERADO / EXTRAIDO ===")
    print(report.get("sql_generated_or_extracted"))
    print("\n=== SQL VALIDADO FINAL ===")
    print(report.get("sql_validated_final"))
    print("\n=== WARNINGS / ERRORES ===")
    print("\n".join(report.get("warnings_or_errors", [])))
    print("\n=== EJECUCION ===")
    print(f"execution_skipped={str(report.get('execution_skipped', True)).lower()}")
    print(f"reason={report.get('execution_reason', 'dry_run_manual_debug')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug manual de preguntas Text-to-SQL en dry-run")
    parser.add_argument("question", nargs="?", help="Pregunta de prueba")
    parser.add_argument("--show-prompt", default="true", choices=["true", "false"])
    parser.add_argument("--save-output", required=False, help="Guardar JSON dentro de outputs/")
    parser.add_argument("--domain", required=False, help="Forzar dominio")
    parser.add_argument("--auto-accept-enhanced-intent", action="store_true", help="Continuar aunque el intent_enhancer pida confirmacion")
    parser.add_argument("--conversation-id", required=False, help="Reanudar una conversacion pendiente")
    parser.add_argument("--clarification-answer", required=False, help="Respuesta de aclaracion (clientes|medidores)")
    parser.add_argument("--dump-state", action="store_true", help="Mostrar el conversation state cuando exista")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    show_prompt = args.show_prompt.lower() == "true"

    def _run_and_maybe_save(q: str) -> None:
        report = run_single_question(
            q,
            show_prompt=show_prompt,
            forced_domain=args.domain,
            auto_accept_enhanced_intent=args.auto_accept_enhanced_intent,
            conversation_id=args.conversation_id,
            clarification_answer=args.clarification_answer,
            dump_state=args.dump_state,
        )
        print_report(report, show_prompt=show_prompt)
        if args.save_output:
            output_path = resolve_output_path(args.save_output)
            output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.question:
        _run_and_maybe_save(args.question)
        return 0

    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", "salir"}:
            break
        _run_and_maybe_save(q)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
