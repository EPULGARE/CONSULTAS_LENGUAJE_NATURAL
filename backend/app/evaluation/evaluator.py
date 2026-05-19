from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from sqlglot import exp, parse

from app.core.config import settings
from app.evaluation.models import EvaluationFailure, EvaluationQuestion, EvaluationReport, EvaluationResult, EvaluationSuccess
from app.context_selector.directory_loader import ContextDirectoryLoader
from app.context_selector.selector import SemanticContextSelector
from app.intent_enhancer import IntentEnhancer
from app.llm.classifier import DomainClassifier
from app.llm.sql_generator import SQLGenerator
from app.relationship_feedback import record_relationship_candidates
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_catalog.readiness import validate_catalog_ready
from app.semantic_catalog.retriever import SemanticRetriever
from app.sql.validator import SQLValidator

CATALOG_NOT_READY_ERROR = "Semantic catalog is not ready for query generation."


class TextToSQLEvaluator:
    def __init__(
        self,
        *,
        questions_path: Path,
        domain_filter: str | None = None,
        limit: int | None = None,
        enable_intent_enhancer: bool = False,
    ) -> None:
        self.questions_path = questions_path
        self.domain_filter = domain_filter
        self.limit = limit
        self.enable_intent_enhancer = enable_intent_enhancer

        loader = SemanticCatalogLoader(settings.metadata_path)
        self.domains = loader.load_domains()
        self.tables = loader.load_tables()
        self.relationships = loader.load_relationships()
        self.examples = loader.load_examples()
        self.parametric_mappings = loader.load_parametric_mappings()
        self.static_value_mappings = loader.load_static_value_mappings()
        self.oracle_comments = loader.load_oracle_comments()
        self.context_selector = SemanticContextSelector(ContextDirectoryLoader(settings.metadata_path))

        self.classifier = DomainClassifier()
        self.intent_enhancer = IntentEnhancer()
        self.retriever = SemanticRetriever(
            tables=self.tables,
            relationships=self.relationships,
            examples=self.examples,
            parametric_mappings=self.parametric_mappings,
            static_value_mappings=self.static_value_mappings,
            oracle_comments=self.oracle_comments,
            context_selector=self.context_selector,
        )
        self.generator = SQLGenerator()
        self.validator = SQLValidator(max_rows=settings.db_max_rows, dialect=settings.db_dialect)

    def load_questions(self) -> list[EvaluationQuestion]:
        if not self.questions_path.exists():
            return []
        data = yaml.safe_load(self.questions_path.read_text(encoding="utf-8")) or {}
        questions_raw = data.get("questions", [])
        questions = [EvaluationQuestion(**item) for item in questions_raw]

        if self.domain_filter:
            questions = [q for q in questions if q.domain == self.domain_filter]
        if self.limit is not None:
            questions = questions[: self.limit]
        return questions

    def evaluate(self) -> EvaluationReport:
        readiness = validate_catalog_ready(domains=self.domains, tables=self.tables)
        if not readiness.ready:
            failure = EvaluationFailure(
                id="catalog_readiness",
                question="",
                reason=CATALOG_NOT_READY_ERROR,
            )
            return EvaluationReport(total_questions=0, passed=0, failed=1, skipped=0, pass_rate=0.0, failures=[failure])

        questions = self.load_questions()
        report = EvaluationReport(total_questions=len(questions))

        for question in questions:
            if not question.approved:
                report.skipped += 1
                continue

            result = self._evaluate_question(question)
            if result.ok:
                report.passed += 1
                if result.success is not None:
                    report.successful_queries.append(result.success)
            else:
                report.failed += 1
                if result.failure is not None:
                    report.failures.append(result.failure)

        effective_total = max(report.total_questions - report.skipped, 0)
        report.pass_rate = 0.0 if effective_total == 0 else round((report.passed / effective_total) * 100, 2)
        return report

    def _evaluate_question(self, question: EvaluationQuestion) -> EvaluationResult:
        detected_domain: str | None = None
        retrieved_tables: list[str] = []
        raw_llm_response: str | None = None
        generated_sql: str | None = None
        validated_sql: str | None = None
        extraction_error: str | None = None
        debug_llm_prompt: str | None = None
        relationship_candidates: list[dict] = []
        relationship_candidates_review_file: str | None = None

        try:
            effective_question = question.question
            if self.enable_intent_enhancer and settings.enable_intent_enhancer:
                intent = asyncio.run(self.intent_enhancer.enhance(question.question))
                if intent.requires_user_confirmation:
                    if question.clarification_answer:
                        effective_question = self.intent_enhancer.resolve_clarification(
                            question.question,
                            intent,
                            question.clarification_answer,
                        )
                    else:
                        raise ValueError("INTENT_REQUIRES_USER_CONFIRMATION")
                else:
                    effective_question = intent.enhanced_question
            else:
                intent = None

            detected_domain = question.domain or asyncio.run(self.classifier.classify(effective_question, self.domains))
            retrieval = self.retriever.retrieve(
                domain=detected_domain,
                question=effective_question,
                resolved_lookup_values=(intent.resolved_lookup_values if intent is not None else []),
                intent_guardrails=(intent.intent_guardrails if intent is not None else []),
                unresolved_ambiguities=(intent.unresolved_ambiguities if intent is not None else []),
            )
            retrieved_tables = [table.full_name for table in retrieval.tables]

            trace = asyncio.run(self.generator.generate_with_trace(effective_question, retrieval))
            raw_llm_response = _sanitize_text(trace.raw_llm_response)
            if _include_debug_llm_prompt():
                debug_llm_prompt = _sanitize_text(trace.debug_llm_prompt)
            generated_sql = trace.extracted_sql
            extraction_error = trace.extraction_error
            if extraction_error or not generated_sql:
                raise ValueError(extraction_error or "LLM_NO_SQL_FOUND")

            if _has_unapproved_parametric_join(
                generated_sql,
                approved_parametric_mappings=retrieval.parametric_mappings,
            ):
                raise ValueError("UNAPPROVED_PARAMETRIC_JOIN")

            validated = self.validator.validate(
                generated_sql,
                allowed_tables={t.full_name for t in retrieval.tables},
                disallowed_columns=retrieval.disallowed_columns,
                approved_relationships=retrieval.relationships,
                approved_parametric_mappings=retrieval.parametric_mappings,
                resolved_lookup_values=retrieval.resolved_lookup_values,
                resolved_numeric_filters=retrieval.resolved_numeric_filters,
                detected_query_pattern=retrieval.detected_query_pattern,
            )
            validated_sql = validated.sql

            used_tables = {item.upper() for item in validated.used_tables}
            selected_columns = _extract_selected_columns(validated_sql, settings.db_dialect.value)
            normalized_selected_columns = {col.upper() for col in selected_columns}
            sql_upper = validated_sql.upper()

            missing_expected_tables = [t for t in question.expected_tables if t.upper() not in used_tables]
            forbidden_tables_found = [t for t in question.forbidden_tables if t.upper() in used_tables]

            missing_expected_columns = [
                c for c in question.expected_columns if not _has_expected_column_semantic(validated_sql, c, normalized_selected_columns)
            ]
            forbidden_columns_found = [
                c for c in question.forbidden_columns if c.upper() in normalized_selected_columns
            ]

            missing_sql_contains = [
                token for token in question.expected_sql_contains if not _sql_contains_semantic(validated_sql, token)
            ]
            forbidden_sql_tokens = list(dict.fromkeys(question.forbidden_sql_contains + question.forbidden_sql))
            forbidden_sql_found = [token for token in forbidden_sql_tokens if token.upper() in sql_upper]
            unapproved_parametric = _has_unapproved_parametric_join(
                validated_sql,
                approved_parametric_mappings=retrieval.parametric_mappings,
            )

            failed_reasons: list[str] = []
            if unapproved_parametric:
                failed_reasons.append("UNAPPROVED_PARAMETRIC_JOIN")
            if missing_expected_tables:
                failed_reasons.append("missing_expected_tables")
            if forbidden_tables_found:
                failed_reasons.append("forbidden_tables_found")
            if missing_expected_columns:
                failed_reasons.append("missing_expected_columns")
            if forbidden_columns_found:
                failed_reasons.append("forbidden_columns_found")
            if missing_sql_contains:
                failed_reasons.append("missing_expected_sql_contains")
            if forbidden_sql_found:
                failed_reasons.append("forbidden_sql_found")

            if failed_reasons:
                return EvaluationResult(
                    ok=False,
                    failure=EvaluationFailure(
                        id=question.id,
                        question=question.question,
                        reason=", ".join(failed_reasons),
                        detected_domain=detected_domain,
                        retrieved_tables=retrieved_tables,
                        raw_llm_response=raw_llm_response,
                        debug_llm_prompt=debug_llm_prompt,
                        extraction_error=extraction_error,
                        generated_sql=generated_sql,
                        validated_sql=validated_sql,
                        missing_expected_tables=missing_expected_tables,
                        forbidden_tables_found=forbidden_tables_found,
                        missing_expected_columns=missing_expected_columns,
                        forbidden_columns_found=forbidden_columns_found,
                        forbidden_sql_found=forbidden_sql_found,
                        relationship_candidates=relationship_candidates,
                        relationship_candidates_review_file=relationship_candidates_review_file,
                    ),
                )
            return EvaluationResult(
                ok=True,
                success=EvaluationSuccess(
                    id=question.id,
                    question=question.question,
                    detected_domain=detected_domain,
                    retrieved_tables=retrieved_tables,
                    raw_llm_response=raw_llm_response,
                    debug_llm_prompt=debug_llm_prompt,
                    generated_sql=generated_sql,
                    validated_sql=validated_sql,
                ),
            )
        except Exception as exc:
            if getattr(exc, "error_code", "") == "UNAPPROVED_JOIN_PATH" and getattr(exc, "candidates", None):
                write_result = record_relationship_candidates(
                    exc.candidates,
                    question=question.question,
                    blocked_reason=getattr(exc, "error_code", "UNAPPROVED_JOIN_PATH"),
                )
                relationship_candidates = [item.model_dump(mode="json") for item in write_result.candidates]
                relationship_candidates_review_file = write_result.review_path
            return EvaluationResult(
                ok=False,
                failure=EvaluationFailure(
                    id=question.id,
                    question=question.question,
                    reason=str(exc),
                    detected_domain=detected_domain,
                    retrieved_tables=retrieved_tables,
                    raw_llm_response=raw_llm_response,
                    debug_llm_prompt=debug_llm_prompt,
                    extraction_error=extraction_error,
                    validation_errors=[str(exc)] if generated_sql else [],
                    generated_sql=generated_sql,
                    validated_sql=validated_sql,
                    relationship_candidates=relationship_candidates,
                    relationship_candidates_review_file=relationship_candidates_review_file,
                ),
            )


