from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from sqlglot import exp, parse, parse_one
from sqlglot.errors import ParseError

from app.core.config import settings
from app.relationship_feedback import UnapprovedJoinPathError, detect_unapproved_join_candidates
from app.sql.dialects import SQLDialect, ensure_row_limit
from app.semantic_catalog.models import DetectedQueryPattern, ParametricMapping, RelationshipMetadata, ResolvedLookupValue
from app.semantic_normalization.models import ResolvedNumericFilter


BLOCKED_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Merge,
    exp.Command,
)
FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "MERGE",
    "EXEC",
    "CALL",
)


@dataclass
class ValidationResult:
    sql: str
    used_tables: set[str]
    limited: bool


class SQLValidator:
    def __init__(
        self,
        *,
        max_rows: int,
        dialect: SQLDialect = SQLDialect.ORACLE,
        allow_union: bool | None = None,
        allow_select_without_from: bool | None = None,
    ) -> None:
        self.max_rows = max_rows
        self.dialect = dialect
        self.allow_union = settings.sql_allow_union if allow_union is None else allow_union
        self.allow_select_without_from = (
            settings.sql_allow_select_without_from
            if allow_select_without_from is None
            else allow_select_without_from
        )

    def validate(
        self,
        sql: str,
        allowed_tables: set[str],
        disallowed_columns: set[str] | None = None,
        approved_relationships: list[RelationshipMetadata] | None = None,
        approved_parametric_mappings: list[ParametricMapping] | None = None,
        resolved_lookup_values: list[ResolvedLookupValue] | None = None,
        resolved_numeric_filters: list[ResolvedNumericFilter] | None = None,
        detected_query_pattern: DetectedQueryPattern | None = None,
        required_null_filters: dict[str, list[str]] | None = None,
        required_text_filters: list[dict[str, str]] | None = None,
    ) -> ValidationResult:
        clean = sql.strip().strip("`")
        if not clean:
            raise ValueError("SQL vacio")
        upper_clean = clean.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{keyword}\b", upper_clean):
                raise ValueError(f"Keyword no permitida detectada: {keyword}")

        try:
            statements = parse(clean, read=self.dialect.value)
        except ParseError as exc:
            raise ValueError("SQL invalido") from exc

        if len(statements) != 1:
            raise ValueError("Multiples sentencias no permitidas")

        statement = statements[0]
        if not isinstance(statement, exp.Select):
            raise ValueError("Solo se permite SELECT")

        if any(isinstance(node, BLOCKED_EXPRESSIONS) for node in statement.walk()):
            raise ValueError("Sentencia contiene operaciones no permitidas")

        if not self.allow_union and any(isinstance(node, exp.Union) for node in statement.walk()):
            raise ValueError("UNION no permitido")

        self._validate_text_search_patterns(statement)

        if approved_relationships is not None:
            alias_map, _ = self._extract_alias_map(statement)
            unapproved_join_candidates = detect_unapproved_join_candidates(
                statement,
                alias_map=alias_map,
                approved_relationships=approved_relationships,
                approved_parametric_mappings=approved_parametric_mappings or [],
            )
            if unapproved_join_candidates:
                raise UnapprovedJoinPathError(unapproved_join_candidates)

        tables_in_query = self._extract_tables(statement)
        if not tables_in_query:
            if not self.allow_select_without_from:
                raise ValueError("SELECT sin FROM no permitido")
        else:
            normalized_allowed = {self._normalize_table_name(table) for table in allowed_tables}
            normalized_used = {self._normalize_table_name(table) for table in tables_in_query}
            if not normalized_used.issubset(normalized_allowed):
                raise ValueError("La consulta usa tablas fuera del catalogo permitido")

        if disallowed_columns:
            self._validate_sensitive_columns(statement, disallowed_columns)
        if approved_parametric_mappings:
            self._validate_parametric_filters(
                statement,
                approved_parametric_mappings,
                resolved_numeric_filters=resolved_numeric_filters or [],
            )
        if resolved_lookup_values:
            self._validate_resolved_lookup_values(statement, resolved_lookup_values)
        if resolved_numeric_filters:
            self._validate_resolved_numeric_filters(statement, resolved_numeric_filters)
        if detected_query_pattern:
            self._validate_pattern_structure(statement, detected_query_pattern)

        if required_null_filters:
            statement = self._apply_required_null_filters(statement, required_null_filters)
            clean = statement.sql(dialect=self.dialect.value)
        if required_text_filters:
            statement = self._apply_required_text_filters(statement, required_text_filters)
            clean = statement.sql(dialect=self.dialect.value)

        sql_limited, limited = ensure_row_limit(clean, dialect=self.dialect, max_rows=self.max_rows)
        return ValidationResult(sql=sql_limited, used_tables=tables_in_query, limited=limited)

    def _apply_required_null_filters(
        self,
        statement: exp.Select,
        required_null_filters: dict[str, list[str]],
    ) -> exp.Select:
        filters = {
            self._normalize_table_name(table): {column.upper() for column in columns}
            for table, columns in required_null_filters.items()
            if columns
        }
        if not filters:
            return statement

        alias_map, _ = self._extract_alias_map(statement)
        existing_sql = (statement.args.get("where").sql(dialect=self.dialect.value).upper() if statement.args.get("where") else "")
        additions: list[exp.Expression] = []

        for table_node in statement.find_all(exp.Table):
            table_name = self._normalize_table_name(self._table_expression_to_name(table_node))
            columns = filters.get(table_name)
            if not columns:
                continue
            qualifier = (table_node.alias_or_name or table_name.split(".")[-1]).upper()
            resolved_table = alias_map.get(qualifier, table_name)
            if resolved_table != table_name:
                qualifier = table_name.split(".")[-1]
            for column in columns:
                marker = f"{qualifier}.{column}"
                if marker in existing_sql or f"{table_name}.{column}" in existing_sql:
                    continue
                additions.append(
                    exp.Is(
                        this=exp.column(column, table=qualifier),
                        expression=exp.Null(),
                    )
                )

        if not additions:
            return statement

        combined = additions[0]
        for addition in additions[1:]:
            combined = exp.and_(combined, addition)

        where = statement.args.get("where")
        if where is None or where.this is None:
            statement.set("where", exp.Where(this=combined))
        else:
            where.set("this", exp.and_(where.this, combined))
        return statement

    def _apply_required_text_filters(
        self,
        statement: exp.Select,
        required_text_filters: list[dict[str, str]],
    ) -> exp.Select:
        alias_map, _ = self._extract_alias_map(statement)
        existing_sql = (statement.args.get("where").sql(dialect=self.dialect.value).upper() if statement.args.get("where") else "")
        additions: list[exp.Expression] = []

        for item in required_text_filters:
            table_name = self._normalize_table_name(item.get("table", ""))
            column = item.get("column", "").upper()
            value = item.get("value", "").strip()
            if not table_name or not column or not value:
                continue
            if value.upper().replace("'", "''") in existing_sql and column in existing_sql:
                continue
            table_short_name = table_name.split(".")[-1]
            aliases = [
                alias
                for alias, table in alias_map.items()
                if table == table_name and "." not in alias and alias != table_short_name
            ]
            qualifier = aliases[0] if aliases else table_short_name
            literal = value.replace("'", "''")
            condition_sql = (
                f"NLSSORT(TRIM({qualifier}.{column}), 'NLS_SORT=BINARY_AI') = "
                f"NLSSORT(TRIM('{literal}'), 'NLS_SORT=BINARY_AI')"
            )
            additions.append(parse_one(condition_sql, read=self.dialect.value))

        if not additions:
            return statement

        combined = additions[0]
        for addition in additions[1:]:
            combined = exp.and_(combined, addition)

        where = statement.args.get("where")
        if where is None or where.this is None:
            statement.set("where", exp.Where(this=combined))
        else:
            where.set("this", exp.and_(where.this, combined))
        return statement

    def _validate_pattern_structure(self, statement: exp.Select, pattern: DetectedQueryPattern) -> None:
        try:
            if pattern.type == "entity_count_with_cardinality_condition":
                self._validate_entity_count_cardinality(statement, pattern)
                return
            if pattern.type == "ranking_top_n":
                self._validate_ranking_top_n(statement, pattern)
                return
            if pattern.type == "grouped_aggregation":
                self._validate_grouped_aggregation(statement)
                return
            if pattern.type == "municipality_filter":
                self._validate_municipality_filter(statement)
                return
            if pattern.type == "descriptive_lookup":
                self._validate_descriptive_lookup(statement)
                return
            if pattern.type == "parametric_status_filter":
                self._validate_parametric_status_filter(statement)
                return
        except ValueError:
            raise
        raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_text_search_patterns(self, statement: exp.Select) -> None:
        for like_node in statement.find_all(exp.Like):
            left_sql = like_node.left.sql(dialect=self.dialect.value).upper()
            right_sql = like_node.right.sql(dialect=self.dialect.value).upper()
            if "NLSSORT(" in left_sql or "NLSSORT(" in right_sql:
                raise ValueError("INVALID_TEXT_LIKE_WITH_NLSSORT")

    def _validate_entity_count_cardinality(self, statement: exp.Select, pattern: DetectedQueryPattern) -> None:
        has_outer_count_star = False
        for expr_node in statement.expressions or []:
            if isinstance(expr_node, exp.Count) and isinstance(expr_node.this, exp.Star):
                has_outer_count_star = True
            for count_node in expr_node.find_all(exp.Count):
                if isinstance(count_node.this, exp.Star):
                    has_outer_count_star = True
        from_clause = statement.args.get("from") or statement.args.get("from_")
        from_subquery = None
        if from_clause is not None:
            from_subquery = from_clause.this
            if from_subquery is None:
                expressions = getattr(from_clause, "expressions", None) or []
                if expressions:
                    from_subquery = expressions[0]
        if not isinstance(from_subquery, exp.Subquery):
            raise ValueError("INVALID_PATTERN_STRUCTURE")

        inner_select = from_subquery.this
        if not isinstance(inner_select, exp.Select):
            raise ValueError("INVALID_PATTERN_STRUCTURE")

        has_group = inner_select.args.get("group") is not None
        has_having = inner_select.args.get("having") is not None
        if not (has_outer_count_star and has_group and has_having):
            raise ValueError("INVALID_PATTERN_STRUCTURE")

        having_expr = inner_select.args["having"].this if inner_select.args.get("having") is not None else None
        operator_node_type = {
            ">": exp.GT,
            "<": exp.LT,
            "=": exp.EQ,
            ">=": exp.GTE,
            "<=": exp.LTE,
        }.get(pattern.operator, exp.EQ)
        if not isinstance(having_expr, operator_node_type):
            raise ValueError("INVALID_PATTERN_STRUCTURE")

        count_side = having_expr.left if isinstance(having_expr.left, exp.Count) else having_expr.right
        literal_side = having_expr.right if count_side is having_expr.left else having_expr.left
        if not isinstance(count_side, exp.Count) or not isinstance(literal_side, exp.Literal):
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        if pattern.threshold is not None:
            try:
                value = int(literal_side.this)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError("INVALID_PATTERN_STRUCTURE") from exc
            if value != pattern.threshold:
                raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_ranking_top_n(self, statement: exp.Select, pattern: DetectedQueryPattern) -> None:
        if statement.args.get("group") is None:
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        order = statement.args.get("order")
        if order is None:
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        if pattern.operator and pattern.threshold is not None:
            having = statement.args.get("having")
            if having is not None and having.this is not None:
                self._validate_cardinality_expression(having.this, pattern)
            elif not self._has_equivalent_cardinality_subquery(statement, pattern):
                raise ValueError("INVALID_PATTERN_STRUCTURE")
        sql_text = statement.sql(dialect=self.dialect.value).upper()
        if "FETCH FIRST" not in sql_text:
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        if pattern.top_n is not None and f"FETCH FIRST {pattern.top_n} ROW" not in sql_text:
            raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_cardinality_expression(self, expression: exp.Expression, pattern: DetectedQueryPattern) -> None:
        operator_node_type = {
            ">": exp.GT,
            "<": exp.LT,
            "=": exp.EQ,
            ">=": exp.GTE,
            "<=": exp.LTE,
        }.get(pattern.operator, exp.EQ)
        if not isinstance(expression, operator_node_type):
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        count_side = expression.left if isinstance(expression.left, exp.Count) else expression.right
        literal_side = expression.right if count_side is expression.left else expression.left
        if not isinstance(count_side, exp.Count) or not isinstance(literal_side, exp.Literal):
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        try:
            value = int(literal_side.this)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("INVALID_PATTERN_STRUCTURE") from exc
        if pattern.threshold is not None and value != pattern.threshold:
            raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _has_equivalent_cardinality_subquery(self, statement: exp.Select, pattern: DetectedQueryPattern) -> bool:
        where = statement.args.get("where")
        if where is None:
            return False
        for in_node in where.find_all(exp.In):
            subquery = in_node.args.get("query")
            if not isinstance(subquery, exp.Subquery):
                continue
            inner = subquery.this
            if not isinstance(inner, exp.Select):
                continue
            if inner.args.get("group") is None:
                continue
            having = inner.args.get("having")
            if having is None or having.this is None:
                continue
            try:
                self._validate_cardinality_expression(having.this, pattern)
            except ValueError:
                continue
            return True
        return False

    def _validate_grouped_aggregation(self, statement: exp.Select) -> None:
        if statement.args.get("group") is None:
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        aggregate_types = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
        has_aggregate = any(isinstance(node, aggregate_types) for node in statement.walk())
        if not has_aggregate:
            raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_municipality_filter(self, statement: exp.Select) -> None:
        sql_text = statement.sql(dialect=self.dialect.value).upper()
        if "MUNICIPIOS" not in sql_text:
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        if "DESCRIPCION" not in sql_text:
            raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_descriptive_lookup(self, statement: exp.Select) -> None:
        if statement.args.get("where") is None:
            raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_parametric_status_filter(self, statement: exp.Select) -> None:
        sql_text = statement.sql(dialect=self.dialect.value).upper()
        if "MULTITABLA" not in sql_text:
            raise ValueError("INVALID_PATTERN_STRUCTURE")
        if "TABLA" not in sql_text or "DESCRIPCION" not in sql_text:
            raise ValueError("INVALID_PATTERN_STRUCTURE")

    def _validate_parametric_filters(
        self,
        statement: exp.Select,
        approved_parametric_mappings: list[ParametricMapping],
        *,
        resolved_numeric_filters: list[ResolvedNumericFilter],
    ) -> None:
        alias_map, _ = self._extract_alias_map(statement)
        mapping_index: dict[tuple[str, str], ParametricMapping] = {}
        approved_pair_keys: set[tuple[str, str, str, str]] = set()
        allowed_numeric_predicates = {
            (
                self._normalize_table_name(item.source_table),
                item.source_column.upper(),
                str(item.value),
                item.value_type.lower(),
            )
            for item in resolved_numeric_filters
        }
        for mapping in approved_parametric_mappings:
            key = (self._normalize_table_name(mapping.source_table), mapping.source_column.upper())
            mapping_index[key] = mapping
            approved_pair_keys.add(
                (
                    self._normalize_table_name(mapping.source_table),
                    mapping.source_column.upper(),
                    self._normalize_table_name(mapping.lookup_table),
                    mapping.lookup_key.upper(),
                )
            )
            approved_pair_keys.add(
                (
                    self._normalize_table_name(mapping.lookup_table),
                    mapping.lookup_key.upper(),
                    self._normalize_table_name(mapping.source_table),
                    mapping.source_column.upper(),
                )
            )

        parametric_joins_present: set[tuple[str, str]] = set()
        for eq_node in statement.find_all(exp.EQ):
            if not isinstance(eq_node.left, exp.Column) or not isinstance(eq_node.right, exp.Column):
                continue
            left_table = alias_map.get((eq_node.left.table or "").upper(), (eq_node.left.table or "").upper())
            right_table = alias_map.get((eq_node.right.table or "").upper(), (eq_node.right.table or "").upper())
            left_col = (eq_node.left.name or "").upper()
            right_col = (eq_node.right.name or "").upper()
            left_norm = self._normalize_table_name(left_table)
            right_norm = self._normalize_table_name(right_table)

            involves_multitabla = left_norm.endswith(".MULTITABLA") or right_norm.endswith(".MULTITABLA")
            if involves_multitabla:
                pair = (left_norm, left_col, right_norm, right_col)
                if pair not in approved_pair_keys:
                    raise ValueError("UNAPPROVED_PARAMETRIC_JOIN")

            for key, mapping in mapping_index.items():
                source_table, source_col = key
                lookup_table = self._normalize_table_name(mapping.lookup_table)
                lookup_key = mapping.lookup_key.upper()
                if (
                    left_norm == source_table
                    and left_col == source_col
                    and right_norm == lookup_table
                    and right_col == lookup_key
                ) or (
                    right_norm == source_table
                    and right_col == source_col
                    and left_norm == lookup_table
                    and left_col == lookup_key
                ):
                    parametric_joins_present.add(key)

        for eq_node in statement.find_all(exp.EQ):
            if not isinstance(eq_node.left, exp.Column):
                continue
            left_table = alias_map.get((eq_node.left.table or "").upper(), (eq_node.left.table or "").upper())
            left_col = (eq_node.left.name or "").upper()
            key = (self._normalize_table_name(left_table), left_col)
            if key not in mapping_index:
                continue
            right_expr = eq_node.right
            if isinstance(right_expr, exp.Literal):
                literal_value = str(right_expr.this)
                literal_type = "string" if right_expr.is_string else "number"
                if (key[0], key[1], literal_value, literal_type) in allowed_numeric_predicates:
                    continue
                # Bloquea filtros "magicos" directos sobre columnas parametrizadas.
                raise ValueError("PARAMETRIC_FILTER_WITHOUT_LOOKUP")

        # Si se usa la tabla lookup del mapping y se filtra por descripcion, exigir fixed_filter.
        for key, mapping in mapping_index.items():
            if key not in parametric_joins_present:
                continue
            lookup_table = self._normalize_table_name(mapping.lookup_table)
            lookup_aliases = [a for a, t in alias_map.items() if t == lookup_table]
            if not lookup_aliases:
                lookup_aliases = [lookup_table]

            has_desc_filter = False
            has_fixed_filter = False
            fixed_filter = (mapping.fixed_filter or "").upper().replace('"', "").replace("[", "").replace("]", "")
            fixed_filter_variants: set[str] = set()
            if fixed_filter:
                fixed_filter_variants.add(fixed_filter)
                for alias in lookup_aliases:
                    fixed_filter_variants.add(fixed_filter.replace(lookup_table, alias))

            for eq_node in statement.find_all(exp.EQ):
                left_sql = eq_node.left.sql(dialect=self.dialect.value).upper().replace('"', "").replace("[", "").replace("]", "")
                right_sql = eq_node.right.sql(dialect=self.dialect.value).upper().replace('"', "").replace("[", "").replace("]", "")
                for alias in lookup_aliases:
                    if f"{alias}.DESCRIPCION" in left_sql or f"{alias}.DESCRIPCION" in right_sql:
                        has_desc_filter = True
                if fixed_filter and any(
                    _fixed_filter_semantically_matches(left_sql, right_sql, candidate)
                    for candidate in fixed_filter_variants
                ):
                    has_fixed_filter = True

            if has_desc_filter and fixed_filter and not has_fixed_filter:
                raise ValueError("PARAMETRIC_FILTER_WITHOUT_LOOKUP")

    def _validate_resolved_lookup_values(self, statement: exp.Select, resolved_lookup_values: list[ResolvedLookupValue]) -> None:
        alias_map, _ = self._extract_alias_map(statement)
        by_key = {
            (item.source_table.upper(), item.source_column.upper()): item
            for item in resolved_lookup_values
        }
        parametric_joins_present: dict[tuple[str, str], list[str]] = {}

        for eq_node in statement.find_all(exp.EQ):
            if not isinstance(eq_node.left, exp.Column) or not isinstance(eq_node.right, exp.Column):
                continue
            left_table = alias_map.get((eq_node.left.table or "").upper(), (eq_node.left.table or "").upper())
            right_table = alias_map.get((eq_node.right.table or "").upper(), (eq_node.right.table or "").upper())
            left_col = (eq_node.left.name or "").upper()
            right_col = (eq_node.right.name or "").upper()

            left_key = (self._normalize_table_name(left_table), left_col)
            right_key = (self._normalize_table_name(right_table), right_col)
            if left_key in by_key:
                parametric_joins_present.setdefault(left_key, []).append(self._normalize_table_name(right_table))
            if right_key in by_key:
                parametric_joins_present.setdefault(right_key, []).append(self._normalize_table_name(left_table))

        for eq_node in statement.find_all(exp.EQ):
            literal_value = _extract_business_string_literal(eq_node.left) or _extract_business_string_literal(eq_node.right)
            if literal_value is None:
                continue
            left_sql = eq_node.left.sql(dialect=self.dialect.value).upper().replace('"', "").replace("[", "").replace("]", "")
            right_sql = eq_node.right.sql(dialect=self.dialect.value).upper().replace('"', "").replace("[", "").replace("]", "")
            column_ref = _extract_column_reference(eq_node.left) or _extract_column_reference(eq_node.right)

            for key, resolved in by_key.items():
                lookup_table = self._normalize_table_name(resolved.lookup_table)
                lookup_aliases = [alias for alias, table in alias_map.items() if table == lookup_table]
                if not lookup_aliases:
                    lookup_aliases = [lookup_table]
                canonical_matches = (
                    _normalize_business_text(literal_value) == _normalize_business_text(resolved.canonical_value)
                    if resolved.resolution_source == "approved_lookup_values"
                    else literal_value == resolved.canonical_value
                )
                if canonical_matches and column_ref is not None:
                    ref_table, ref_column = column_ref
                    ref_table = alias_map.get(ref_table.upper(), ref_table.upper())
                    ref_table = self._normalize_table_name(ref_table)
                    if not (
                        ref_table == lookup_table and ref_column == resolved.lookup_description.upper()
                    ):
                        raise ValueError("INVALID_LOOKUP_VALUE_COLUMN")
                if key not in parametric_joins_present:
                    continue
                if not any(
                    f"{alias}.{resolved.lookup_description.upper()}" in left_sql
                    or f"{alias}.{resolved.lookup_description.upper()}" in right_sql
                    for alias in lookup_aliases
                ):
                    continue
                if not canonical_matches:
                    raise ValueError("UNRESOLVED_LOOKUP_VALUE")

        for key, resolved in by_key.items():
            if resolved.resolution_source != "approved_lookup_values":
                continue
            if key not in parametric_joins_present:
                raise ValueError("INVALID_LOOKUP_VALUE_COLUMN")

            lookup_table = self._normalize_table_name(resolved.lookup_table)
            lookup_aliases = [alias for alias, table in alias_map.items() if table == lookup_table]
            if not lookup_aliases:
                lookup_aliases = [lookup_table]

            has_description_filter = False
            has_fixed_filter = False
            fixed_filter_candidate = (
                f"{lookup_table}.TABLA = '{resolved.fixed_filter_value}'" if resolved.fixed_filter_value else ""
            )
            fixed_filter_variants = {fixed_filter_candidate} if fixed_filter_candidate else set()
            for alias in lookup_aliases:
                if fixed_filter_candidate:
                    fixed_filter_variants.add(fixed_filter_candidate.replace(lookup_table, alias))

            for eq_node in statement.find_all(exp.EQ):
                literal_value = _extract_business_string_literal(eq_node.left) or _extract_business_string_literal(eq_node.right)
                left_sql = eq_node.left.sql(dialect=self.dialect.value).upper().replace('"', "").replace("[", "").replace("]", "")
                right_sql = eq_node.right.sql(dialect=self.dialect.value).upper().replace('"', "").replace("[", "").replace("]", "")
                if literal_value is not None and _normalize_business_text(literal_value) == _normalize_business_text(resolved.canonical_value):
                    if any(
                        f"{alias}.{resolved.lookup_description.upper()}" in left_sql
                        or f"{alias}.{resolved.lookup_description.upper()}" in right_sql
                        for alias in lookup_aliases
                    ):
                        has_description_filter = True
                if fixed_filter_variants and any(
                    _fixed_filter_semantically_matches(left_sql, right_sql, candidate)
                    for candidate in fixed_filter_variants
                ):
                    has_fixed_filter = True

            if not has_description_filter or (resolved.fixed_filter_value and not has_fixed_filter):
                raise ValueError("INVALID_LOOKUP_VALUE_COLUMN")

    def _validate_resolved_numeric_filters(self, statement: exp.Select, resolved_numeric_filters: list[ResolvedNumericFilter]) -> None:
        alias_map, query_tables = self._extract_alias_map(statement)
        comparisons: list[tuple[str, str, exp.Literal, str]] = []
        for comparison in [*statement.find_all(exp.EQ), *statement.find_all(exp.NEQ)]:
            operator = "=" if isinstance(comparison, exp.EQ) else "<>"
            if isinstance(comparison.left, exp.Column) and isinstance(comparison.right, exp.Literal):
                left_table = alias_map.get((comparison.left.table or "").upper(), (comparison.left.table or "").upper())
                if not left_table and len(query_tables) == 1:
                    left_table = next(iter(query_tables))
                comparisons.append((self._normalize_table_name(left_table), (comparison.left.name or "").upper(), comparison.right, operator))
            elif isinstance(comparison.right, exp.Column) and isinstance(comparison.left, exp.Literal):
                right_table = alias_map.get((comparison.right.table or "").upper(), (comparison.right.table or "").upper())
                if not right_table and len(query_tables) == 1:
                    right_table = next(iter(query_tables))
                comparisons.append((self._normalize_table_name(right_table), (comparison.right.name or "").upper(), comparison.left, operator))

        for resolved in resolved_numeric_filters:
            source_table = self._normalize_table_name(resolved.source_table)
            source_column = resolved.source_column.upper()
            expected_value = str(resolved.value)
            matched_expected = False
            for table_name, column_name, literal, operator in comparisons:
                literal_value = str(literal.this)
                if table_name == source_table and column_name in {c.upper() for c in resolved.forbidden_columns} and literal_value == expected_value:
                    raise ValueError("INVALID_NUMERIC_ENTITY_COLUMN")
                if table_name != source_table or column_name != source_column:
                    continue
                if operator != resolved.operator:
                    continue
                if resolved.value_type.lower() == "string" and not literal.is_string:
                    continue
                if resolved.value_type.lower() == "number" and literal.is_string:
                    continue
                if literal_value == expected_value:
                    matched_expected = True
            if not matched_expected:
                raise ValueError("UNRESOLVED_NUMERIC_FILTER")

    def _validate_sensitive_columns(self, statement: exp.Select, disallowed_columns: set[str]) -> None:
        normalized_disallowed = {item.upper() for item in disallowed_columns}
        sensitive_by_table = self._build_sensitive_map(normalized_disallowed)
        select_exprs = statement.expressions or []

        if self._selects_star_with_sensitive_risk(statement, select_exprs, sensitive_by_table):
            raise ValueError("La consulta intenta seleccionar columnas sensibles")

        alias_map, query_tables = self._extract_alias_map(statement)
        normalized_query_tables = {self._normalize_table_name(table) for table in query_tables}

        for expr_node in select_exprs:
            for column in expr_node.find_all(exp.Column):
                column_name = column.name.upper()
                if column_name == "*":
                    continue

                qualifier = (column.table or "").upper()
                if qualifier:
                    resolved_table = alias_map.get(qualifier, self._normalize_table_name(qualifier))
                    sensitive_cols = sensitive_by_table.get(resolved_table, set())
                    if column_name in sensitive_cols:
                        raise ValueError("La consulta intenta seleccionar columnas sensibles")
                    continue

                sensitive_tables = {
                    table
                    for table in normalized_query_tables
                    if column_name in sensitive_by_table.get(table, set())
                }
                if len(sensitive_tables) == 1:
                    raise ValueError("La consulta intenta seleccionar columnas sensibles")
                if len(sensitive_tables) > 1:
                    raise ValueError("La consulta contiene columna ambigua con sensibilidad")

    def _selects_star_with_sensitive_risk(
        self,
        statement: exp.Select,
        select_exprs: list[exp.Expression],
        sensitive_by_table: dict[str, set[str]],
    ) -> bool:
        if not sensitive_by_table:
            return False
        alias_map, query_tables = self._extract_alias_map(statement)
        normalized_query_tables = {self._normalize_table_name(table) for table in query_tables}

        if any(isinstance(expr, exp.Star) for expr in select_exprs):
            return any(table in sensitive_by_table for table in normalized_query_tables)

        for expr_node in select_exprs:
            for column in expr_node.find_all(exp.Column):
                if column.name != "*":
                    continue
                qualifier = (column.table or "").upper()
                if not qualifier:
                    return any(table in sensitive_by_table for table in normalized_query_tables)
                resolved_table = alias_map.get(qualifier, self._normalize_table_name(qualifier))
                if resolved_table in sensitive_by_table:
                    return True
        return False

    def _extract_alias_map(self, statement: exp.Select) -> tuple[dict[str, str], set[str]]:
        alias_map: dict[str, str] = {}
        query_tables: set[str] = set()
        for table in statement.find_all(exp.Table):
            full_name = self._table_expression_to_name(table)
            if not full_name:
                continue
            normalized_full = self._normalize_table_name(full_name)
            query_tables.add(normalized_full)

            table_name_only = normalized_full.split(".")[-1]
            alias_map[table_name_only] = normalized_full
            alias_map[normalized_full] = normalized_full

            alias_name = table.alias_or_name if hasattr(table, "alias_or_name") else ""
            alias_name = (alias_name or "").upper()
            if alias_name and alias_name != table_name_only:
                alias_map[alias_name] = normalized_full
        return alias_map, query_tables

    @staticmethod
    def _build_sensitive_map(disallowed_columns: set[str]) -> dict[str, set[str]]:
        mapped: dict[str, set[str]] = {}
        for item in disallowed_columns:
            parts = item.split(".")
            if len(parts) < 3:
                continue
            table_name = SQLValidator._normalize_table_name(".".join(parts[:-1]))
            column_name = parts[-1].upper()
            mapped.setdefault(table_name, set()).add(column_name)
        return mapped

    @staticmethod
    def _table_expression_to_name(table: exp.Table) -> str:
        db = table.args.get("db")
        table_name = table.args.get("this")
        db_name = db.name if isinstance(db, exp.Identifier) else (db.sql() if db else None)
        this_name = (
            table_name.name
            if isinstance(table_name, exp.Identifier)
            else table_name.sql()
            if table_name is not None
            else None
        )
        if this_name is None:
            return ""
        if db_name:
            return f"{db_name}.{this_name}"
        return this_name

    @staticmethod
    def _extract_tables(statement: exp.Expression) -> set[str]:
        found: set[str] = set()
        for table in statement.find_all(exp.Table):
            full_name = SQLValidator._table_expression_to_name(table)
            if not full_name:
                continue
            found.add(full_name)
        return found

    @staticmethod
    def _normalize_table_name(table: str) -> str:
        return table.replace('"', "").replace("[", "").replace("]", "").strip().upper()


