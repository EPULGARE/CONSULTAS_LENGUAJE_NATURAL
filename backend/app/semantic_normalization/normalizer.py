from __future__ import annotations

from pathlib import Path
import re

import yaml

from app.core.config import settings
from app.llm.classifier import DomainClassifier
from app.query_patterns.detector import detect_query_pattern
from app.semantic_catalog.loader import SemanticCatalogLoader
from app.semantic_catalog.models import ApprovedLookupValuesEntry, ParametricMapping, ResolvedLookupValue, StaticValueMapping
from app.semantic_normalization.models import (
    BusinessTermRule,
    NumericEntityMapping,
    ResolvedNumericFilter,
    SemanticNormalizationResult,
)
from app.semantic_normalization.rules import (
    ACTIVE_TERMS,
    CLIENT_ENTITY_TERMS,
    CONNECTED_TERMS,
    MEDIDOR_ENTITY_TERMS,
    OPERATIONAL_VERBS,
    PROCESO_ENTITY_TERMS,
    append_hint,
    contains_phrase,
    extract_fixed_filter_value,
    normalize_text,
)


class SemanticNormalizer:
    def __init__(self) -> None:
        self.loader = SemanticCatalogLoader(settings.metadata_path)

    def normalize(self, question: str) -> SemanticNormalizationResult:
        normalized_question = normalize_text(question)
        domains = self.loader.load_domains()
        detected_domain = DomainClassifier.classify_by_vocabulary(question, domains) or DomainClassifier.classify_by_rules(question, domains)
        domain_confidence = 0.9 if detected_domain else 0.0
        resolved_entities = self._resolve_entities(normalized_question)
        parametric_mappings = self.loader.load_parametric_mappings()
        static_mappings = self.loader.load_static_value_mappings()
        numeric_entity_mappings = self.loader.load_numeric_entity_mappings()
        approved_lookup_values = self.loader.load_approved_lookup_values()

        result = SemanticNormalizationResult(
            original_question=question,
            normalized_question=question,
            detected_domain=detected_domain,
            domain_confidence=domain_confidence,
            resolved_entities=resolved_entities,
        )

        self._apply_numeric_entity_resolution(
            result,
            normalized_question,
            numeric_entity_mappings,
            parametric_mappings,
        )
        self._apply_generated_approved_lookup_values(
            result,
            normalized_question,
            resolved_entities,
            approved_lookup_values,
            parametric_mappings,
            static_mappings,
        )
        self._apply_lookup_normalization(result, normalized_question, resolved_entities, parametric_mappings, static_mappings)
        self._apply_proximity_status_resolution(result, normalized_question, parametric_mappings, static_mappings)
        self._apply_business_term_rules(result, normalized_question, resolved_entities, parametric_mappings, static_mappings)
        self._apply_static_status_rules(result, normalized_question, detected_domain, resolved_entities, static_mappings)
        self._apply_connected_guard(result, normalized_question, resolved_entities, parametric_mappings)
        self._apply_operational_ambiguity_guard(result, normalized_question)

        result.resolved_entities = list(dict.fromkeys(result.resolved_entities))
        result.resolved_filters = list(dict.fromkeys(result.resolved_filters))
        result.resolved_numeric_filters = list({
            (item.source_table, item.source_column, item.operator, item.value, item.value_type): item
            for item in result.resolved_numeric_filters
        }.values())
        result.resolved_lookup_values = list({
            (
                item.source_table,
                item.source_column,
                item.lookup_table,
                item.lookup_description,
                item.fixed_filter_value,
                item.canonical_value,
                item.code,
            ): item
            for item in result.resolved_lookup_values
        }.values())
        result.unresolved_ambiguities = list(dict.fromkeys(result.unresolved_ambiguities))
        result.normalized_terms = list(dict.fromkeys(result.normalized_terms))
        result.applied_governed_rules = list(dict.fromkeys(result.applied_governed_rules))
        result.skipped_normalizations = list(dict.fromkeys(result.skipped_normalizations))
        return result

    def _resolve_entities(self, normalized_question: str) -> list[str]:
        resolved_entities: list[str] = []
        if any(contains_phrase(normalized_question, token) for token in CLIENT_ENTITY_TERMS):
            resolved_entities.append("clientes")
        if any(contains_phrase(normalized_question, token) for token in MEDIDOR_ENTITY_TERMS):
            resolved_entities.append("medidores")
        if any(contains_phrase(normalized_question, token) for token in PROCESO_ENTITY_TERMS):
            resolved_entities.append("procesos")
        if contains_phrase(normalized_question, "armenia"):
            resolved_entities.append("municipio Armenia")
        if contains_phrase(normalized_question, "calarca"):
            resolved_entities.append("municipio Calarca")
        if contains_phrase(normalized_question, "quindio"):
            resolved_entities.append("departamento Quindio")
        return resolved_entities

    def _apply_proximity_status_resolution(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        parametric_mappings: list[ParametricMapping],
        static_mappings: list[StaticValueMapping],
    ) -> None:
        if any(contains_phrase(normalized_question, verb) for verb in OPERATIONAL_VERBS):
            return

        approved_map = {
            (mapping.source_table.upper(), mapping.source_column.upper()): mapping
            for mapping in parametric_mappings
        }
        medidores_estado = next(
            (m for m in static_mappings if m.table.upper() == "SAC.MEDIDORES" and m.column.upper() == "ESTADO"),
            None,
        )

        if self._has_entity_adjective_proximity(
            normalized_question,
            entity_terms=("cliente", "clientes", "abonado", "abonados"),
            adjective_terms=("activo", "activos"),
        ):
            self._append_client_estado_activo_resolution(result, approved_map, matched_synonym="activos")
        elif self._has_user_active_context_resolution_candidate(normalized_question, result):
            self._append_client_estado_activo_resolution(result, approved_map, matched_synonym="activos")

        if self._has_entity_adjective_proximity(
            normalized_question,
            entity_terms=("medidor", "medidores", "contador", "contadores"),
            adjective_terms=("activo", "activos", "instalado", "instalados", "instalada", "instaladas"),
        ) and medidores_estado is not None:
            self._append_static_mapping_resolution(
                result=result,
                normalized_question=normalized_question,
                mapping=medidores_estado,
                preferred_code="I",
                matched_label="activos",
            )

        if self._has_entity_adjective_proximity(
            normalized_question,
            entity_terms=("medidor", "medidores", "contador", "contadores"),
            adjective_terms=("retirado", "retirados", "retirada", "retiradas"),
        ) and medidores_estado is not None:
            self._append_static_mapping_resolution(
                result=result,
                normalized_question=normalized_question,
                mapping=medidores_estado,
                preferred_code="R",
                matched_label="retirados",
            )

    def _apply_numeric_entity_resolution(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        numeric_entity_mappings: list[NumericEntityMapping],
        parametric_mappings: list[ParametricMapping],
    ) -> None:
        approved_map = {
            (mapping.source_table.upper(), mapping.source_column.upper()): mapping
            for mapping in parametric_mappings
        }
        for entity_mapping in numeric_entity_mappings:
            explicit_resolved = self._resolve_explicit_numeric_column(
                result=result,
                normalized_question=normalized_question,
                entity_mapping=entity_mapping,
                approved_map=approved_map,
            )
            if explicit_resolved:
                continue
            resolved = self._resolve_default_numeric_entity_code(
                normalized_question=normalized_question,
                entity_mapping=entity_mapping,
            )
            if resolved is None:
                continue
            self._append_numeric_filter_resolution(
                result=result,
                resolved=resolved,
                approved_map=approved_map,
            )

    def _apply_lookup_normalization(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        resolved_entities: list[str],
        parametric_mappings: list[ParametricMapping],
        static_mappings: list[StaticValueMapping],
    ) -> None:
        approved_by_key = {
            (mapping.source_table.upper(), mapping.source_column.upper()): mapping
            for mapping in parametric_mappings
        }
        static_by_key = {(mapping.table.upper(), mapping.column.upper()) for mapping in static_mappings}

        for rule in self.loader.load_lookup_value_normalizations():
            key = (rule.source_table.upper(), rule.source_column.upper())
            mapping = approved_by_key.get(key)
            if mapping is None or key in static_by_key:
                continue
            if self._already_has_lookup_resolution(result, rule.source_table, rule.source_column):
                continue
            candidate_phrases = []
            for canonical_value, details in rule.canonical_values.items():
                candidate_phrases.append(canonical_value)
                candidate_phrases.extend(details.synonyms or [])
            if not self._lookup_rule_applies(
                normalized_question,
                rule.source_table,
                rule.source_column,
                resolved_entities,
                candidate_phrases,
            ):
                continue

            matches: dict[str, str] = {}
            for canonical_value, details in rule.canonical_values.items():
                candidates = [canonical_value, *(details.synonyms or [])]
                for candidate in candidates:
                    if contains_phrase(normalized_question, candidate):
                        matches.setdefault(canonical_value, candidate)
                        break

            if len(matches) == 1:
                canonical_value, matched_synonym = next(iter(matches.items()))
                resolved_lookup = ResolvedLookupValue(
                    source_table=mapping.source_table,
                    source_column=mapping.source_column,
                    lookup_table=mapping.lookup_table,
                    lookup_description=mapping.lookup_description,
                    fixed_filter_value=rule.fixed_filter_value,
                    canonical_value=canonical_value,
                    matched_synonym=matched_synonym,
                    valid_values=list(rule.canonical_values.keys()),
                )
                result.resolved_lookup_values.append(resolved_lookup)
                result.resolved_filters.append(resolved_lookup.as_text)
                result.normalized_terms.append(f"{matched_synonym} -> {canonical_value}")
                result.applied_governed_rules.append(
                    f"{mapping.source_table}.{mapping.source_column} -> {rule.fixed_filter_value}='{canonical_value}'"
                )
                result.normalized_question = append_hint(
                    result.normalized_question,
                    f"Usar valor canonico gobernado para {mapping.source_table}.{mapping.source_column}: {canonical_value}",
                )
                continue

            candidate_text = self._extract_lookup_candidate(normalized_question, rule.source_column)
            if candidate_text:
                result.unresolved_ambiguities.append(
                    "lookup_value_unresolved:"
                    f"{rule.source_table}:{rule.source_column}:{rule.fixed_filter_value}:{candidate_text}:"
                    f"{'|'.join(rule.canonical_values.keys())}"
                )

    def _apply_generated_approved_lookup_values(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        resolved_entities: list[str],
        approved_lookup_values: list[ApprovedLookupValuesEntry],
        parametric_mappings: list[ParametricMapping],
        static_mappings: list[StaticValueMapping],
    ) -> None:
        if not approved_lookup_values:
            return
        approved_by_key = {
            (mapping.source_table.upper(), mapping.source_column.upper()): mapping
            for mapping in parametric_mappings
        }
        static_by_key = {(mapping.table.upper(), mapping.column.upper()) for mapping in static_mappings}
        matches: list[tuple[ApprovedLookupValuesEntry, object, str]] = []

        for entry in approved_lookup_values:
            key = (entry.source_table.upper(), entry.source_column.upper())
            mapping = approved_by_key.get(key)
            if mapping is None or key in static_by_key:
                continue
            if self._already_has_lookup_resolution(result, entry.source_table, entry.source_column):
                continue
            candidate_phrases: list[str] = []
            for value in entry.values:
                candidate_phrases.append(value.description)
                candidate_phrases.extend(value.synonyms or [])
            if not self._lookup_rule_applies(
                normalized_question,
                entry.source_table,
                entry.source_column,
                resolved_entities,
                candidate_phrases,
            ):
                continue
            for value in entry.values:
                matched = self._match_approved_lookup_value(normalized_question, value)
                if matched:
                    matches.append((entry, value, matched))

        if not matches:
            return

        unique_keys = {
            (
                entry.source_table.upper(),
                entry.source_column.upper(),
                value.code,
                value.description,
                entry.fixed_filter_value.upper(),
            )
            for entry, value, _matched in matches
        }
        if len(unique_keys) == 1:
            entry, value, matched = matches[0]
            resolved_lookup = ResolvedLookupValue(
                source_table=entry.source_table,
                source_column=entry.source_column,
                lookup_table=entry.lookup_table,
                lookup_description=entry.lookup_description,
                fixed_filter_value=entry.fixed_filter_value,
                canonical_value=value.description,
                matched_synonym=matched,
                code=value.code,
                resolution_source="approved_lookup_values",
                valid_values=[item.description for item in entry.values],
            )
            result.resolved_lookup_values.append(resolved_lookup)
            result.resolved_filters.append(resolved_lookup.as_text)
            result.normalized_terms.append(f"{matched} -> {value.description}")
            result.applied_governed_rules.append(
                f"{entry.source_table}.{entry.source_column} -> {entry.fixed_filter_value}='{value.description}'"
            )
            result.normalized_question = append_hint(
                result.normalized_question,
                f"Usar valor canonico gobernado para {entry.source_table}.{entry.source_column}: {value.description}",
            )
            return

        matched_descriptions = sorted({value.description for _entry, value, _matched in matches})
        if matched_descriptions:
            result.unresolved_ambiguities.append(
                "approved_lookup_value_ambiguous:"
                + "|".join(matched_descriptions)
            )

    def _lookup_rule_applies(
        self,
        normalized_question: str,
        source_table: str,
        source_column: str,
        resolved_entities: list[str],
        candidate_phrases: object,
    ) -> bool:
        table_token = source_table.split(".")[-1].lower()
        singular_table = table_token[:-1] if table_token.endswith("s") else table_token
        entity_tokens = {normalize_text(item) for item in resolved_entities}
        table_mentioned = (
            contains_phrase(normalized_question, table_token)
            or contains_phrase(normalized_question, singular_table)
            or table_token in entity_tokens
            or singular_table in entity_tokens
        )
        if not table_mentioned:
            return False
        column_tokens = [part for part in source_column.lower().split("_") if part]
        if any(contains_phrase(normalized_question, token) for token in column_tokens):
            return True
        return any(contains_phrase(normalized_question, value) for value in candidate_phrases)

    def _match_approved_lookup_value(self, normalized_question: str, value: object) -> str | None:
        candidates = [getattr(value, "description", ""), getattr(value, "normalized_description", "")]
        candidates.extend(getattr(value, "synonyms", []) or [])
        for candidate in candidates:
            normalized_candidate = normalize_text(candidate)
            if len(normalized_candidate.split()) < 2:
                continue
            if candidate and contains_phrase(normalized_question, candidate):
                return normalize_text(candidate)
        return None

    def _apply_business_term_rules(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        resolved_entities: list[str],
        parametric_mappings: list[ParametricMapping],
        static_mappings: list[StaticValueMapping],
    ) -> None:
        rules = self._load_business_term_rules()
        approved_map = {
            (mapping.source_table.upper(), mapping.source_column.upper()): mapping
            for mapping in parametric_mappings
        }
        has_medidores_static_estado = any(
            mapping.table.upper() == "SAC.MEDIDORES" and mapping.column.upper() == "ESTADO"
            for mapping in static_mappings
        )
        has_pattern = detect_query_pattern(normalized_question) is not None

        for rule in rules:
            matched_synonym = next(
                (syn for syn in rule.synonyms if contains_phrase(normalized_question, syn)),
                None,
            )
            if matched_synonym is None:
                continue
            if rule.applies_to_domains and result.detected_domain and result.detected_domain not in rule.applies_to_domains:
                continue
            if rule.entity_terms and not any(contains_phrase(normalized_question, term) for term in rule.entity_terms):
                continue
            if any(contains_phrase(normalized_question, verb) for verb in (rule.operational_verbs or OPERATIONAL_VERBS)):
                result.unresolved_ambiguities.append("activos => cliente o medidor")
                result.skipped_normalizations.append(f"{matched_synonym} (operational_context)")
                continue
            if self._already_resolved_client_estado_activo(result, rule.source_table, rule.source_column, rule.canonical_value):
                continue
            if any(contains_phrase(normalized_question, token) for token in MEDIDOR_ENTITY_TERMS) and has_medidores_static_estado:
                result.unresolved_ambiguities.append("activos => cliente o medidor")
                result.skipped_normalizations.append(f"{matched_synonym} (multiple_governed_meanings)")
                continue
            mapping = approved_map.get((rule.source_table.upper(), rule.source_column.upper()))
            if mapping is None:
                result.skipped_normalizations.append(f"{matched_synonym} (missing_approved_mapping)")
                continue
            if not (result.domain_confidence >= 0.85 or has_pattern):
                result.unresolved_ambiguities.append("activos => cliente o medidor")
                result.skipped_normalizations.append(f"{matched_synonym} (low_domain_confidence)")
                continue

            fixed_filter_value = extract_fixed_filter_value(mapping.fixed_filter)
            resolved_lookup = ResolvedLookupValue(
                source_table=mapping.source_table,
                source_column=mapping.source_column,
                lookup_table=mapping.lookup_table,
                lookup_description=mapping.lookup_description,
                fixed_filter_value=fixed_filter_value,
                canonical_value=rule.canonical_value,
                matched_synonym=matched_synonym,
            )
            result.resolved_lookup_values.append(resolved_lookup)
            result.resolved_filters.append("estado cliente activo (mapping aprobado)")
            result.normalized_terms.append(f"{matched_synonym} -> {rule.canonical_term}")
            result.applied_governed_rules.append(
                f"{mapping.source_table}.{mapping.source_column} -> {fixed_filter_value}='{rule.canonical_value}'"
            )
            result.normalized_question = append_hint(
                result.normalized_question,
                (
                    f"Interpretar {matched_synonym} como {rule.canonical_term} "
                    f"(usar mapping aprobado {mapping.source_table}.{mapping.source_column} -> "
                    f"{mapping.lookup_table} {fixed_filter_value} DESCRIPCION='{rule.canonical_value}')"
                ),
            )

    def _apply_static_status_rules(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        detected_domain: str | None,
        resolved_entities: list[str],
        static_mappings: list[StaticValueMapping],
    ) -> None:
        medidores_estado = next(
            (m for m in static_mappings if m.table.upper() == "SAC.MEDIDORES" and m.column.upper() == "ESTADO"),
            None,
        )
        if medidores_estado is None:
            return
        medidor_context = detected_domain == "medidores" or "medidores" in resolved_entities or any(
            contains_phrase(normalized_question, token) for token in MEDIDOR_ENTITY_TERMS
        )
        if not medidor_context:
            return

        if any(
            contains_phrase(normalized_question, token)
            for token in ("retirado", "retirados", "retirada", "retiradas", "inactivo", "inactivos")
        ):
            self._append_static_mapping_resolution(
                result=result,
                normalized_question=normalized_question,
                mapping=medidores_estado,
                preferred_code="R",
            )
            return

        if any(
            contains_phrase(normalized_question, token)
            for token in ("activo", "activos", "instalado", "instalados", "instalada", "instaladas", "en servicio")
        ):
            self._append_static_mapping_resolution(
                result=result,
                normalized_question=normalized_question,
                mapping=medidores_estado,
                preferred_code="I",
            )
            return

        for code, value in medidores_estado.values.items():
            candidates = [value.label, *(value.synonyms or [])]
            matched = next(
                (
                    candidate
                    for candidate in candidates
                    if contains_phrase(normalized_question, candidate)
                    or self._matches_status_variant(normalized_question, candidate)
                ),
                None,
            )
            if matched is None:
                continue
            self._append_static_mapping_resolution(
                result=result,
                normalized_question=normalized_question,
                mapping=medidores_estado,
                preferred_code=code,
                matched_label=matched,
            )
            break

    def _apply_connected_guard(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
        resolved_entities: list[str],
        parametric_mappings: list[ParametricMapping],
    ) -> None:
        if not any(contains_phrase(normalized_question, token) for token in CONNECTED_TERMS):
            return
        has_supply_mapping = any(
            mapping.source_table.upper() == "SAC.CLIENTES" and mapping.source_column.upper() == "ESTADO_SUMINISTRO"
            for mapping in parametric_mappings
        )
        medidor_context = "medidores" in resolved_entities or any(
            contains_phrase(normalized_question, token) for token in MEDIDOR_ENTITY_TERMS
        )
        client_context = "clientes" in resolved_entities or any(
            contains_phrase(normalized_question, token) for token in CLIENT_ENTITY_TERMS
        )
        if has_supply_mapping and client_context and not medidor_context:
            result.skipped_normalizations.append("conectados (missing_governed_canonical_value)")
            return
        result.unresolved_ambiguities.append("conectados => cliente o medidor")
        result.skipped_normalizations.append("conectados (ambiguous)")

    def _load_business_term_rules(self) -> list[BusinessTermRule]:
        target = Path(settings.metadata_path) / "business_terms.yml"
        if not target.exists():
            return []
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return [BusinessTermRule(**item) for item in payload.get("business_terms", [])]

    def _resolve_explicit_numeric_column(
        self,
        *,
        result: SemanticNormalizationResult,
        normalized_question: str,
        entity_mapping: NumericEntityMapping,
        approved_map: dict[tuple[str, str], ParametricMapping],
    ) -> bool:
        found = False
        for explicit_rule in entity_mapping.explicit_column_terms:
            for term in explicit_rule.terms:
                match = re.search(
                    rf"\b{re.escape(normalize_text(term))}\s+"
                    rf"(?:(diferente\s+a|distinto\s+a|diferente\s+de|distinto\s+de|<>|!=|igual\s+a|=)\s+)?"
                    rf"([a-z0-9_-]*\d[a-z0-9_-]*)\b",
                    normalized_question,
                )
                if not match:
                    continue
                operator = self._resolve_numeric_operator(match.group(1) or "")
                resolved = ResolvedNumericFilter(
                    source_table=entity_mapping.source_table,
                    source_column=explicit_rule.source_column.upper(),
                    operator=operator,
                    value=match.group(2),
                    value_type=explicit_rule.code_type,
                    entity=entity_mapping.entity,
                    matched_text=match.group(0),
                    confidence=1.0,
                    description_lookup_available=False,
                    lookup_table="",
                    lookup_description="",
                    fixed_filter_value="",
                    forbidden_columns=[],
                )
                self._append_numeric_filter_resolution(
                    result=result,
                    resolved=resolved,
                    approved_map=approved_map,
                )
                found = True
                break
        return found

    @staticmethod
    def _resolve_numeric_operator(raw_operator: str) -> str:
        normalized = normalize_text(raw_operator)
        if normalized in {"diferente a", "distinto a", "diferente de", "distinto de", "<>", "!="}:
            return "<>"
        return "="

    def _resolve_default_numeric_entity_code(
        self,
        *,
        normalized_question: str,
        entity_mapping: NumericEntityMapping,
    ) -> ResolvedNumericFilter | None:
        if not entity_mapping.behavior.filter_by_code_when_user_provides_code:
            return None
        entity_pattern = "|".join(re.escape(normalize_text(term)) for term in entity_mapping.business_terms if term)
        if not entity_pattern:
            return None

        code_token = r"([a-z0-9_-]*\d[a-z0-9_-]*)"
        patterns = (
            rf"\b(?:{entity_pattern})\s+{code_token}\b",
            rf"\b(?:{entity_pattern})\s+(?:codigo|numero|tipo)\s+{code_token}\b",
            rf"\bcodigo\s+{code_token}\s+de\s+(?:{entity_pattern})\b",
            rf"\bnumero\s+{code_token}\s+de\s+(?:{entity_pattern})\b",
            rf"\btipo\s+{code_token}\s+de\s+(?:{entity_pattern})\b",
        )
        match = None
        for pattern in patterns:
            match = re.search(pattern, normalized_question)
            if match:
                break
        if match is None:
            return None

        value = match.group(1)
        return ResolvedNumericFilter(
            source_table=entity_mapping.source_table,
            source_column=entity_mapping.default_code_column.upper(),
            operator="=",
            value=value,
            value_type=entity_mapping.code_type,
            entity=entity_mapping.entity,
            matched_text=match.group(0),
            confidence=1.0,
            description_lookup_available=False,
            lookup_table="",
            lookup_description="",
            fixed_filter_value="",
            forbidden_columns=[item.upper() for item in entity_mapping.forbidden_columns_for_entity_code],
        )

    def _append_numeric_filter_resolution(
        self,
        *,
        result: SemanticNormalizationResult,
        resolved: ResolvedNumericFilter,
        approved_map: dict[tuple[str, str], ParametricMapping],
    ) -> None:
        if any(
            item.source_table.upper() == resolved.source_table.upper()
            and item.source_column.upper() == resolved.source_column.upper()
            and item.value == resolved.value
            for item in result.resolved_numeric_filters
        ):
            return
        description_mapping = approved_map.get((resolved.source_table.upper(), resolved.source_column.upper()))
        if description_mapping is not None:
            resolved.description_lookup_available = True
            resolved.lookup_table = description_mapping.lookup_table
            resolved.lookup_description = description_mapping.lookup_description
            resolved.fixed_filter_value = extract_fixed_filter_value(description_mapping.fixed_filter)
        result.resolved_numeric_filters.append(resolved)
        result.resolved_filters.append(resolved.sql_predicate)
        result.normalized_terms.append(f"{resolved.matched_text} -> {resolved.source_column}")
        result.applied_governed_rules.append(resolved.sql_predicate)
        result.normalized_question = append_hint(
            result.normalized_question,
            f"Usar filtro numerico gobernado {resolved.sql_predicate}",
        )
        if resolved.forbidden_columns:
            forbidden_text = ", ".join(resolved.forbidden_columns)
            result.normalized_question = append_hint(
                result.normalized_question,
                f"No reinterpretar {resolved.value} en columnas alternativas: {forbidden_text}",
            )

    def _apply_operational_ambiguity_guard(
        self,
        result: SemanticNormalizationResult,
        normalized_question: str,
    ) -> None:
        has_active_term = any(contains_phrase(normalized_question, token) for token in ACTIVE_TERMS)
        has_operational_verb = any(contains_phrase(normalized_question, verb) for verb in OPERATIONAL_VERBS)
        if not has_active_term or self._already_has_status_resolution(result):
            return
        result.unresolved_ambiguities.append("activos => cliente o medidor")
        if has_operational_verb:
            result.skipped_normalizations.append("activos (operational_context)")

    def _extract_lookup_candidate(self, normalized_question: str, source_column: str) -> str:
        tokens = [part for part in source_column.lower().split("_") if part]
        for token in tokens:
            match = re.search(
                rf"\b{re.escape(token)}\b\s+(?:de\s+)?([a-z0-9 ]{{2,40}}?)(?:\b(con|de|del|por|para|y|o|que|hay|tienen|tenga)\b|$)",
                normalized_question,
            )
            if not match:
                continue
            candidate = " ".join(match.group(1).split())
            if candidate:
                return candidate
        return ""

    def _append_static_mapping_resolution(
        self,
        *,
        result: SemanticNormalizationResult,
        normalized_question: str,
        mapping: StaticValueMapping,
        preferred_code: str,
        matched_label: str | None = None,
    ) -> None:
        if f"MED.ESTADO='{preferred_code}'" in result.resolved_filters:
            return
        value = mapping.values.get(preferred_code)
        if value is None:
            return
        matched = matched_label or value.label
        result.resolved_filters.append(f"MED.ESTADO='{preferred_code}'")
        result.normalized_terms.append(f"{matched} -> {value.label}")
        result.applied_governed_rules.append(f"{mapping.table}.{mapping.column}='{preferred_code}'")
        result.normalized_question = append_hint(
            result.normalized_question,
            f"Interpretar {matched} como medidores con estado {value.label} (usar static mapping {mapping.table}.{mapping.column}='{preferred_code}')",
        )

    def _append_client_estado_activo_resolution(
        self,
        result: SemanticNormalizationResult,
        approved_map: dict[tuple[str, str], ParametricMapping],
        *,
        matched_synonym: str,
    ) -> None:
        mapping = approved_map.get(("SAC.CLIENTES", "ESTADO_CLIENTE"))
        if mapping is None or self._already_resolved_client_estado_activo(result, mapping.source_table, mapping.source_column, "Activo"):
            return
        fixed_filter_value = extract_fixed_filter_value(mapping.fixed_filter)
        resolved_lookup = ResolvedLookupValue(
            source_table=mapping.source_table,
            source_column=mapping.source_column,
            lookup_table=mapping.lookup_table,
            lookup_description=mapping.lookup_description,
            fixed_filter_value=fixed_filter_value,
            canonical_value="Activo",
            matched_synonym=matched_synonym,
        )
        result.resolved_lookup_values.append(resolved_lookup)
        result.resolved_filters.append("estado cliente activo (mapping aprobado)")
        result.normalized_terms.append(f"{matched_synonym} -> estado cliente activo")
        result.applied_governed_rules.append(
            f"{mapping.source_table}.{mapping.source_column} -> {fixed_filter_value}='Activo'"
        )
        result.normalized_question = append_hint(
            result.normalized_question,
            (
                f"Interpretar {matched_synonym} como estado cliente activo "
                f"(usar mapping aprobado {mapping.source_table}.{mapping.source_column} -> "
                f"{mapping.lookup_table} {fixed_filter_value} DESCRIPCION='Activo')"
            ),
        )

    def _already_resolved_client_estado_activo(
        self,
        result: SemanticNormalizationResult,
        source_table: str,
        source_column: str,
        canonical_value: str,
    ) -> bool:
        return any(
            item.source_table.upper() == source_table.upper()
            and item.source_column.upper() == source_column.upper()
            and item.canonical_value.upper() == canonical_value.upper()
            for item in result.resolved_lookup_values
        )

    def _already_has_lookup_resolution(
        self,
        result: SemanticNormalizationResult,
        source_table: str,
        source_column: str,
    ) -> bool:
        return any(
            item.source_table.upper() == source_table.upper()
            and item.source_column.upper() == source_column.upper()
            for item in result.resolved_lookup_values
        )

    def _already_has_status_resolution(self, result: SemanticNormalizationResult) -> bool:
        return bool(result.resolved_lookup_values) or any(
            item.startswith("MED.ESTADO=") or item == "estado cliente activo (mapping aprobado)"
            for item in result.resolved_filters
        )

    def _has_entity_adjective_proximity(
        self,
        normalized_question: str,
        *,
        entity_terms: tuple[str, ...],
        adjective_terms: tuple[str, ...],
    ) -> bool:
        tokens = normalized_question.split()
        for idx, token in enumerate(tokens[:-1]):
            if token not in entity_terms:
                continue
            next_token = tokens[idx + 1]
            if next_token in adjective_terms:
                return True
        return False

    def _has_user_active_context_resolution_candidate(
        self,
        normalized_question: str,
        result: SemanticNormalizationResult,
    ) -> bool:
        if not self._has_entity_adjective_window(
            normalized_question,
            entity_terms=("usuario", "usuarios"),
            adjective_terms=("activo", "activos"),
            max_gap=2,
        ):
            return False
        has_location_context = any(
            item in result.resolved_entities
            for item in ("municipio Armenia", "municipio Calarca", "departamento Quindio")
        )
        has_medidor_context = "medidores" in result.resolved_entities and any(
            contains_phrase(normalized_question, token)
            for token in ("retirado", "retirados", "retirada", "retiradas", "instalado", "instalados")
        )
        return has_location_context or has_medidor_context

    def _has_entity_adjective_window(
        self,
        normalized_question: str,
        *,
        entity_terms: tuple[str, ...],
        adjective_terms: tuple[str, ...],
        max_gap: int,
    ) -> bool:
        tokens = normalized_question.split()
        for idx, token in enumerate(tokens):
            if token not in entity_terms:
                continue
            upper_bound = min(len(tokens), idx + max_gap + 2)
            for probe in range(idx + 1, upper_bound):
                if tokens[probe] in adjective_terms:
                    return True
        return False

    def _matches_status_variant(self, normalized_question: str, candidate: str) -> bool:
        normalized_candidate = normalize_text(candidate)
        if not normalized_candidate:
            return False
        variants = {
            normalized_candidate,
            normalized_candidate.rstrip("s"),
            f"{normalized_candidate}s",
        }
        if normalized_candidate.endswith("ado"):
            variants.add(f"{normalized_candidate}s")
        if normalized_candidate.endswith("ados"):
            variants.add(normalized_candidate[:-1])
        if normalized_candidate.endswith("iva"):
            variants.add(normalized_candidate[:-1] + "o")
        if normalized_candidate.endswith("ivo"):
            variants.add(normalized_candidate[:-1] + "a")
            variants.add(f"{normalized_candidate}s")
        return any(contains_phrase(normalized_question, variant) for variant in variants if variant)