def _extract_selected_columns(sql: str, dialect: str) -> set[str]:
    selected: set[str] = set()
    statements = parse(sql, read=dialect)
    if not statements:
        return selected
    statement = statements[0]
    if not isinstance(statement, exp.Select):
        return selected

    for expr_node in statement.expressions or []:
        for col in expr_node.find_all(exp.Column):
            column_name = col.name
            if not column_name:
                continue
            selected.add(column_name)
            if col.table:
                selected.add(f"{col.table}.{column_name}")
    return selected


def _sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value
    for secret in (
        settings.openrouter_api_key,
        settings.openrouter_proxy_user,
        settings.openrouter_proxy_password,
    ):
        if secret:
            clean = clean.replace(secret, "***")
    return clean


def _sql_contains_semantic(sql: str, expected_token: str) -> bool:
    token_upper = expected_token.upper()
    sql_upper = sql.upper()
    if token_upper in sql_upper:
        return True

    statements = parse(sql, read=settings.db_dialect.value)
    if not statements or not isinstance(statements[0], exp.Select):
        return False
    statement = statements[0]
    alias_map = _table_alias_map(statement)

    # Alias-aware support for patterns like: SAC.MULTITABLA.TABLA = 'CLI_ESTADO'
    if "=" in expected_token and "." in expected_token:
        left_raw, right_raw = [p.strip() for p in expected_token.split("=", 1)]
        left_raw_upper = left_raw.upper()
        right_raw_upper = right_raw.upper()
        if left_raw_upper.count(".") >= 2:
            parts = left_raw_upper.split(".")
            table_full = ".".join(parts[:-1])
            column_name = parts[-1]
            alias_candidates = [alias for alias, table in alias_map.items() if table.upper() == table_full]
            alias_candidates.append(table_full)
            alias_candidates = list(dict.fromkeys(alias_candidates))

            for where_node in statement.find_all(exp.Where):
                for eq_node in where_node.find_all(exp.EQ):
                    left_expr = eq_node.left.sql(dialect=settings.db_dialect.value).upper()
                    right_expr = eq_node.right.sql(dialect=settings.db_dialect.value).upper()
                    for alias in alias_candidates:
                        if left_expr == f"{alias}.{column_name}" and _normalize_sql_literal(right_expr) == _normalize_sql_literal(right_raw_upper):
                            return True
                        if left_expr == f'"{alias}"."{column_name}"' and _normalize_sql_literal(right_expr) == _normalize_sql_literal(right_raw_upper):
                            return True
    if "=" in expected_token:
        if _matches_semantic_equality(statement, expected_token):
            return True
    return False


