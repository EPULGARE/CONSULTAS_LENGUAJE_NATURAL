from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException

from app.audit.models import QueryAuditEntry
from app.audit.service import AuditService
from app.conversation_state import ConversationState, get_conversation_state_manager
from app.core.config import settings
from app.core.security import normalize_question
from app.llm.classifier import DomainClassifier
from app.intent_enhancer import ClarificationResolutionRequest, EnhancedIntentResult, IntentEnhancer
from app.llm.sql_generator import SQLGenerator
from app.relationship_feedback import record_relationship_candidates
from app.schemas.query import QueryRequest
from app.schemas.response import QueryResponse
from app.context_selector.directory_loader import ContextDirectoryLoader
from app.context_selector.selector import SemanticContextSelector
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_catalog.readiness import validate_catalog_ready
from app.semantic_catalog.retriever import SemanticRetriever
from app.sql.executor import SQLExecutor
from app.sql.validator import SQLValidator

router = APIRouter(prefix="", tags=["query"])
NO_METADATA_ERROR = "No semantic metadata available for query generation."
CATALOG_NOT_READY_ERROR = "Semantic catalog is not ready for query generation."
logger = logging.getLogger(__name__)


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(payload: QueryRequest) -> QueryResponse:
    requested_dry_run = settings.query_dry_run_default if payload.dry_run is None else payload.dry_run
    return await _process_query(payload=payload, force_dry_run=requested_dry_run)


@router.post("/query/preview", response_model=QueryResponse)
async def query_preview_endpoint(payload: QueryRequest) -> QueryResponse:
    return await _process_query(payload=payload, force_dry_run=True)


@router.post("/query/resolve-clarification", response_model=QueryResponse)
async def query_resolve_clarification_endpoint(payload: ClarificationResolutionRequest) -> QueryResponse:
    intent_enhancer = IntentEnhancer()
    intent_result = payload.previous_intent_result or EnhancedIntentResult(
        original_question=payload.original_question,
        enhanced_question=payload.enhanced_question,
        ambiguity_detected=True,
        normalized_terms=[],
        applied_governed_rules=[],
        skipped_normalizations=[],
        clarification_questions=[],
        detected_entities=[],
        detected_filters=[],
        resolved_entities=[],
        resolved_filters=[],
        resolved_lookup_values=[],
        resolved_numeric_filters=[],
        intent_guardrails=[],
        unresolved_ambiguities=["pending_clarification"],
        confidence=0.5,
        requires_user_confirmation=True,
    )
    resolved_question = intent_enhancer.resolve_clarification(
        payload.original_question,
        intent_result,
        payload.clarification_answer,
    )
    request = QueryRequest(
        question=resolved_question,
        user_id="clarification_user",
        dry_run=True,
        clarification_answer=payload.clarification_answer,
    )
    return await _process_query(payload=request, force_dry_run=True)


