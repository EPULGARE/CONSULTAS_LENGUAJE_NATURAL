from __future__ import annotations
import re

from app.core.config import settings
from app.query_patterns import detect_query_pattern
from app.semantic_catalog.models import ParametricMapping, RelationshipMetadata, ResolvedLookupValue, RetrievalResult, StaticValueMapping, TableMetadata


class SemanticRetriever:
    def __init__(
        self,
        tables: list[TableMetadata],
        relationships: list[RelationshipMetadata],
        examples: dict[str, list[str]],
        parametric_mappings: list[ParametricMapping] | None = None,
        static_value_mappings: list[StaticValueMapping] | None = None,
        oracle_comments: dict | None = None,
        context_selector: object | None = None,
    ) -> None:
        self.tables = tables
        self.relationships = relationships
        self.examples = examples
        self.parametric_mappings = [
            item if isinstance(item, ParametricMapping) else ParametricMapping(**item)
            for item in (parametric_mappings or [])
        ]
        self.static_value_mappings = [
            item if isinstance(item, StaticValueMapping) else StaticValueMapping(**item)
            for item in (static_value_mappings or [])
        ]
        self.oracle_comments = oracle_comments or {}
        self.context_selector = context_selector

    def retrieve(
        self,
        *,
        domain: str,
        question: str,
        max_tables: int = 5,
        resolved_lookup_values: list[ResolvedLookupValue] | None = None,
        resolved_numeric_filters: list[object] | None = None,
        intent_guardrails: list[str] | None = None,
        unresolved_ambiguities: list[str] | None = None,
    ) -> RetrievalResult:
        if not self.tables:
            raise ValueError("No semantic metadata available for query generation.")
        detected_query_pattern = detect_query_pattern(question)
        lower_question = question.lower()
        asks_code = bool(re.search(r"\b(codigo|codigos|llave|valor numerico|id)\b", lower_question))
        domain_tables = [t for t in self.tables if t.domain == domain and t.allowed_for_query]
        if not domain_tables:
            raise ValueError("No semantic metadata available for query generation.")
        allowed_tables = [t for t in self.tables if t.allowed_for_query]

        selected_context_by_table: dict[str, list[str]] = {}
        selected_table_order: list[str] = []
        candidate_tables = domain_tables
        if self.context_selector is not None:
            selected_contexts = self.context_selector.select(
                question=question,
                domain=domain,
                relationships=self.relationships,
                parametric_mappings=self.parametric_mappings,
                unresolved_ambiguities=unresolved_ambiguities or [],
                resolved_lookup_values=resolved_lookup_values or [],
                resolved_numeric_filters=resolved_numeric_filters or [],
                static_mapping_columns=[f"{m.table}.{m.column}" for m in self.static_value_mappings],
            )
            selected_context_by_table = {ctx.table.upper(): [c.upper() for c in ctx.selected_columns] for ctx in selected_contexts}
            selected_table_order = [ctx.table.upper() for ctx in selected_contexts]
            if selected_context_by_table:
                candidate_tables = [t for t in allowed_tables if t.full_name.upper() in selected_context_by_table]
                if not candidate_tables:
                    candidate_tables = domain_tables

        scored: list[tuple[int, TableMetadata]] = []
        for table in candidate_tables:
            column_hits = sum(1 for col in table.columns if col.name.lower() in lower_question)
            table_hit = int(table.name.lower() in lower_question)
            score = column_hits + (3 * table_hit)
            scored.append((score, table))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [t for score, t in scored if score > 0][:max_tables]
        if not selected:
            selected = candidate_tables[:max_tables]
        if selected_table_order:
            # When context selector already curated a safe table set, keep that set as
            # first priority (for example lookup tables needed by approved mappings).
            by_name = {t.full_name.upper(): t for t in candidate_tables}
            ordered_selected = [by_name[name] for name in selected_table_order if name in by_name]
            if ordered_selected:
                selected = ordered_selected[:max_tables]
        if not selected:
            raise ValueError("No semantic metadata available for query generation.")

        domain_by_name = {t.full_name: t for t in candidate_tables}
        selected_by_name = {t.full_name: t for t in selected}
        changed = True
        while changed and len(selected_by_name) < max_tables:
            changed = False
            current_names = set(selected_by_name.keys())
            for rel in self.relationships:
                if rel.left_table in current_names and rel.right_table in domain_by_name and rel.right_table not in selected_by_name:
                    selected_by_name[rel.right_table] = domain_by_name[rel.right_table]
                    changed = True
                if len(selected_by_name) >= max_tables:
                    break
                if rel.right_table in current_names and rel.left_table in domain_by_name and rel.left_table not in selected_by_name:
                    selected_by_name[rel.left_table] = domain_by_name[rel.left_table]
                    changed = True
                if len(selected_by_name) >= max_tables:
                    break

        selected = list(selected_by_name.values())[:max_tables]
        selected_names_upper = {t.full_name.upper() for t in selected}
        allowed_by_name = {t.full_name.upper(): t for t in allowed_tables}
        if any(token in lower_question for token in ("usuario", "usuarios", "cliente", "clientes")):
            cliente_table = allowed_by_name.get("SAC.CLIENTES")
            if cliente_table is not None and "SAC.CLIENTES" not in selected_names_upper and len(selected) < max_tables:
                selected.append(cliente_table)
                selected_names_upper.add("SAC.CLIENTES")
        if any(token in lower_question for token in ("armenia", "calarca", "calarca", "municipio", "ciudad", "localidad")):
            municipio_table = allowed_by_name.get("SAC.MUNICIPIOS")
            if municipio_table is not None and "SAC.MUNICIPIOS" not in selected_names_upper and len(selected) < max_tables:
                selected.append(municipio_table)
                selected_names_upper.add("SAC.MUNICIPIOS")
        required_source_tables = {
            m.source_table.upper() for m in self.parametric_mappings if m.source_table.upper() in selected_names_upper
        }
        asks_estado_suministro = "estado suministro" in lower_question or "suministro" in lower_question
        asks_estado_facturacion = "estado facturacion" in lower_question or "facturacion" in lower_question
        for mapping in self.parametric_mappings:
            src = mapping.source_table.upper()
            lookup = mapping.lookup_table.upper()
            if (
                src == "SAC.CLIENTES"
                and mapping.source_column.upper() == "ESTADO_CLIENTE"
                and (asks_estado_suministro or asks_estado_facturacion)
            ):
                continue
            if src in selected_names_upper and lookup in allowed_by_name and lookup not in selected_names_upper:
                if asks_code:
                    continue
                if len(selected) >= max_tables:
                    # Reserve room for mandatory lookup tables referenced by approved
                    # parametric mappings by evicting the last non-required table.
                    evicted = False
                    for idx in range(len(selected) - 1, -1, -1):
                        candidate_name = selected[idx].full_name.upper()
                        if candidate_name not in required_source_tables:
                            selected.pop(idx)
                            selected_names_upper.remove(candidate_name)
                            evicted = True
                            break
                    if not evicted:
                        continue
                selected.append(allowed_by_name[lookup])
                selected_names_upper.add(lookup)

        if asks_code:
            lookup_tables = {m.lookup_table.upper() for m in self.parametric_mappings}
            selected = [t for t in selected if t.full_name.upper() not in lookup_tables]
            selected_names_upper = {t.full_name.upper() for t in selected}

        # Keep municipality catalog in-context for municipality-like filters
        # (including explicit city names) to avoid LLM using out-of-context joins.
        wants_municipality = any(
            token in lower_question
            for token in ("municipio", "ciudad", "localidad", "armenia", "calarca", "calarcá")
        )
        municipality_name = "SAC.MUNICIPIOS"
        if wants_municipality and municipality_name in allowed_by_name and municipality_name not in selected_names_upper:
            if len(selected) >= max_tables:
                selected.pop(-1)
            selected.append(allowed_by_name[municipality_name])
            selected_names_upper.add(municipality_name)

        if self._should_prefer_medidores_static_estado(question, selected):
            selected = [t for t in selected if t.full_name.upper() != "SAC.MULTITABLA"]
        allowed_names = {table.full_name for table in selected}
        if self._should_prefer_medidores_static_estado(question, selected):
            allowed_names = {name for name in allowed_names if name.upper() != "SAC.MULTITABLA"}
        rels = [
            r
            for r in self.relationships
            if r.left_table in allowed_names and r.right_table in allowed_names
        ]

        filtered_tables: list[TableMetadata] = []
        disallowed_columns: set[str] = set()
        for table in selected:
            if settings.sql_allow_sensitive_columns:
                filtered_tables.append(table)
                continue

            sensitive_set = {c.upper() for c in table.sensitive_columns}
            sanitized_columns = []
            context_cols = set(selected_context_by_table.get(table.full_name.upper(), []))
            for column in table.columns:
                if not column.allowed_for_select:
                    disallowed_columns.add(f"{table.full_name}.{column.name}".upper())
                    continue
                if column.sensitive or column.name.upper() in sensitive_set:
                    disallowed_columns.add(f"{table.full_name}.{column.name}".upper())
                    continue
                if context_cols and column.name.upper() not in context_cols:
                    continue
                sanitized_columns.append(column)
            filtered_tables.append(table.model_copy(update={"columns": sanitized_columns}))

        selected_columns_by_table: dict[str, set[str]] = {
            table.full_name.upper(): {col.name.upper() for col in table.columns}
            for table in filtered_tables
        }
        filtered_static_mappings = [
            m
            for m in self.static_value_mappings
            if m.table.upper() in selected_columns_by_table
            and m.column.upper() in selected_columns_by_table[m.table.upper()]
        ]

        return RetrievalResult(
            domain=domain,
            tables=filtered_tables,
            relationships=rels,
            examples=self.examples.get(domain, []),
            disallowed_columns=disallowed_columns,
            parametric_mappings=self.parametric_mappings,
            static_value_mappings=filtered_static_mappings,
            resolved_lookup_values=list(resolved_lookup_values or []),
            resolved_numeric_filters=list(resolved_numeric_filters or []),
            intent_guardrails=list(intent_guardrails or []),
            auxiliary_semantic_context=self._build_auxiliary_context(filtered_tables),
            detected_query_pattern=detected_query_pattern,
        )

    def _should_prefer_medidores_static_estado(self, question: str, selected_tables: list[TableMetadata]) -> bool:
        q = question.lower()
        has_medidores_question = any(token in q for token in ("medidor", "medidores", "contador", "contadores"))
        has_estado_question = "estado" in q or any(token in q for token in ("activo", "activos", "instalado", "instalados", "inactivo", "inactivos", "retirado", "retirados"))
        # If the state intent is explicitly about client/customer status, keep
        # MULTITABLA available for approved customer-state mappings.
        has_cliente_estado_intent = (
            ("cliente" in q or "clientes" in q or "usuario" in q or "usuarios" in q)
            and any(token in q for token in ("activo", "activos", "inactivo", "inactivos", "estado cliente"))
        )
        if has_cliente_estado_intent:
            return False
        if not (has_medidores_question and has_estado_question):
            return False
        has_medidores_table = any(t.full_name.upper() == "SAC.MEDIDORES" for t in selected_tables)
        if not has_medidores_table:
            return False
        return any(
            m.table.upper() == "SAC.MEDIDORES" and m.column.upper() == "ESTADO"
            for m in self.static_value_mappings
        )

    def _build_auxiliary_context(self, tables: list[TableMetadata]) -> list[str]:
        output: list[str] = []
        table_comments = self.oracle_comments.get("tables", {}) if isinstance(self.oracle_comments, dict) else {}
        for table in tables:
            full_name = table.full_name.upper()
            entry = table_comments.get(full_name, {})
            if not isinstance(entry, dict):
                continue
            table_comment = str(entry.get("table_comment") or "").strip()
            if table_comment:
                output.append(f"{full_name} table_comment: {table_comment}")
            columns = entry.get("columns", {})
            if not isinstance(columns, dict):
                continue
            for col_name, col_entry in columns.items():
                if not isinstance(col_entry, dict):
                    continue
                hint = str(col_entry.get("detected_parametric_hint") or "").strip()
                comment = str(col_entry.get("comment") or "").strip()
                confidence = str(col_entry.get("confidence") or "").strip()
                if hint:
                    output.append(
                        f"{full_name}.{str(col_name).upper()} comment_hint: {hint} confidence={confidence or 'low'} note=auxiliary_only"
                    )
                elif comment:
                    output.append(f"{full_name}.{str(col_name).upper()} comment: {comment}")
        return output[:50]
