from __future__ import annotations

from app.semantic_catalog.models import DetectedQueryPattern, DomainCatalog, ParametricMapping, ResolvedLookupValue, StaticValueMapping, TableMetadata


CLASSIFIER_SYSTEM_PROMPT = """Eres un clasificador de dominio de datos para Text-to-SQL.
Devuelve solo el nombre exacto del dominio entre los dominios permitidos.
"""


def build_classifier_user_prompt(question: str, domains: list[DomainCatalog]) -> str:
    domain_lines = [f"- {d.name}: {d.description}" for d in domains]
    return (
        "Dominios disponibles:\n"
        + "\n".join(domain_lines)
        + "\n\nPregunta del usuario:\n"
        + question
        + "\n\nResponde solo con el nombre del dominio."
    )


SQL_SYSTEM_PROMPT = """Eres un generador SQL empresarial seguro.
Reglas estrictas:
- Responde con UNA sola consulta SQL.
- Solo SELECT.
- No INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, EXEC.
- Usa solo tablas y columnas permitidas.
- No inventes tablas.
- Usa solo ASCII en toda la salida SQL: sin tildes, sin eñe, sin caracteres especiales Unicode.
"""


def _render_resolved_numeric_filter(item: object) -> str:
    if isinstance(item, dict):
        value_type = str(item.get("value_type", "string")).lower()
        value = str(item.get("value", ""))
        literal = value if value_type == "number" else f"'{value}'"
        predicate = (
            f"{item.get('source_table', '')}.{item.get('source_column', '')} "
            f"{item.get('operator', '=')} {literal}"
        ).strip()
        forbidden = item.get("forbidden_columns") or []
        if forbidden:
            return f"{predicate} | forbidden_columns: {', '.join(str(col) for col in forbidden)}"
        return predicate
    predicate = getattr(item, "sql_predicate", str(item))
    forbidden = getattr(item, "forbidden_columns", [])
    if forbidden:
        return f"{predicate} | forbidden_columns: {', '.join(forbidden)}"
    return predicate


def _render_resolved_lookup_value(item: ResolvedLookupValue) -> str:
    extra: list[str] = []
    if item.fixed_filter_value:
        extra.append(f"fixed_filter_value: {item.fixed_filter_value}")
    if item.code:
        extra.append(f"code: '{item.code}'")
    if item.matched_synonym:
        extra.append(f"matched_synonym: {item.matched_synonym}")
    if item.resolution_source:
        extra.append(f"resolution_source: {item.resolution_source}")
    suffix = f" | {' | '.join(extra)}" if extra else ""
    return (
        f"{item.source_table}.{item.source_column} -> "
        f"{item.lookup_table}.{item.lookup_description} = '{item.canonical_value}'"
        f"{suffix}"
    )


