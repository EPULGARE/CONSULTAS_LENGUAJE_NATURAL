from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings
from app.llm.openrouter_client import OpenRouterClient
from app.llm.prompts import SQL_SYSTEM_PROMPT, build_sql_user_prompt
from app.semantic_catalog.models import RetrievalResult


@dataclass
class SQLGenerationTrace:
    raw_llm_response: str
    extracted_sql: str | None
    extraction_error: str | None
    debug_llm_prompt: str | None = None


class SQLGenerator:
    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    async def generate(self, question: str, retrieval: RetrievalResult) -> str:
        trace = await self.generate_with_trace(question, retrieval)
        if trace.extracted_sql:
            return trace.extracted_sql
        raise ValueError(trace.extraction_error or "LLM_NO_SQL_FOUND")

    async def generate_with_trace(self, question: str, retrieval: RetrievalResult) -> SQLGenerationTrace:
        prompt = build_sql_user_prompt(
            question=question,
            tables=retrieval.tables,
            relationships=retrieval.relationships_text,
            examples=retrieval.examples,
            approved_parametric_mappings=retrieval.parametric_mappings,
            static_value_mappings=retrieval.static_value_mappings,
            resolved_lookup_values=retrieval.resolved_lookup_values,
            resolved_numeric_filters=retrieval.resolved_numeric_filters,
            intent_guardrails=retrieval.intent_guardrails,
            auxiliary_semantic_context=retrieval.auxiliary_semantic_context,
            detected_query_pattern=retrieval.detected_query_pattern,
        )
        raw_response = await self.client.chat_completion(
            model=settings.openrouter_model_sql,
            system_prompt=SQL_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        extracted = _extract_select_sql(raw_response)
        if extracted:
            return SQLGenerationTrace(
                raw_llm_response=raw_response,
                extracted_sql=extracted,
                extraction_error=None,
                debug_llm_prompt=prompt,
            )
        return SQLGenerationTrace(
            raw_llm_response=raw_response,
            extracted_sql=None,
            extraction_error="LLM_NO_SQL_FOUND",
            debug_llm_prompt=prompt,
        )


def _extract_select_sql(text: str) -> str | None:
    value = (text or "").strip()
    if not value:
        return None

    code_blocks = re.findall(r"```(?:sql)?\s*([\s\S]*?)```", value, flags=re.IGNORECASE)
    for block in code_blocks:
        candidate = _extract_from_free_text(block)
        if candidate:
            return candidate

    return _extract_from_free_text(value)


def _extract_from_free_text(text: str) -> str | None:
    match = re.search(r"(?is)\bselect\b[\s\S]*", text)
    if not match:
        return None
    tail = match.group(0).strip()
    statement = tail.split(";", 1)[0].strip()
    statement = re.sub(r"`{3,}$", "", statement).strip()
    if not statement.lower().startswith("select"):
        return None
    return statement
