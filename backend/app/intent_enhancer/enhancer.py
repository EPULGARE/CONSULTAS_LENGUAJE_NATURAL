from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.conversation_state.resolver import looks_like_clarification_answer
from app.core.config import settings
from app.intent_enhancer.models import EnhancedIntentResult
from app.intent_enhancer.prompts import INTENT_ENHANCER_SYSTEM_PROMPT, build_intent_enhancer_user_prompt
from app.llm.openrouter_client import OpenRouterClient
from app.query_patterns import detect_query_pattern
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_catalog.models import ResolvedLookupValue
from app.semantic_normalization import SemanticNormalizer
from app.semantic_normalization.models import SemanticNormalizationResult
from app.semantic_normalization.rules import append_hint, contains_phrase, normalize_text


class IntentEnhancer:
    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()
        self.loader = SemanticCatalogLoader(settings.metadata_path)
        self.normalizer = SemanticNormalizer()

    async def enhance(self, question: str) -> EnhancedIntentResult:
        normalization = self.normalizer.normalize(question)
        normalization = self._apply_ambiguity_rules_locally(question, normalization)
        raw = await self.client.chat_completion(
            model=settings.intent_enhancer_model,
            system_prompt=INTENT_ENHANCER_SYSTEM_PROMPT,
            user_prompt=build_intent_enhancer_user_prompt(normalization.normalized_question),
        )
        payload = _parse_response(raw)
        result = _build_result(original_question=question, payload=payload, normalization=normalization)
        return self._apply_governed_rules(result, normalization=normalization)

    def looks_like_clarification_answer(self, text: str) -> bool:
        return looks_like_clarification_answer(text)

    def resolve_clarification(self, original_question: str, intent_result: EnhancedIntentResult, answer: str) -> str:
        normalized_answer = (answer or "").strip().lower()
        base = intent_result.enhanced_question or original_question
        unresolved = [item.lower() for item in (intent_result.unresolved_ambiguities or [])]
        has_active_ambiguity = any("activos => cliente o medidor" in item for item in unresolved)
        has_connected_ambiguity = any("conectados => cliente o medidor" in item for item in unresolved)
        if has_connected_ambiguity:
            if "clientes" in normalized_answer or "cliente" in normalized_answer:
                self._record_ambiguity_learning("conectados", "clientes")
                return (
                    f"{base}. Interpretar conectados como clientes activos "
                    "(estado cliente activo usando mapping aprobado CLIENTES.ESTADO_CLIENTE -> MULTITABLA CLI_ESTADO DESCRIPCION='Activo')."
                )
            if "medidores" in normalized_answer or "medidor" in normalized_answer:
                self._record_ambiguity_learning("conectados", "medidores")
                return (
                    f"{base}. Interpretar conectados como medidores instalados "
                    "(usar static mapping MEDIDORES.ESTADO='I')."
                )
        if not has_active_ambiguity:
            return base
        if "clientes" in normalized_answer or "cliente" in normalized_answer:
            self._record_ambiguity_learning("activos", "clientes")
            return (
                f"{base}. Interpretar activos como clientes activos "
                "(estado cliente activo usando mapping aprobado CLIENTES.ESTADO_CLIENTE -> MULTITABLA CLI_ESTADO DESCRIPCION='Activo')."
            )
        if "medidores" in normalized_answer or "medidor" in normalized_answer:
            self._record_ambiguity_learning("activos", "medidores")
            return (
                f"{base}. Interpretar activos como medidores instalados "
                "(usar static mapping MEDIDORES.ESTADO='I')."
            )
        return base

    def _apply_ambiguity_rules_locally(
        self,
        question: str,
        normalization: SemanticNormalizationResult,
    ) -> SemanticNormalizationResult:
        q = f" {question.lower()} "
        rules = self.loader.load_ambiguity_rules().get("ambiguities", [])
        unresolved = set(normalization.unresolved_ambiguities)
        for rule in rules:
            phrase = str(rule.get("phrase", "")).strip().lower()
            if not phrase or f" {phrase} " not in q:
                continue
            approved_resolution = str(rule.get("approved_resolution", "")).strip().lower()
            confidence = _clamp_float(rule.get("confidence"))
            requires_confirmation = bool(rule.get("requires_confirmation", False))
            if phrase == "retirados":
                unresolved.discard("retirados => resolver")
                continue
            if phrase == "activos":
                if approved_resolution and confidence >= settings.intent_enhancer_auto_accept_confidence and not requires_confirmation:
                    unresolved.discard("activos => cliente o medidor")
                    if approved_resolution == "clientes":
                        normalization.resolved_filters = list(
                            dict.fromkeys(normalization.resolved_filters + ["estado cliente activo (mapping aprobado)"])
                        )
                    elif approved_resolution == "medidores":
                        normalization.resolved_filters = list(
                            dict.fromkeys(normalization.resolved_filters + ["MED.ESTADO='I'"])
                        )
                elif requires_confirmation and not self._has_governed_active_resolution(normalization):
                    unresolved.add("activos => cliente o medidor")
        normalization.unresolved_ambiguities = list(unresolved)
        return normalization

    def _has_governed_active_resolution(self, normalization: SemanticNormalizationResult) -> bool:
        if normalization.resolved_lookup_values:
            return True
        return any(
            item == "estado cliente activo (mapping aprobado)" or item.startswith("MED.ESTADO=")
            for item in normalization.resolved_filters
        )

    def _apply_governed_rules(
        self,
        result: EnhancedIntentResult,
        *,
        normalization: SemanticNormalizationResult,
    ) -> EnhancedIntentResult:
        q = normalize_text(result.original_question)
        unresolved = list(normalization.unresolved_ambiguities)
        clarifications: list[str] = []

        if "activos => cliente o medidor" in unresolved:
            clarifications.append("'activos' aplica a clientes o a medidores?")
        for item in unresolved:
            if item.startswith("lookup_value_unresolved:"):
                clarifications.append(self._build_lookup_clarification(item))

        if (contains_phrase(q, "conectado") or contains_phrase(q, "conectados")) and not normalization.resolved_filters:
            clarifications.append("'conectados' significa clientes activos o medidores activos?")

        if (contains_phrase(q, "conectado") or contains_phrase(q, "conectados")) and not normalization.resolved_filters:
            unresolved = list(dict.fromkeys([*unresolved, "conectados => cliente o medidor"]))

        result.normalized_terms = normalization.normalized_terms
        result.applied_governed_rules = normalization.applied_governed_rules
        result.skipped_normalizations = normalization.skipped_normalizations
        result.resolved_entities = normalization.resolved_entities
        result.resolved_filters = normalization.resolved_filters
        result.resolved_lookup_values = normalization.resolved_lookup_values
        result.resolved_numeric_filters = normalization.resolved_numeric_filters
        result.unresolved_ambiguities = unresolved
        result.intent_guardrails = self._build_intent_guardrails(result.original_question, unresolved)
        if result.resolved_lookup_values:
            result.detected_filters.extend(item.as_text for item in result.resolved_lookup_values)
            result.detected_filters = list(dict.fromkeys(result.detected_filters))
        if result.resolved_numeric_filters:
            result.detected_filters.extend(item.as_text for item in result.resolved_numeric_filters)
            result.detected_filters = list(dict.fromkeys(result.detected_filters))
        result.clarification_questions = list(dict.fromkeys(clarifications))
        result.ambiguity_detected = bool(result.clarification_questions)

        for item in result.resolved_lookup_values:
            result.enhanced_question = self._append_lookup_resolution_hint(result.enhanced_question, item)
        if normalization.normalized_question != result.original_question:
            suffix = normalization.normalized_question
            if suffix.lower().startswith(result.original_question.lower()):
                suffix = suffix[len(result.original_question) :].strip(" .")
            if suffix:
                result.enhanced_question = append_hint(result.enhanced_question, suffix)

        result.enhanced_question = self._preserve_structural_constraints(
            original_question=result.original_question,
            enhanced_question=result.enhanced_question,
        )

        if result.ambiguity_detected:
            result.requires_user_confirmation = True
            result.confidence = min(result.confidence, 0.89)
        else:
            result.requires_user_confirmation = False
        return result

    def _preserve_structural_constraints(self, *, original_question: str, enhanced_question: str) -> str:
        original_pattern = detect_query_pattern(original_question)
        if original_pattern is None:
            return enhanced_question

        current_pattern = detect_query_pattern(enhanced_question)
        updated = enhanced_question

        if original_pattern.operator and original_pattern.threshold is not None:
            lost_cardinality = (
                current_pattern is None
                or current_pattern.operator != original_pattern.operator
                or current_pattern.threshold != original_pattern.threshold
            )
            if lost_cardinality:
                operator_text = {
                    ">": f"mas de {original_pattern.threshold}",
                    "<": f"menos de {original_pattern.threshold}",
                    "=": f"exactamente {original_pattern.threshold}",
                }.get(original_pattern.operator, f"{original_pattern.operator} {original_pattern.threshold}")
                updated = append_hint(updated, f"Con condicion de cardinalidad: {operator_text} medidores por cliente")

        if original_pattern.type == "ranking_top_n" and original_pattern.top_n is not None:
            current_pattern = detect_query_pattern(updated)
            if current_pattern is None or current_pattern.top_n != original_pattern.top_n:
                updated = append_hint(updated, f"Limitar a top {original_pattern.top_n}")

        return updated

    def _record_ambiguity_learning(self, phrase: str, selected_resolution: str) -> None:
        metadata_root = Path(settings.metadata_path)
        target = metadata_root / "generated" / "ambiguity_learning_suggestions.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"suggestions": []}
        if target.exists():
            payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {"suggestions": []}
            if not isinstance(payload.get("suggestions"), list):
                payload["suggestions"] = []

        suggestions = payload["suggestions"]
        current = None
        for item in suggestions:
            if str(item.get("phrase", "")).lower() == phrase.lower() and str(item.get("selected_resolution", "")).lower() == selected_resolution.lower():
                current = item
                break
        if current is None:
            current = {
                "phrase": phrase,
                "selected_resolution": selected_resolution,
                "count": 0,
                "timestamp": "",
            }
            suggestions.append(current)
        current["count"] = int(current.get("count", 0)) + 1
        current["timestamp"] = datetime.now(timezone.utc).isoformat()
        target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")

    def _build_lookup_clarification(self, raw_item: str) -> str:
        _, source_table, source_column, fixed_filter_value, candidate_text, valid_values = raw_item.split(":", 5)
        values = [item for item in valid_values.split("|") if item]
        values_text = ", ".join(values) if values else "sin valores curados"
        filter_suffix = f" ({fixed_filter_value})" if fixed_filter_value else ""
        return (
            f"No pude resolver el valor '{candidate_text}' para {source_table}.{source_column}{filter_suffix}. "
            f"Valores validos: {values_text}."
        )

    def _append_lookup_resolution_hint(self, enhanced_question: str, value: ResolvedLookupValue) -> str:
        hint = (
            f"Usar valor canonico gobernado para {value.source_table}.{value.source_column}: "
            f"{value.canonical_value}"
        )
        return append_hint(enhanced_question, hint)

    def _build_intent_guardrails(self, question: str, unresolved: list[str]) -> list[str]:
        q = question.lower()
        guardrails: list[str] = []
        if ("conectado" in q or "conectados" in q) and any(
            item == "conectados => cliente o medidor" for item in unresolved
        ):
            guardrails.append(
                "No inferir 'conectado(s)' como SAC.CLIENTES.ESTADO_SUMINISTRO, "
                "SAC.CLIENTES.ESTADO_CLIENTE ni SAC.MEDIDORES.ESTADO sin aclaracion del usuario "
                "o mapping gobernado explicito."
            )
            guardrails.append(
                "Si la consulta continua sin aclaracion, omitir el filtro ambiguo 'conectado(s)' "
                "en lugar de inventar codigos o columnas."
            )
        return guardrails


