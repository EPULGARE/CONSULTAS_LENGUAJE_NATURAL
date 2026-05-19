from __future__ import annotations

import logging

from app.context_selector.directory_loader import ContextDirectoryLoader
from app.context_selector.llm_table_selector import select_tables_with_llm
from app.context_selector.models import DirectoryEntry, SelectedTableContext, TableContext, TableSelectionDiagnostics
from app.context_selector.relationship_graph import RelationshipGraph
from app.core.config import settings
from app.query_patterns.detector import detect_query_pattern
from app.semantic_catalog.models import ParametricMapping, RelationshipMetadata

logger = logging.getLogger(__name__)


class SemanticContextSelector:
    def __init__(self, loader: ContextDirectoryLoader) -> None:
        self.loader = loader
        self.relationship_graph = RelationshipGraph(loader.metadata_path)
        self.last_selection_debug: dict = {}

    def select(
        self,
        *,
        question: str,
        domain: str,
        relationships: list[RelationshipMetadata],
        parametric_mappings: list[ParametricMapping],
        unresolved_ambiguities: list[str] | None = None,
        resolved_lookup_values: list[object] | None = None,
        resolved_numeric_filters: list[object] | None = None,
        static_mapping_columns: list[str] | None = None,
    ) -> list[SelectedTableContext]:
        all_directory = [d for d in self.loader.load_directory() if d.allowed_for_query]
        directory = [d for d in all_directory if d.domain == domain]
        if not directory:
            self.last_selection_debug = {
                "local_selected_tables": [],
                "llm_selected_tables": [],
                "final_selected_tables": [],
                "table_selection_reason": "No directory entries for domain",
                "confidence": 0.0,
                "strategy": "LOCAL_PLUS_LLM",
                "used_llm_table_selection": False,
                "local_selection_confidence": 0.0,
                "local_selection_reason": "No directory entries for domain",
                "approved_join_paths": [],
                "approved_join_edges": [],
            }
            return []

        detected_query_pattern = detect_query_pattern(question)
        ranked = self._rank_by_keywords(question, all_directory)
        domain_tables = {d.table for d in directory}
        local_selected = [entry.table for score, entry in ranked if score > 0 and entry.table in domain_tables][
            : settings.max_tables_in_sql_context
        ]
        if not local_selected:
            local_selected = [entry.table for _, entry in ranked[: settings.max_tables_in_sql_context]]

        local_selected = self._enforce_cross_domain_rules(question, local_selected, all_directory)
        local_expanded, local_table_paths, local_join_edges = self.relationship_graph.expand_tables_with_join_path(
            local_selected,
            question,
            max_hops=3,
        )
        diagnostics = self.should_skip_llm_table_selection(
            question=question,
            domain=domain,
            detected_query_pattern=detected_query_pattern,
            local_selected_tables=local_selected,
            expanded_local_tables=local_expanded,
            approved_join_paths=local_table_paths,
            join_edges=local_join_edges,
            unresolved_ambiguities=unresolved_ambiguities or [],
            parametric_mappings=parametric_mappings,
            resolved_lookup_values=resolved_lookup_values or [],
            resolved_numeric_filters=resolved_numeric_filters or [],
            static_mapping_columns=static_mapping_columns or [],
        )

        llm_selected: list[str] = []
        reason = diagnostics.local_selection_reason or "Local selector"
        confidence = diagnostics.local_selection_confidence
        used_llm_table_selection = False

        should_call_llm = (
            settings.use_llm_context_selector
            and settings.enable_llm_table_selection_fallback
            and diagnostics.strategy != "LOCAL_ONLY"
            and (self._is_uncertain(ranked) or len(local_selected) < 2 or confidence < settings.local_table_selection_confidence_threshold)
        )
        if should_call_llm:
            llm_result = select_tables_with_llm(question, all_directory, local_selected)
            llm_selected = llm_result.selected_tables
            reason = llm_result.reason
            confidence = llm_result.confidence
            used_llm_table_selection = True
            logger.info(
                "fallback_to_llm_table_selection confidence=%.2f reason=%s",
                diagnostics.local_selection_confidence,
                diagnostics.local_selection_reason,
            )
        elif diagnostics.strategy == "LOCAL_ONLY":
            logger.info(
                "llm_table_selection_skipped confidence=%.2f reason=%s",
                diagnostics.local_selection_confidence,
                diagnostics.local_selection_reason,
            )
        else:
            logger.info(
                "local_selection_confidence confidence=%.2f reason=%s",
                diagnostics.local_selection_confidence,
                diagnostics.local_selection_reason,
            )

        final_selected = self._merge_table_names(local_selected, llm_selected)
        final_selected, table_paths, join_edges = self.relationship_graph.expand_tables_with_join_path(
            final_selected, question, max_hops=3
        )

        selected_entries = [e for e in all_directory if e.table in final_selected]
        selected_entries = self._enrich_with_parametric_requirements(question, selected_entries, all_directory, parametric_mappings)

        outputs: list[SelectedTableContext] = []
        for entry in selected_entries:
            detail = self.loader.load_table_context(entry.context_path or entry.has_detailed_context_path)
            if not detail:
                continue
            cols = self._select_columns(question, detail, relationships, parametric_mappings)
            outputs.append(SelectedTableContext(table=entry.table, selected_columns=cols))

        final_tables = [o.table for o in outputs]
        self.last_selection_debug = {
            "local_selected_tables": local_selected,
            "llm_selected_tables": llm_selected,
            "final_selected_tables": final_tables,
            "table_selection_reason": reason,
            "confidence": confidence,
            "strategy": diagnostics.strategy if not used_llm_table_selection else "LOCAL_PLUS_LLM",
            "used_llm_table_selection": used_llm_table_selection,
            "local_selection_confidence": diagnostics.local_selection_confidence,
            "local_selection_reason": diagnostics.local_selection_reason,
            "approved_join_paths": [" -> ".join(path) for path in table_paths],
            "approved_join_edges": [
                (
                    f"{edge.get('from_table')}.{edge.get('from_column')} = "
                    f"{edge.get('to_table')}.{edge.get('to_column')}"
                )
                for edge in join_edges
            ],
        }
        return outputs

    def should_skip_llm_table_selection(
        self,
        *,
        question: str,
        domain: str | None,
        detected_query_pattern: object | None,
        local_selected_tables: list[str],
        expanded_local_tables: list[str],
        approved_join_paths: list[list[str]],
        join_edges: list[dict],
        unresolved_ambiguities: list[str],
        parametric_mappings: list[ParametricMapping],
        resolved_lookup_values: list[object],
        resolved_numeric_filters: list[object],
        static_mapping_columns: list[str],
    ) -> TableSelectionDiagnostics:
        has_domain = bool(domain)
        has_pattern = detected_query_pattern is not None
        has_local_tables = bool(local_selected_tables)
        no_unresolved_ambiguities = not unresolved_ambiguities
        approved_join_paths_found = bool(approved_join_paths) or len(set(expanded_local_tables or local_selected_tables)) <= 1
        join_paths_complete = self._has_complete_join_paths(
            question=question,
            expanded_local_tables=expanded_local_tables,
            approved_join_paths=approved_join_paths,
            join_edges=join_edges,
        )
        mappings_sufficient = self._has_sufficient_governed_mappings(
            question=question,
            selected_tables=expanded_local_tables or local_selected_tables,
            parametric_mappings=parametric_mappings,
            resolved_lookup_values=resolved_lookup_values,
            resolved_numeric_filters=resolved_numeric_filters,
            static_mapping_columns=static_mapping_columns,
        )

        confidence = 0.0
        reasons: list[str] = []
        if has_domain:
            confidence += 0.14
            reasons.append("detected_domain")
        if has_pattern:
            confidence += 0.18
            reasons.append("query_pattern")
        if has_local_tables:
            confidence += 0.14
            reasons.append("local_selected_tables")
        if approved_join_paths_found:
            confidence += 0.18
            reasons.append("approved_join_paths")
        if no_unresolved_ambiguities:
            confidence += 0.12
            reasons.append("no_unresolved_ambiguities")
        if mappings_sufficient:
            confidence += 0.12
            reasons.append("governed_mappings")
        if join_paths_complete:
            confidence += 0.12
            reasons.append("relationship_graph")
        confidence = max(0.0, min(1.0, confidence))

        all_conditions = all(
            [
                has_domain,
                has_pattern,
                has_local_tables,
                approved_join_paths_found,
                no_unresolved_ambiguities,
                mappings_sufficient,
                join_paths_complete,
            ]
        )
        if all_conditions and confidence >= settings.local_table_selection_confidence_threshold:
            return TableSelectionDiagnostics(
                strategy="LOCAL_ONLY",
                local_selection_confidence=confidence,
                local_selection_reason=" + ".join(reasons) or "local_evidence",
                used_llm_table_selection=False,
            )
        return TableSelectionDiagnostics(
            strategy="LOCAL_PLUS_LLM",
            local_selection_confidence=confidence,
            local_selection_reason=" + ".join(reasons) or "insufficient_local_evidence",
            used_llm_table_selection=True,
        )

    def _merge_table_names(self, local_selected: list[str], llm_selected: list[str]) -> list[str]:
        merged = list(dict.fromkeys([*local_selected, *llm_selected]))
        return merged[: settings.max_tables_in_sql_context]

    def _enforce_cross_domain_rules(self, question: str, local_selected: list[str], directory: list[DirectoryEntry]) -> list[str]:
        q = f" {question.lower()} "
        city_tokens = {" ciudad ", " municipio ", " localidad ", " población ", " poblacion ", " armenia ", " quindio "}
        user_tokens = {" usuario ", " usuarios ", " cliente ", " clientes ", " abonado ", " abonados "}
        medidor_tokens = {" medidor ", " medidores ", " contador ", " contadores "}
        has_city_intent = any(token in q for token in city_tokens)
        has_user_intent = any(token in q for token in user_tokens)
        has_medidor_intent = any(token in q for token in medidor_tokens)

        municipalities = next((d.table for d in directory if d.table.upper().endswith(".MUNICIPIOS")), None)
        clientes = next((d.table for d in directory if d.table.upper().endswith(".CLIENTES")), None)
        medidores = next((d.table for d in directory if d.table.upper().endswith(".MEDIDORES")), None)

        for entry in directory:
            for kw in entry.keywords + entry.business_terms:
                kw_text = kw.lower().strip()
                if kw_text and f" {kw_text} " in q and entry.table not in local_selected:
                    local_selected.append(entry.table)

        if has_city_intent and municipalities and municipalities not in local_selected:
            local_selected.append(municipalities)
        if has_city_intent and clientes and clientes not in local_selected:
            local_selected.append(clientes)
        if has_user_intent and clientes and clientes not in local_selected:
            local_selected.append(clientes)
        if has_medidor_intent and medidores and medidores not in local_selected:
            local_selected.append(medidores)
        if has_medidor_intent and has_user_intent and clientes and clientes not in local_selected:
            local_selected.append(clientes)
        if has_medidor_intent and has_city_intent and municipalities and municipalities not in local_selected:
            local_selected.append(municipalities)

        return list(dict.fromkeys(local_selected))[: settings.max_tables_in_sql_context]

    def _enrich_with_parametric_requirements(
        self,
        question: str,
        selected: list[DirectoryEntry],
        directory: list[DirectoryEntry],
        parametric_mappings: list[ParametricMapping],
    ) -> list[DirectoryEntry]:
        q = question.lower()
        asks_estado_suministro = "estado suministro" in q or "suministro" in q
        asks_estado_facturacion = "estado facturacion" in q or "facturacion" in q
        by_table = {e.table: e for e in directory}
        selected_by_table = {e.table: e for e in selected}
        for mapping in parametric_mappings:
            if (
                mapping.source_table.upper() == "SAC.CLIENTES"
                and mapping.source_column.upper() == "ESTADO_CLIENTE"
                and (asks_estado_suministro or asks_estado_facturacion)
            ):
                continue
            source_tokens = [t for t in mapping.source_column.lower().split("_") if t]
            if any(token in q for token in source_tokens):
                if mapping.source_table in by_table:
                    selected_by_table[mapping.source_table] = by_table[mapping.source_table]
                if mapping.lookup_table in by_table:
                    selected_by_table[mapping.lookup_table] = by_table[mapping.lookup_table]
        return list(selected_by_table.values())[: settings.max_tables_in_sql_context]

    def _rank_by_keywords(self, question: str, directory: list[DirectoryEntry]) -> list[tuple[int, DirectoryEntry]]:
        q = question.lower()
        scored: list[tuple[int, DirectoryEntry]] = []
        for entry in directory:
            score = 0
            if entry.table.split(".")[-1].lower() in q:
                score += 5
            for kw in entry.keywords:
                if kw.lower() in q:
                    score += 2
            for term in entry.business_terms:
                if term.lower() in q:
                    score += 1
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _is_uncertain(self, ranked: list[tuple[int, DirectoryEntry]]) -> bool:
        if len(ranked) < 2:
            return True
        return ranked[0][0] == ranked[1][0]

    def _has_complete_join_paths(
        self,
        *,
        question: str,
        expanded_local_tables: list[str],
        approved_join_paths: list[list[str]],
        join_edges: list[dict],
    ) -> bool:
        selected_unique = list(dict.fromkeys(expanded_local_tables))
        if len(selected_unique) <= 1:
            return True
        if approved_join_paths or join_edges:
            return True
        q = question.lower()
        needs_bridge = any(token in q for token in ("municipio", "ciudad", "localidad", "armenia", "calarca", "quindio"))
        return not needs_bridge

    def _has_sufficient_governed_mappings(
        self,
        *,
        question: str,
        selected_tables: list[str],
        parametric_mappings: list[ParametricMapping],
        resolved_lookup_values: list[object],
        resolved_numeric_filters: list[object],
        static_mapping_columns: list[str],
    ) -> bool:
        q = question.lower()
        if resolved_lookup_values or resolved_numeric_filters:
            return True
        state_like_terms = (
            "estado",
            "activo",
            "activos",
            "inactivo",
            "inactivos",
            "retirado",
            "retirados",
            "conectado",
            "conectados",
            "instalado",
            "instalados",
        )
        if not any(token in q for token in state_like_terms):
            return True
        selected_upper = {table.upper() for table in selected_tables}
        has_parametric = any(mapping.source_table.upper() in selected_upper for mapping in parametric_mappings)
        static_tables = {
            ".".join(static_column.split(".")[:2]).upper()
            for static_column in static_mapping_columns
            if static_column.count(".") >= 2
        }
        has_static = bool(static_tables & selected_upper)
        return has_parametric or has_static

    def _select_columns(
        self,
        question: str,
        table_context: TableContext,
        relationships: list[RelationshipMetadata],
        parametric_mappings: list[ParametricMapping],
    ) -> list[str]:
        q = question.lower()
        detected_pattern = detect_query_pattern(question)
        asks_estado_suministro = ("estado" in q and "suministro" in q)
        asks_estado_facturacion = ("estado" in q and "facturacion" in q)
        relationship_cols = {
            rel.left_column.upper()
            for rel in relationships
            if rel.left_table.upper() == table_context.table.upper() or rel.right_table.upper() == table_context.table.upper()
        } | {
            rel.right_column.upper()
            for rel in relationships
            if rel.left_table.upper() == table_context.table.upper() or rel.right_table.upper() == table_context.table.upper()
        }
        mapping_cols = {
            pm.source_column.upper()
            for pm in parametric_mappings
            if pm.source_table.upper() == table_context.table.upper()
        } | {
            pm.lookup_key.upper()
            for pm in parametric_mappings
            if pm.lookup_table.upper() == table_context.table.upper()
        } | {
            pm.lookup_description.upper()
            for pm in parametric_mappings
            if pm.lookup_table.upper() == table_context.table.upper()
        }

        chosen: list[str] = []
        for col in table_context.columns:
            if not col.selectable or col.sensitive:
                continue
            if (
                table_context.table.upper() == "SAC.CLIENTES"
                and col.name.upper() == "ESTADO_CLIENTE"
                and (asks_estado_suministro or asks_estado_facturacion)
            ):
                continue
            if (
                table_context.table.upper().endswith(".CLIENTES")
                and col.name.upper() == "MUNICIPIO"
                and any(t in q for t in ["armenia", "ciudad", "municipio", "localidad"])
            ):
                relationship_cols.add("MUNICIPIO")
                continue

            col_name_lower = col.name.lower()
            col_name_phrase = col_name_lower.replace("_", " ")
            name_hit = col_name_lower in q or col_name_phrase in q
            normalized_synonyms = [s.lower().strip() for s in col.synonyms]
            exact_syn_hit = any(s == q or f" {s} " in f" {q} " for s in normalized_synonyms if s)
            syn_hit = any(s in q for s in normalized_synonyms if s)
            desc_hit = any(token in col.business_description.lower() for token in q.split())
            rel_hit = col.name.upper() in relationship_cols
            map_hit = col.name.upper() in mapping_cols
            semantic_estado_suministro_hit = (
                table_context.table.upper() == "SAC.CLIENTES"
                and col.name.upper() == "ESTADO_SUMINISTRO"
                and asks_estado_suministro
            )
            semantic_estado_facturacion_hit = (
                table_context.table.upper() == "SAC.CLIENTES"
                and col.name.upper() == "ESTADO_FACTURACION"
                and asks_estado_facturacion
            )
            estado_medidor_hit = (
                table_context.table.upper() == "SAC.MEDIDORES"
                and col.name.upper() == "ESTADO"
                and any(
                    token in q
                    for token in (
                        "estado",
                        "activo",
                        "activos",
                        "instalado",
                        "instalados",
                        "inactivo",
                        "inactivos",
                        "retirado",
                        "retirados",
                    )
                )
            )
            if (
                exact_syn_hit
                or name_hit
                or syn_hit
                or desc_hit
                or rel_hit
                or map_hit
                or estado_medidor_hit
                or semantic_estado_suministro_hit
                or semantic_estado_facturacion_hit
            ):
                chosen.append(col.name.upper())

        display_column = (table_context.display_column or "").upper()
        if display_column and self._should_include_display_column(
            question=question,
            table_context=table_context,
            detected_pattern=detected_pattern,
        ):
            available_columns = {col.name.upper() for col in table_context.columns if col.selectable and not col.sensitive}
            if display_column in available_columns and display_column not in chosen:
                chosen.append(display_column)

        if not chosen:
            chosen = [c.name.upper() for c in table_context.columns if c.selectable and not c.sensitive]
        return chosen[: settings.max_columns_per_table_in_sql_context]

    def _should_include_display_column(
        self,
        *,
        question: str,
        table_context: TableContext,
        detected_pattern: object | None,
    ) -> bool:
        q = question.lower()
        if detected_pattern is not None and getattr(detected_pattern, "type", "") in {
            "grouped_aggregation",
            "ranking_top_n",
            "municipality_filter",
            "descriptive_lookup",
        }:
            return True
        dimension_tokens = (" por ", " agrupad", " municipio", " ciudad", " localidad", " descripcion", " nombre ")
        if any(token in q for token in dimension_tokens):
            return True
        return table_context.table.upper().endswith(".MULTITABLA") and "estado" in q