async def _process_query(
    payload: QueryRequest,
    force_dry_run: bool,
    *,
    resumed_intent_result: EnhancedIntentResult | None = None,
    resumed_state: ConversationState | None = None,
) -> QueryResponse:
    loader = SemanticCatalogLoader(settings.metadata_path)
    domains = loader.load_domains()
    tables = loader.load_tables()
    relationships = loader.load_relationships()
    examples = loader.load_examples()
    parametric_mappings = loader.load_parametric_mappings()
    static_value_mappings = loader.load_static_value_mappings()
    oracle_comments = loader.load_oracle_comments()
    context_selector = SemanticContextSelector(ContextDirectoryLoader(settings.metadata_path))

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
    executor = SQLExecutor()
    audit = AuditService()
    conversation_manager = get_conversation_state_manager()
    if settings.conversation_state_enabled:
        conversation_manager.expire_old_states()

    normalized_question = normalize_question(payload.question)
    intent_result = resumed_intent_result or _default_intent_result(payload.question)
    generated_sql = None
    validated_sql = None
    domain = resumed_state.detected_domain if resumed_state else None
    retrieved_tables: list[str] = []
    debug_prompt: str | None = None

    try:
        readiness = validate_catalog_ready(domains=domains, tables=tables)
        if not readiness.ready:
            raise ValueError(CATALOG_NOT_READY_ERROR)

        effective_question = normalize_question(intent_result.enhanced_question)
        if settings.enable_intent_enhancer and settings.conversation_state_enabled and resumed_intent_result is None:
            pending_input = payload.clarification_answer or payload.question
            pending_resolution = conversation_manager.resolve_pending_clarification(
                conversation_id=payload.conversation_id,
                user_id=payload.user_id,
                incoming_text=pending_input,
                intent_enhancer=intent_enhancer,
                allow_implicit_resume=payload.conversation_id is not None or payload.clarification_answer is None,
            )
            if pending_resolution.matched_pending_state:
                if pending_resolution.resolved and pending_resolution.resumed_intent_result and pending_resolution.conversation_state:
                    return await _process_query(
                        payload=QueryRequest(
                            question=pending_resolution.conversation_state.original_question,
                            user_id=payload.user_id,
                            dry_run=payload.dry_run,
                            conversation_id=pending_resolution.conversation_state.conversation_id,
                        ),
                        force_dry_run=force_dry_run,
                        resumed_intent_result=pending_resolution.resumed_intent_result,
                        resumed_state=pending_resolution.conversation_state,
                    )
                state = pending_resolution.conversation_state
                return QueryResponse(
                    conversation_id=state.conversation_id if state else payload.conversation_id,
                    domain=state.detected_domain if state else None,
                    sql=None,
                    rows=[],
                    row_count=0,
                    question=state.original_question if state else payload.question,
                    detected_domain=state.detected_domain if state else None,
                    retrieved_tables=list(state.selected_tables) if state else [],
                    generated_sql=None,
                    validated_sql=None,
                    validation_status=None,
                    warnings=[],
                    execution_skipped=True,
                    execution_skip_reason="requires_user_confirmation",
                    debug_prompt=None,
                    original_question=state.original_question if state else payload.question,
                    enhanced_question=state.enhanced_question if state else payload.question,
                    normalized_terms=list(state.normalized_terms) if state else [],
                    applied_governed_rules=list(state.applied_governed_rules) if state else [],
                    skipped_normalizations=list(state.skipped_normalizations) if state else [],
                    ambiguity_detected=True,
                    clarification_questions=list(state.clarification_questions) if state else [],
                    detected_entities=list(state.resolved_entities) if state else [],
                    detected_filters=list(state.resolved_filters) if state else [],
                    resolved_entities=list(state.resolved_entities) if state else [],
                    resolved_filters=list(state.resolved_filters) if state else [],
                    resolved_lookup_values=list(state.resolved_lookup_values) if state else [],
                    resolved_numeric_filters=list(state.resolved_numeric_filters) if state else [],
                    intent_guardrails=list(state.intent_guardrails) if state else [],
                    unresolved_ambiguities=list(state.unresolved_ambiguities) if state else [],
                    detected_query_pattern=state.detected_query_pattern if state else None,
                    intent_confidence=0.5,
                    requires_user_confirmation=True,
                )

        if settings.enable_intent_enhancer and resumed_intent_result is None:
            intent_result = await intent_enhancer.enhance(payload.question)
            if payload.clarification_answer:
                try:
                    resolved_question = intent_enhancer.resolve_clarification(
                        payload.question,
                        intent_result,
                        payload.clarification_answer,
                    )
                except Exception:
                    resolved_question = intent_result.enhanced_question
                if resolved_question != intent_result.enhanced_question:
                    intent_result.enhanced_question = resolved_question
                    intent_result.requires_user_confirmation = False
                    intent_result.ambiguity_detected = False
                    intent_result.clarification_questions = []
                    intent_result.unresolved_ambiguities = []
            effective_question = normalize_question(intent_result.enhanced_question)
            if intent_result.requires_user_confirmation:
                retrieval = None
                try:
                    domain = await classifier.classify(effective_question, domains)
                    retrieval = retriever.retrieve(
                        domain=domain,
                        question=effective_question,
                        resolved_lookup_values=intent_result.resolved_lookup_values,
                        resolved_numeric_filters=intent_result.resolved_numeric_filters,
                        intent_guardrails=intent_result.intent_guardrails,
                        unresolved_ambiguities=intent_result.unresolved_ambiguities,
                    )
                    retrieved_tables = [table.full_name for table in retrieval.tables]
                    selection_debug = context_selector.last_selection_debug if hasattr(context_selector, "last_selection_debug") else {}
                    state = None
                    if settings.conversation_state_enabled:
                        state = conversation_manager.create_state(
                            user_id=payload.user_id,
                            intent_result=intent_result,
                            conversation_id=payload.conversation_id,
                            detected_domain=domain,
                            detected_query_pattern=(
                                retrieval.detected_query_pattern.type
                                if retrieval and retrieval.detected_query_pattern
                                else None
                            ),
                            selected_tables=selection_debug.get("final_selected_tables", retrieved_tables),
                            approved_join_paths=selection_debug.get("approved_join_paths", []),
                        )
                except Exception:
                    domain = domain or None
                    retrieved_tables = []
                    state = None
                response = QueryResponse(
                    conversation_id=state.conversation_id if state else payload.conversation_id,
                    domain=domain,
                    sql=None,
                    rows=[],
                    row_count=0,
                    question=payload.question,
                    detected_domain=domain,
                    retrieved_tables=retrieved_tables,
                    generated_sql=None,
                    validated_sql=None,
                    validation_status=None,
                    warnings=[],
                    execution_skipped=True,
                    execution_skip_reason="requires_user_confirmation",
                    debug_prompt=None,
                    original_question=intent_result.original_question,
                    enhanced_question=intent_result.enhanced_question,
                    normalized_terms=intent_result.normalized_terms,
                    applied_governed_rules=intent_result.applied_governed_rules,
                    skipped_normalizations=intent_result.skipped_normalizations,
                    ambiguity_detected=intent_result.ambiguity_detected,
                    clarification_questions=intent_result.clarification_questions,
                    detected_entities=intent_result.detected_entities,
                    detected_filters=intent_result.detected_filters,
                    resolved_entities=intent_result.resolved_entities,
                    resolved_filters=intent_result.resolved_filters,
                    resolved_lookup_values=intent_result.resolved_lookup_values,
                    resolved_numeric_filters=intent_result.resolved_numeric_filters,
                    intent_guardrails=intent_result.intent_guardrails,
                    unresolved_ambiguities=intent_result.unresolved_ambiguities,
                    detected_query_pattern=(
                        retrieval.detected_query_pattern.type
                        if retrieval and retrieval.detected_query_pattern
                        else None
                    ),
                    intent_confidence=intent_result.confidence,
                    requires_user_confirmation=True,
                )
                _audit_query(
                    audit=audit,
                    payload=payload,
                    normalized_question=normalized_question,
                    domain=domain,
                    generated_sql=None,
                    validated_sql=None,
                    success=True,
                    result_count=0,
                    executed=False,
                    execution_skip_reason="requires_user_confirmation",
                )
                return response

        domain = domain or await classifier.classify(effective_question, domains)
        retrieval = retriever.retrieve(
            domain=domain,
            question=effective_question,
            resolved_lookup_values=intent_result.resolved_lookup_values,
            resolved_numeric_filters=intent_result.resolved_numeric_filters,
            intent_guardrails=intent_result.intent_guardrails,
            unresolved_ambiguities=intent_result.unresolved_ambiguities,
        )
        retrieved_tables = [table.full_name for table in retrieval.tables]

        allowed_tables = {t.full_name for t in retrieval.tables}
        if not allowed_tables:
            raise ValueError(NO_METADATA_ERROR)

        generated_sql = await generator.generate(effective_question, retrieval)
        validated = validator.validate(
            generated_sql,
            allowed_tables=allowed_tables,
            disallowed_columns=retrieval.disallowed_columns,
            approved_relationships=retrieval.relationships,
            approved_parametric_mappings=retrieval.parametric_mappings,
            resolved_lookup_values=retrieval.resolved_lookup_values,
            resolved_numeric_filters=retrieval.resolved_numeric_filters,
            detected_query_pattern=retrieval.detected_query_pattern,
            required_null_filters=_required_active_record_filters(payload.question, retrieval.tables),
            required_text_filters=_required_text_filters(payload.question, retrieval.tables),
        )
        validated_sql = validated.sql

        effective_dry_run = force_dry_run or (not settings.query_allow_execution)
        execution_skip_reason = None
        if not settings.query_allow_execution:
            execution_skip_reason = "QUERY_ALLOW_EXECUTION=false"
        elif force_dry_run:
            execution_skip_reason = "dry_run=true"

        if settings.query_include_llm_prompt_in_debug and _is_development_environment():
            debug_prompt = _build_debug_prompt(payload.question, retrieved_tables)

        if effective_dry_run:
            response = QueryResponse(
                conversation_id=(resumed_state.conversation_id if resumed_state else payload.conversation_id),
                domain=domain,
                sql=validated_sql,
                rows=[],
                row_count=0,
                question=payload.question,
                detected_domain=domain,
                retrieved_tables=retrieved_tables,
                generated_sql=generated_sql,
                validated_sql=validated_sql,
                validation_status="valid",
                warnings=[],
                execution_skipped=True,
                execution_skip_reason=execution_skip_reason,
                debug_prompt=debug_prompt,
                original_question=intent_result.original_question,
                enhanced_question=intent_result.enhanced_question,
                normalized_terms=intent_result.normalized_terms,
                applied_governed_rules=intent_result.applied_governed_rules,
                skipped_normalizations=intent_result.skipped_normalizations,
                ambiguity_detected=intent_result.ambiguity_detected,
                clarification_questions=intent_result.clarification_questions,
                detected_entities=intent_result.detected_entities,
                detected_filters=intent_result.detected_filters,
                resolved_entities=intent_result.resolved_entities,
                resolved_filters=intent_result.resolved_filters,
                resolved_lookup_values=intent_result.resolved_lookup_values,
                resolved_numeric_filters=intent_result.resolved_numeric_filters,
                intent_guardrails=intent_result.intent_guardrails,
                unresolved_ambiguities=intent_result.unresolved_ambiguities,
                detected_query_pattern=retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None,
                intent_confidence=intent_result.confidence,
                requires_user_confirmation=intent_result.requires_user_confirmation,
            )
            if settings.conversation_state_enabled and resumed_state is not None:
                resumed_state.detected_domain = domain
                resumed_state.detected_query_pattern = (
                    retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None
                )
                resumed_state.selected_tables = list(retrieved_tables)
                resumed_state.sql_generation_ready = True
                conversation_manager.update_state(resumed_state)
            _audit_query(
                audit=audit,
                payload=payload,
                normalized_question=normalized_question,
                domain=domain,
                generated_sql=generated_sql,
                validated_sql=validated_sql,
                success=True,
                result_count=0,
                executed=False,
                execution_skip_reason=execution_skip_reason,
            )
            return response

        execution = executor.execute(validated_sql)
        if isinstance(execution, list):
            rows = execution
            row_count = len(rows)
        else:
            rows = execution.get("rows", [])
            row_count = execution.get("row_count", len(rows))

        response = QueryResponse(
            conversation_id=(resumed_state.conversation_id if resumed_state else payload.conversation_id),
            domain=domain,
            sql=validated_sql,
            rows=rows,
            row_count=row_count,
            question=payload.question,
            detected_domain=domain,
            retrieved_tables=retrieved_tables,
            generated_sql=generated_sql,
            validated_sql=validated_sql,
            validation_status="valid",
            warnings=[],
            execution_skipped=False,
            execution_skip_reason=None,
            debug_prompt=debug_prompt,
            original_question=intent_result.original_question,
            enhanced_question=intent_result.enhanced_question,
            normalized_terms=intent_result.normalized_terms,
            applied_governed_rules=intent_result.applied_governed_rules,
            skipped_normalizations=intent_result.skipped_normalizations,
            ambiguity_detected=intent_result.ambiguity_detected,
            clarification_questions=intent_result.clarification_questions,
            detected_entities=intent_result.detected_entities,
            detected_filters=intent_result.detected_filters,
            resolved_entities=intent_result.resolved_entities,
            resolved_filters=intent_result.resolved_filters,
            resolved_lookup_values=intent_result.resolved_lookup_values,
            resolved_numeric_filters=intent_result.resolved_numeric_filters,
            intent_guardrails=intent_result.intent_guardrails,
            unresolved_ambiguities=intent_result.unresolved_ambiguities,
            detected_query_pattern=retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None,
            intent_confidence=intent_result.confidence,
            requires_user_confirmation=intent_result.requires_user_confirmation,
        )
        if settings.conversation_state_enabled and resumed_state is not None:
            resumed_state.detected_domain = domain
            resumed_state.detected_query_pattern = retrieval.detected_query_pattern.type if retrieval.detected_query_pattern else None
            resumed_state.selected_tables = list(retrieved_tables)
            resumed_state.sql_generation_ready = True
            conversation_manager.update_state(resumed_state)
        _audit_query(
            audit=audit,
            payload=payload,
            normalized_question=normalized_question,
            domain=domain,
            generated_sql=generated_sql,
            validated_sql=validated_sql,
            success=True,
            result_count=row_count,
            executed=True,
            execution_skip_reason=None,
        )
        return response
    except Exception as exc:
        if getattr(exc, "error_code", "") == "UNAPPROVED_JOIN_PATH" and getattr(exc, "candidates", None):
            record_relationship_candidates(
                exc.candidates,
                question=payload.question,
                blocked_reason=getattr(exc, "error_code", "UNAPPROVED_JOIN_PATH"),
            )
        _audit_query(
            audit=audit,
            payload=payload,
            normalized_question=normalized_question,
            domain=domain,
            generated_sql=generated_sql,
            validated_sql=validated_sql,
            success=False,
            result_count=0,
            executed=False,
            execution_skip_reason="error",
            error=str(exc),
        )
        controlled_errors = {NO_METADATA_ERROR, CATALOG_NOT_READY_ERROR}
        detail = str(exc) if str(exc) in controlled_errors else "No se pudo procesar la consulta de forma segura"
        raise HTTPException(status_code=400, detail=detail) from exc