def _normalize_expr_for_compare(value: str) -> str:
    out = value.strip().upper().replace('"', "").replace("[", "").replace("]", "")
    while out.startswith("UPPER(") and out.endswith(")"):
        out = out[6:-1].strip()
    while out.startswith("TRIM(") and out.endswith(")"):
        out = out[5:-1].strip()
    return out.strip().strip("'")


def _fixed_filter_semantically_matches(left_sql: str, right_sql: str, candidate: str) -> bool:
    if "=" not in candidate:
        return False
    cand_left, cand_right = [piece.strip() for piece in candidate.split("=", 1)]
    left_norm = _normalize_expr_for_compare(left_sql)
    right_norm = _normalize_expr_for_compare(right_sql)
    cand_left_norm = _normalize_expr_for_compare(cand_left)
    cand_right_norm = _normalize_expr_for_compare(cand_right)
    return (
        left_norm == cand_left_norm and right_norm == cand_right_norm
    ) or (
        left_norm == cand_right_norm and right_norm == cand_left_norm
    )


def _extract_string_literal(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Literal) and node.is_string:
        return str(node.this)
    for literal in node.find_all(exp.Literal):
        if literal.is_string:
            return str(literal.this)
    return None


def _extract_business_string_literal(node: exp.Expression) -> str | None:
    direct = _extract_string_literal(node)
    if direct is not None and direct.upper() != "NLS_SORT=BINARY_AI":
        return direct
    literals = [
        str(literal.this)
        for literal in node.find_all(exp.Literal)
        if literal.is_string and str(literal.this).upper() != "NLS_SORT=BINARY_AI"
    ]
    if not literals:
        return None
    return max(literals, key=len)


def _normalize_business_text(value: str) -> str:
    lowered = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(lowered.split())


def _extract_column_reference(node: exp.Expression) -> tuple[str, str] | None:
    if isinstance(node, exp.Column):
        return (
            SQLValidator._normalize_table_name(node.table or ""),
            (node.name or "").upper(),
        )
    columns = list(node.find_all(exp.Column))
    if len(columns) != 1:
        return None
    column = columns[0]
    return (
        SQLValidator._normalize_table_name(column.table or ""),
        (column.name or "").upper(),
    )