def build_sql_user_prompt(
    question: str,
    tables: list[TableMetadata],
    relationships: list[str],
    examples: list[str],
    approved_parametric_mappings: list[ParametricMapping],
    static_value_mappings: list[StaticValueMapping],
    resolved_lookup_values: list[ResolvedLookupValue],
    resolved_numeric_filters: list[object],
    intent_guardrails: list[str],
    auxiliary_semantic_context: list[str],
    detected_query_pattern: DetectedQueryPattern | None = None,
) -> str:
    tables_text = []
    for table in tables:
        columns = ", ".join(f"{c.name} ({c.type})" for c in table.columns)
        tables_text.append(f"Tabla: {table.full_name} | Descripcion: {table.description} | Columnas: {columns}")

    rel_text = "\n".join(relationships) if relationships else "Sin relaciones adicionales"
    join_lines = list(
        dict.fromkeys(
            line.split(" (")[0].split(" | fixed_filter")[0]
            for line in relationships
        )
    )
    join_paths_text = "\n".join(join_lines) if join_lines else "Sin join paths aprobados"

    table_names = {table.full_name.upper() for table in tables}
    q = question.lower()
    medidores_municipio_rule = ""
    if (
        "SAC.MEDIDORES" in table_names
        and "SAC.CLIENTES" in table_names
        and "SAC.MUNICIPIOS" in table_names
        and ("medidor" in q or "medidores" in q or "contador" in q or "contadores" in q)
        and ("municipio" in q or "ciudad" in q or "localidad" in q)
        ):
        medidores_municipio_rule = (
            "Regla de cadena aprobada (obligatoria para medidores por municipio):\n"
            "- Usa JOIN SAC.MEDIDORES -> SAC.CLIENTES -> SAC.MUNICIPIOS.\n"
            "- JOIN 1: SAC.MEDIDORES.CLIENTE_ID = SAC.CLIENTES.CLIENTE_ID.\n"
            "- JOIN 2: SAC.CLIENTES.MUNICIPIO = SAC.MUNICIPIOS.MUNICIPIO.\n"
            "- Agrupa por M.DESCRIPCION y cuenta medidores con COUNT(MED.MEDIDOR_ID) o COUNT(*).\n"
            "- No usar MULTITABLA para esta pregunta.\n\n"
        )

    medidores_estado_filter_rule = ""
    if "SAC.MEDIDORES" in table_names:
        medidores_estado_filter_rule = (
            "Regla de filtro de estado de medidores (obligatoria):\n"
            "- Si la pregunta menciona 'activo', 'activos', 'instalado', 'instalada', 'instalados' o 'en servicio', filtra con MED.ESTADO = 'I'.\n"
            "- Si la pregunta menciona 'inactivo', 'inactivos', 'retirado', 'retirada', 'retirados' o 'fuera de servicio', filtra con MED.ESTADO = 'R'.\n"
            "- Esta traduccion aplica tambien en consultas de ranking/superlativo (ejemplo: 'marca con mas medidores instalados').\n"
            "- No reemplazar este caso con MULTITABLA.\n\n"
        )
    mapping_text = (
        "\n".join(f"- {m.as_text}" for m in approved_parametric_mappings)
        if approved_parametric_mappings
        else "Sin mappings parametricos aprobados"
    )
    static_mapping_text = (
        "\n".join(f"- {m.as_text}" for m in static_value_mappings)
        if static_value_mappings
        else "Sin static_value_mappings gobernados"
    )
    resolved_lookup_text = (
        "\n".join(f"- {_render_resolved_lookup_value(item)}" for item in resolved_lookup_values)
        if resolved_lookup_values
        else "Sin resolved_lookup_values gobernados"
    )
    resolved_numeric_text = (
        "\n".join(f"- {_render_resolved_numeric_filter(item)}" for item in resolved_numeric_filters)
        if resolved_numeric_filters
        else "Sin resolved_numeric_filters gobernados"
    )
    intent_guardrails_text = (
        "\n".join(f"- {item}" for item in intent_guardrails)
        if intent_guardrails
        else "Sin guardrails adicionales de intencion"
    )
    comments_text = "\n".join(f"- {line}" for line in auxiliary_semantic_context) if auxiliary_semantic_context else "Sin comentarios auxiliares"
    ex_text = "\n".join(examples) if examples else "Sin ejemplos"
    pattern_block = ""
    if detected_query_pattern and detected_query_pattern.sql_skeleton:
        extra_pattern_rules = ""
        if detected_query_pattern.type == "entity_count_with_cardinality_condition":
            extra_pattern_rules = "- No reemplazar por COUNT(DISTINCT ...) con GROUP BY externo.\n"
        pattern_block = (
            "SQL skeleton obligatorio (debes respetarlo exactamente):\n"
            f"{detected_query_pattern.sql_skeleton}\n"
            "- El SQL final debe respetar esta estructura principal.\n"
            "- Solo completa joins, filtros, aliases y columnas reales.\n"
            "- No cambies la forma principal del skeleton.\n\n"
            f"{extra_pattern_rules}"
        )

    return (
        f"Pregunta: {question}\n\n"
        f"Tablas disponibles:\n" + "\n".join(tables_text) + "\n\n"
        f"Relaciones:\n{rel_text}\n\n"
        f"Join paths aprobados:\n{join_paths_text}\n\n"
        f"{pattern_block}"
        f"{medidores_municipio_rule}"
        f"{medidores_estado_filter_rule}"
        "Regla de intencion agregada (obligatoria):\n"
        "- Si la pregunta sigue patrones como 'clientes por X', 'cantidad de clientes por X', "
        "'conteo de clientes por X' o 'numero de clientes por X', debes generar agregacion.\n"
        "- Usa SELECT X, COUNT(...) y GROUP BY X.\n"
        "- No listar filas individuales para ese tipo de pregunta.\n\n"
        "Regla de ranking/superlativo (obligatoria):\n"
        "- Para expresiones como 'con mas', 'mayor cantidad', 'top', 'mas medidores':\n"
        "  1) Selecciona la dimension de negocio.\n"
        "  2) Selecciona tambien la metrica COUNT(...).\n"
        "  3) GROUP BY dimension.\n"
        "  4) ORDER BY COUNT(...) DESC.\n"
        "  5) Limita a 1 fila (preferir FETCH FIRST 1 ROW ONLY en Oracle).\n"
        "- No devolver solo la dimension sin la metrica.\n\n"
        "Regla de conteo exacto de entidades con condicion de cardinalidad (obligatoria):\n"
        "- Si la pregunta es del tipo 'cantidad de usuarios/clientes con N medidores', "
        "devuelve UN solo numero final, no una fila por cliente.\n"
        "- Debes usar doble agregacion:\n"
        "  1) Subconsulta agrupada por cliente con HAVING COUNT(MEDIDOR_ID) = N.\n"
        "  2) Consulta externa con COUNT(*) sobre la subconsulta.\n"
        "- Si la pregunta usa 'mas de N' medidores, usa HAVING COUNT(MED.MEDIDOR_ID) > N.\n"
        "- Si la pregunta dice 'mas de dos', interpreta N=2.\n"
        "- Ejemplo correcto:\n"
        "  SELECT COUNT(*) AS CANTIDAD_USUARIOS\n"
        "  FROM (\n"
        "    SELECT MED.CLIENTE_ID\n"
        "    FROM SAC.MEDIDORES MED\n"
        "    WHERE MED.ESTADO = 'I'\n"
        "    GROUP BY MED.CLIENTE_ID\n"
        "    HAVING COUNT(MED.MEDIDOR_ID) = 2\n"
        "  ) Q;\n"
        "- No devolver COUNT(...) agrupado directamente por CLIENTE_ID como resultado final.\n\n"
        "Regla de filtros textuales de negocio (obligatoria):\n"
        "- Para comparaciones textuales funcionales usar comparacion case-insensitive y accent-insensitive en Oracle.\n"
        "- Preferir: NLSSORT(TRIM(campo_textual), 'NLS_SORT=BINARY_AI') = NLSSORT(TRIM('valor'), 'NLS_SORT=BINARY_AI')\n"
        "- Solo si no aplica NLSSORT, usar como fallback: UPPER(TRIM(campo_textual)) = UPPER(TRIM('valor'))\n"
        "- Aplica a descripciones, nombres, municipios, estados y textos funcionales.\n"
        "- No aplicar UPPER/TRIM a columnas numericas, IDs, llaves tecnicas o fechas.\n"
        "- Ejemplo: para 'Clientes con estado activo' usar WHERE NLSSORT(TRIM(MT.DESCRIPCION), 'NLS_SORT=BINARY_AI') = NLSSORT(TRIM('Activo'), 'NLS_SORT=BINARY_AI').\n\n"
        "Regla de normalizacion de texto en literales (obligatoria):\n"
        "- Si el texto de entrada tiene tildes o caracteres Unicode, normaliza a ASCII en los literales SQL.\n"
        "- Ejemplo: usar 'Calarca' en lugar de variantes con tilde.\n\n"
        "Regla de municipio/ciudad (obligatoria):\n"
        "- Si la pregunta filtra por nombre de municipio/ciudad/localidad, usar SAC.MUNICIPIOS.DESCRIPCION con UPPER/TRIM.\n"
        "- Unir por codigo: SAC.CLIENTES.MUNICIPIO = SAC.MUNICIPIOS.MUNICIPIO.\n"
        "- No comparar texto contra SAC.CLIENTES.MUNICIPIO (es codigo numerico).\n\n"
        "Politica de parametrizaciones:\n"
        "- Nunca usar SAC.MULTITABLA si no existe approved_parametric_mapping para la columna consultada.\n"
        "- Si no existe mapping aprobado, usar la columna base original (codigo/llave).\n"
        "- Comentarios Oracle con [TABLA] son solo sugerencia, no autorizacion.\n\n"
        "Regla de estado cliente con valor de negocio (obligatoria):\n"
        "- Si la pregunta menciona 'cliente activo', 'clientes activos' o filtro descriptivo de estado cliente:\n"
        "  usa approved_parametric_mapping y no codigos magicos.\n"
        "- Debe incluir:\n"
        "  JOIN ... CLI.ESTADO_CLIENTE = MT.CODIGO_NUM\n"
        "  MT.TABLA = 'CLI_ESTADO'\n"
        "  UPPER(TRIM(MT.DESCRIPCION)) = UPPER(TRIM('Activo'))\n"
        "- Nunca usar CLI.ESTADO_CLIENTE = 1 para representar 'Activo'.\n\n"
        "Regla de static_value_mappings (gobernada):\n"
        "- static_value_mappings son verdad gobernada para traduccion de sinonimos de negocio a codigos reales.\n"
        "- Si existe static_value_mapping para una columna, NO usar MULTITABLA para ese caso.\n"
        "- En filtros, usar el codigo real (ejemplo: ESTADO='I' o ESTADO='R').\n"
        "- En reportes por estado, puedes usar CASE para etiqueta legible cuando exista mapping.\n\n"
        "Regla de resolved_lookup_values (obligatoria):\n"
        "- Si existe resolved_lookup_value, usar exactamente ese valor canonico en el SQL.\n"
        "- No inventar ni reinterpretar la descripcion final de MULTITABLA.\n"
        "- No comparar contra otro literal distinto al valor canonico resuelto.\n"
        "- Si resolved_lookup_value viene de approved_lookup_values, usar JOIN aprobado a MULTITABLA,\n"
        "  aplicar el fixed_filter_value aprobado y comparar el texto contra lookup_description.\n"
        "- Para ese filtro descriptivo, preferir NLSSORT(TRIM(lookup_description), 'NLS_SORT=BINARY_AI') = NLSSORT(TRIM('valor canonico'), 'NLS_SORT=BINARY_AI').\n"
        "- No comparar ese texto contra columnas base o vecinas como PROCESO, TIPO, ESTADO u otras no aprobadas.\n\n"
        "Regla de resolved_numeric_filters (obligatoria):\n"
        "- Si existe resolved_numeric_filter, usar exactamente source_column/operator/value.\n"
        "- No reinterpretar el literal numerico o textual en otra columna.\n"
        "- No mover el filtro a columnas alternativas o semanticas vecinas.\n"
        "- Si el usuario pidio descripcion y existe description_lookup aprobado, puedes usar lookup_description.\n"
        "- Si el usuario no pidio descripcion, filtra por codigo base.\n\n"
        "Guardrails de intencion (obligatorios):\n"
        "- Si existe un guardrail que prohibe inferir un termino ambiguo, obedecerlo literalmente.\n"
        "- No inventar filtros, codigos ni columnas para satisfacer un termino ambiguo no resuelto.\n"
        "- Si un termino ambiguo no puede usarse de forma gobernada, omitir ese filtro y conservar solo lo seguro.\n\n"
        "Regla de desambiguacion de estados (obligatoria):\n"
        "- 'estado cliente' => SAC.CLIENTES.ESTADO_CLIENTE (puede usar mapping aprobado a MULTITABLA).\n"
        "- 'estado suministro' => SAC.CLIENTES.ESTADO_SUMINISTRO (sin MULTITABLA si no hay mapping aprobado).\n"
        "- 'estado facturacion' => SAC.CLIENTES.ESTADO_FACTURACION (sin MULTITABLA si no hay mapping aprobado).\n"
        "- Si la pregunta dice solo 'estado' y no especifica suministro/facturacion, priorizar ESTADO_CLIENTE.\n\n"
        "Regla de descripcion vs codigo en campos parametrizados (obligatoria):\n"
        "- Si existe approved_parametric_mapping para la columna solicitada y el usuario pide tipos/descripciones/listado,\n"
        "  devolver lookup_description (ejemplo: MT.DESCRIPCION) usando fixed_filter aprobado.\n"
        "- Solo devolver codigo base cuando el usuario pida explicitamente codigo/llave/valor numerico/id.\n"
        "- Nunca usar MULTITABLA para columnas sin approved_parametric_mapping.\n\n"
        f"Approved parametric mappings:\n{mapping_text}\n\n"
        f"Static value mappings:\n{static_mapping_text}\n\n"
        f"Resolved lookup values:\n{resolved_lookup_text}\n\n"
        f"Resolved numeric filters:\n{resolved_numeric_text}\n\n"
        f"Intent guardrails:\n{intent_guardrails_text}\n\n"
        "Comentarios Oracle auxiliares (NO autorizan joins ni mappings por si solos):\n"
        f"{comments_text}\n\n"
        f"Ejemplos:\n{ex_text}\n\n"
        "Devuelve solo SQL."
    )