def _audit_query(
    *,
    audit: AuditService,
    payload: QueryRequest,
    normalized_question: str,
    domain: str | None,
    generated_sql: str | None,
    validated_sql: str | None,
    success: bool,
    result_count: int,
    executed: bool,
    execution_skip_reason: str | None,
    error: str | None = None,
) -> None:
    audit.log(
        QueryAuditEntry(
            user_id=payload.user_id,
            question=payload.question,
            normalized_question=normalized_question,
            domain=domain,
            generated_sql=generated_sql,
            validated_sql=validated_sql,
            success=success,
            error=error,
            result_count=result_count,
            created_at=AuditService.now(),
            extra={
                "dry_run_requested": payload.dry_run,
                "execution_performed": executed,
                "execution_skip_reason": execution_skip_reason,
            },
        )
    )


def _is_development_environment() -> bool:
    return settings.app_env.strip().lower() == "development"


def _build_debug_prompt(question: str, retrieved_tables: list[str]) -> str:
    table_list = ", ".join(retrieved_tables) if retrieved_tables else "<none>"
    return f"question={question}\nretrieved_tables={table_list}\noutput=sql_only"


def _required_active_record_filters(question: str, tables: list[object]) -> dict[str, list[str]]:
    if _asks_for_inactive_records(question):
        return {}
    output: dict[str, list[str]] = {}
    for table in tables:
        full_name = getattr(table, "full_name", "")
        columns = getattr(table, "columns", [])
        column_names = {getattr(column, "name", "").upper() for column in columns}
        if "FECHA_DESACTIVACION" in column_names:
            output[full_name] = ["FECHA_DESACTIVACION"]
    return output


