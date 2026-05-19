from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import re
from dataclasses import dataclass

from app.context_selector.models import DirectoryEntry
from app.core.config import settings
from app.llm.openrouter_client import OpenRouterClient


@dataclass
class TableSelectionResult:
    selected_tables: list[str]
    reason: str
    confidence: float
    used_fallback: bool = False


def _build_prompt(question: str, table_directory: list[DirectoryEntry]) -> str:
    compact = []
    for entry in table_directory:
        compact.append(
            {
                "table": entry.table,
                "domain": entry.domain,
                "short_description": entry.short_description,
                "keywords": entry.keywords,
                "business_terms": entry.business_terms,
                "allowed_for_query": entry.allowed_for_query,
            }
        )
    return (
        "Selecciona tablas candidatas para Text-to-SQL.\n"
        "Responde SOLO JSON estricto con formato:\n"
        "{\n"
        '  "selected_tables": ["SCHEMA.TABLE"],\n'
        '  "reason": "...",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        f"Pregunta original:\n{question}\n\n"
        f"Directorio de tablas:\n{json.dumps(compact, ensure_ascii=False)}"
    )


def _extract_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None

    code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    candidates = code_blocks + [raw]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(candidate[start : end + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    return None


def _validate_selection(data: dict, table_directory: list[DirectoryEntry]) -> TableSelectionResult:
    allowed_entries = {e.table: e for e in table_directory}
    selected = data.get("selected_tables", [])
    if not isinstance(selected, list):
        selected = []

    normalized = []
    for item in selected:
        table = str(item).strip().upper()
        if table in allowed_entries and allowed_entries[table].allowed_for_query:
            normalized.append(table)

    normalized = list(dict.fromkeys(normalized))[: settings.max_tables_in_sql_context]
    reason = str(data.get("reason", "")).strip()
    confidence_raw = data.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return TableSelectionResult(selected_tables=normalized, reason=reason, confidence=confidence)


def select_tables_with_llm(
    question: str,
    table_directory: list[DirectoryEntry],
    fallback_tables: list[str],
    client: OpenRouterClient | None = None,
) -> TableSelectionResult:
    local_fallback = list(dict.fromkeys([t.upper() for t in fallback_tables]))[: settings.max_tables_in_sql_context]
    if not settings.use_llm_table_selector:
        return TableSelectionResult(local_fallback, "LLM table selector disabled", 0.0, used_fallback=True)

    model_client = client or OpenRouterClient()
    prompt = _build_prompt(question, table_directory)

    async def _run_selection_call() -> str:
        return await asyncio.wait_for(
            model_client.chat_completion(
                model=settings.openrouter_model_classifier,
                system_prompt="Selector de tablas para contexto SQL. Responde JSON estricto.",
                user_prompt=prompt,
            ),
            timeout=settings.table_selector_timeout_seconds,
        )

    try:
        try:
            asyncio.get_running_loop()
            has_running_loop = True
        except RuntimeError:
            has_running_loop = False

        if has_running_loop:
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(lambda: asyncio.run(_run_selection_call())).result()
        else:
            response = asyncio.run(_run_selection_call())
        parsed = _extract_json_object(response)
        if not parsed:
            return TableSelectionResult(local_fallback, "Invalid JSON from LLM selector", 0.0, used_fallback=True)

        result = _validate_selection(parsed, table_directory)
        if not result.selected_tables or result.confidence < settings.table_selector_min_confidence:
            return TableSelectionResult(local_fallback, result.reason or "Low confidence", result.confidence, used_fallback=True)
        return result
    except Exception:
        return TableSelectionResult(local_fallback, "LLM selector fallback due to error", 0.0, used_fallback=True)