def _matches_semantic_equality(statement: exp.Select, expected_token: str) -> bool:
    left_raw, right_raw = [p.strip() for p in expected_token.split("=", 1)]
    left_norm = _normalize_expr_for_text_compare(left_raw)
    right_norm = _normalize_expr_for_text_compare(right_raw)
    for where_node in statement.find_all(exp.Where):
        for eq_node in where_node.find_all(exp.EQ):
            left_expr = eq_node.left.sql(dialect=settings.db_dialect.value)
            right_expr = eq_node.right.sql(dialect=settings.db_dialect.value)
            eq_left = _normalize_expr_for_text_compare(left_expr)
            eq_right = _normalize_expr_for_text_compare(right_expr)
            if (eq_left == left_norm and eq_right == right_norm) or (eq_left == right_norm and eq_right == left_norm):
                return True
    return False


def _normalize_expr_for_text_compare(value: str) -> str:
    normalized = value.strip().upper().replace('"', "")
    while normalized.startswith("UPPER(") and normalized.endswith(")"):
        normalized = normalized[6:-1].strip()
    while normalized.startswith("TRIM(") and normalized.endswith(")"):
        normalized = normalized[5:-1].strip()
    return normalized.strip().strip("'")


def _table_alias_map(statement: exp.Select) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for table in statement.find_all(exp.Table):
        if table.db:
            table_name = f"{table.db}.{table.name}".upper()
        else:
            table_name = table.name.upper()
        alias = (table.alias or table.name).upper()
        mapping[alias] = table_name
        mapping[table_name] = table_name
    return mapping