def _parse_response(raw: str) -> dict:
    value = (raw or "").strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            return json.loads(value[start : end + 1])
    raise ValueError("Intent enhancer response is not valid JSON")


def _build_result(
    *,
    original_question: str,
    payload: dict,
    normalization: SemanticNormalizationResult,
) -> EnhancedIntentResult:
    confidence = _clamp_float(payload.get("confidence"))
    ambiguity = bool(payload.get("ambiguity_detected", False))
    enhanced_question = str(payload.get("enhanced_question") or normalization.normalized_question).strip() or normalization.normalized_question
    return EnhancedIntentResult(
        original_question=original_question,
        enhanced_question=_strip_sql_text(enhanced_question),
        ambiguity_detected=ambiguity,
        normalized_terms=normalization.normalized_terms,
        applied_governed_rules=normalization.applied_governed_rules,
        skipped_normalizations=normalization.skipped_normalizations,
        clarification_questions=_to_str_list(payload.get("clarification_questions")),
        detected_entities=_to_str_list(payload.get("detected_entities")),
        detected_filters=_to_str_list(payload.get("detected_filters")),
        resolved_entities=normalization.resolved_entities,
        resolved_filters=normalization.resolved_filters,
        resolved_lookup_values=normalization.resolved_lookup_values,
        resolved_numeric_filters=normalization.resolved_numeric_filters,
        intent_guardrails=[],
        unresolved_ambiguities=normalization.unresolved_ambiguities,
        confidence=confidence,
        requires_user_confirmation=ambiguity or confidence < settings.intent_enhancer_auto_accept_confidence,
    )


def _strip_sql_text(text: str) -> str:
    clean = re.sub(r"(?i)\b(select|from|join|where|group by|having|order by)\b", "", text).strip()
    return clean or text


def _to_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _clamp_float(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))