def _asks_for_inactive_records(question: str) -> bool:
    normalized = normalize_question(question).lower()
    explicit_terms = (
        "desactivad",
        "inactiv",
        "histor",
        "vencid",
        "incluye desactiv",
        "incluir desactiv",
        "con fecha desactivacion",
        "fecha_desactivacion",
    )
    return any(term in normalized for term in explicit_terms)


def _required_text_filters(question: str, tables: list[object]) -> list[dict[str, str]]:
    table_names = {getattr(table, "full_name", "").upper() for table in tables}
    if "SAC.CODCA" not in table_names:
        return []
    concept_description = _extract_concept_description_filter(question)
    if not concept_description:
        return []
    return [
        {
            "table": "SAC.CODCA",
            "column": "DESCRIPCION",
            "value": concept_description,
        }
    ]


def _extract_concept_description_filter(question: str) -> str | None:
    normalized = normalize_question(question)
    match = re.search(
        r"\b(?:descripcion|descricipcion)\s+(?:concepto|cocepto)\s+(.+?)(?="
        r"\s+del\s+cliente|\s+del\s+cliente_id|\s+para\s+cliente|\s+para\s+clientes|"
        r"\s+del\s+municipio|\s+de\s+municipio|\s+en\s+municipio|\s+para\s+el\s+municipio|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = " ".join(match.group(1).strip().split())
    return value or None


def _default_intent_result(question: str) -> EnhancedIntentResult:
    return EnhancedIntentResult(
        original_question=question,
        enhanced_question=question,
        ambiguity_detected=False,
        normalized_terms=[],
        applied_governed_rules=[],
        skipped_normalizations=[],
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