def _has_unapproved_parametric_join(sql: str, approved_parametric_mappings: list) -> bool:
    statements = parse(sql, read=settings.db_dialect.value)
    if not statements or not isinstance(statements[0], exp.Select):
        return False
    statement = statements[0]
    alias_map = _table_alias_map(statement)

    approved_pairs: set[tuple[str, str, str, str]] = set()
    for rel in approved_parametric_mappings:
        source_table = _pm_value(rel, "source_table")
        source_column = _pm_value(rel, "source_column")
        lookup_table = _pm_value(rel, "lookup_table")
        lookup_key = _pm_value(rel, "lookup_key")
        if not source_table or not source_column or not lookup_table or not lookup_key:
            continue
        approved_pairs.add(
            (
                source_table.upper(),
                source_column.upper(),
                lookup_table.upper(),
                lookup_key.upper(),
            )
        )
        approved_pairs.add(
            (
                lookup_table.upper(),
                lookup_key.upper(),
                source_table.upper(),
                source_column.upper(),
            )
        )

    for eq_node in statement.find_all(exp.EQ):
        if not isinstance(eq_node.left, exp.Column) or not isinstance(eq_node.right, exp.Column):
            continue
        left = eq_node.left
        right = eq_node.right
        left_table = alias_map.get((left.table or "").upper(), (left.table or "").upper())
        right_table = alias_map.get((right.table or "").upper(), (right.table or "").upper())
        left_col = (left.name or "").upper()
        right_col = (right.name or "").upper()
        if not left_table or not right_table or not left_col or not right_col:
            continue

        involves_multitabla = left_table.endswith(".MULTITABLA") or right_table.endswith(".MULTITABLA")
        if not involves_multitabla:
            continue
        pair = (left_table.upper(), left_col, right_table.upper(), right_col)
        if pair not in approved_pairs:
            return True
    return False


def _normalize_sql_literal(value: str) -> str:
    return value.strip().strip('"').strip("'").upper()


def _has_expected_column_semantic(sql: str, expected_column: str, normalized_selected_columns: set[str]) -> bool:
    expected_upper = expected_column.upper()
    if expected_upper in normalized_selected_columns:
        return True

    if "." not in expected_upper:
        return False

    parts = expected_upper.split(".")
    if len(parts) < 2:
        return False
    table_full = ".".join(parts[:-1])
    col_name = parts[-1]

    statements = parse(sql, read=settings.db_dialect.value)
    if not statements or not isinstance(statements[0], exp.Select):
        return False
    alias_map = _table_alias_map(statements[0])
    alias_candidates = [
        alias
        for alias, table in alias_map.items()
        if table.upper() == table_full or table.upper().endswith(f".{table_full}")
    ]
    alias_candidates.append(table_full)
    for alias in dict.fromkeys(alias_candidates):
        if f"{alias}.{col_name}" in normalized_selected_columns:
            return True
    return False


def _pm_value(item: object, field: str) -> str:
    if isinstance(item, dict):
        value = item.get(field)
    else:
        value = getattr(item, field, None)
    return str(value) if value is not None else ""


def _include_debug_llm_prompt() -> bool:
    return bool(settings.query_include_llm_prompt_in_debug) and settings.app_env.strip().lower() == "development"
