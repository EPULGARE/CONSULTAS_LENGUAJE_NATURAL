import asyncio

from app.llm.sql_generator import SQLGenerator, _extract_select_sql
from app.semantic_catalog.models import ParametricMapping, RelationshipMetadata, ResolvedLookupValue, RetrievalResult, TableMetadata


class FakeClient:
    async def chat_completion(self, **kwargs):
        return "SELECT status_flag FROM TEST_SCHEMA.TEST_TABLE"


def test_sql_generation_with_mock():
    generator = SQLGenerator(client=FakeClient())
    retrieval = RetrievalResult(
        domain="domain_alpha",
        tables=[
            TableMetadata(
                schema="TEST_SCHEMA",
                name="TEST_TABLE",
                description="",
                domain="domain_alpha",
                columns=[],
            )
        ],
        relationships=[],
        examples=[],
    )
    sql = asyncio.run(generator.generate("consulta demo", retrieval))
    assert sql.lower().startswith("select")


class CapturingClient:
    def __init__(self) -> None:
        self.last_user_prompt = ""

    async def chat_completion(self, **kwargs):
        self.last_user_prompt = kwargs["user_prompt"]
        return "SELECT 1 FROM DUAL"


def test_sql_prompt_includes_fixed_filter_relationship_hint():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="clientes",
        tables=[
            TableMetadata(schema="SAC", name="CLIENTES", description="", domain="clientes", columns=[]),
            TableMetadata(schema="SAC", name="MULTITABLA", description="", domain="clientes", columns=[]),
        ],
        relationships=[
            RelationshipMetadata(
                left_table="SAC.CLIENTES",
                left_column="ESTADO_CLIENTE",
                right_table="SAC.MULTITABLA",
                right_column="CODIGO_NUM",
                fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
            )
        ],
        examples=[],
        parametric_mappings=[
            ParametricMapping(
                source_table="SAC.CLIENTES",
                source_column="ESTADO_CLIENTE",
                lookup_table="SAC.MULTITABLA",
                lookup_key="CODIGO_NUM",
                lookup_description="DESCRIPCION",
                fixed_filter="SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
            )
        ],
        auxiliary_semantic_context=["SAC.CLIENTES.ESTADO_CLIENTE comment_hint: CLI_ESTADO confidence=low note=auxiliary_only"],
    )
    asyncio.run(generator.generate("estado cliente", retrieval))
    assert "fixed_filter: SAC.MULTITABLA.TABLA = 'CLI_ESTADO'" in client.last_user_prompt
    assert "NO autorizan joins ni mappings por si solos" in client.last_user_prompt
    assert "clientes por X" in client.last_user_prompt
    assert "COUNT(...)" in client.last_user_prompt
    assert "GROUP BY X" in client.last_user_prompt
    assert "NLSSORT(TRIM(campo_textual), 'NLS_SORT=BINARY_AI')" in client.last_user_prompt
    assert "UPPER(TRIM(campo_textual)) = UPPER(TRIM('valor'))" in client.last_user_prompt
    assert "No aplicar UPPER/TRIM a columnas numericas" in client.last_user_prompt
    assert "NLSSORT(TRIM(MT.DESCRIPCION), 'NLS_SORT=BINARY_AI')" in client.last_user_prompt
    assert "'estado suministro' => SAC.CLIENTES.ESTADO_SUMINISTRO" in client.last_user_prompt
    assert "'estado facturacion' => SAC.CLIENTES.ESTADO_FACTURACION" in client.last_user_prompt
    assert "Regla de estado cliente con valor de negocio (obligatoria)" in client.last_user_prompt
    assert "Nunca usar CLI.ESTADO_CLIENTE = 1" in client.last_user_prompt
    assert "Regla de ranking/superlativo (obligatoria)" in client.last_user_prompt


def test_extract_sql_from_markdown_block():
    text = "```sql\nSELECT ID FROM SAC.CLIENTES;\n```"
    assert _extract_select_sql(text) == "SELECT ID FROM SAC.CLIENTES"


def test_extract_sql_from_explanation_plus_select():
    text = "Aqui esta la consulta:\nSELECT MUNICIPIO, COUNT(*) FROM SAC.CLIENTES GROUP BY MUNICIPIO;"
    assert _extract_select_sql(text).startswith("SELECT MUNICIPIO")


def test_extract_sql_returns_none_when_missing_select():
    assert _extract_select_sql("No tengo SQL para esto.") is None


class MunicipioPromptClient:
    def __init__(self) -> None:
        self.last_user_prompt = ""

    async def chat_completion(self, **kwargs):
        self.last_user_prompt = kwargs["user_prompt"]
        return "```sql\nSELECT COUNT(*) FROM SAC.CLIENTES C JOIN SAC.MUNICIPIOS M ON C.MUNICIPIO = M.MUNICIPIO WHERE UPPER(TRIM(M.DESCRIPCION)) = UPPER(TRIM('Armenia'))\n```"


def test_prompt_contains_municipio_rule_and_no_text_on_numeric_code():
    client = MunicipioPromptClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="clientes",
        tables=[
            TableMetadata(schema="SAC", name="CLIENTES", description="", domain="clientes", columns=[]),
            TableMetadata(schema="SAC", name="MUNICIPIOS", description="", domain="clientes", columns=[]),
        ],
        relationships=[],
        examples=[],
    )
    sql = asyncio.run(generator.generate("usuarios en armenia", retrieval))
    assert "JOIN SAC.MUNICIPIOS" in sql
    assert "UPPER(TRIM(M.DESCRIPCION))" in sql
    assert "UPPER(TRIM(C.MUNICIPIO))" not in sql
    assert "No comparar texto contra SAC.CLIENTES.MUNICIPIO" in client.last_user_prompt


def test_generated_sql_matches_extracted_trace():
    class BlockClient:
        async def chat_completion(self, **kwargs):
            return "```sql\nSELECT COUNT(*) FROM SAC.CLIENTES\n```"

    generator = SQLGenerator(client=BlockClient())
    retrieval = RetrievalResult(
        domain="clientes",
        tables=[TableMetadata(schema="SAC", name="CLIENTES", description="", domain="clientes", columns=[])],
        relationships=[],
        examples=[],
    )
    trace = asyncio.run(generator.generate_with_trace("q", retrieval))
    generated_sql = asyncio.run(generator.generate("q", retrieval))
    assert generated_sql == trace.extracted_sql


class MedidoresMunicipioClient:
    def __init__(self) -> None:
        self.last_user_prompt = ""

    async def chat_completion(self, **kwargs):
        self.last_user_prompt = kwargs["user_prompt"]
        return (
            "SELECT M.DESCRIPCION, COUNT(MED.MEDIDOR_ID) AS CANTIDAD_MEDIDORES "
            "FROM SAC.MEDIDORES MED "
            "JOIN SAC.CLIENTES C ON MED.CLIENTE_ID = C.CLIENTE_ID "
            "JOIN SAC.MUNICIPIOS M ON C.MUNICIPIO = M.MUNICIPIO "
            "GROUP BY M.DESCRIPCION"
        )


def test_medidores_por_municipio_sql_uses_chain_and_no_multitabla():
    client = MedidoresMunicipioClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="medidores",
        tables=[
            TableMetadata(schema="SAC", name="MEDIDORES", description="", domain="medidores", columns=[]),
            TableMetadata(schema="SAC", name="CLIENTES", description="", domain="clientes", columns=[]),
            TableMetadata(schema="SAC", name="MUNICIPIOS", description="", domain="clientes", columns=[]),
        ],
        relationships=[
            RelationshipMetadata(left_table="SAC.MEDIDORES", left_column="CLIENTE_ID", right_table="SAC.CLIENTES", right_column="CLIENTE_ID"),
            RelationshipMetadata(left_table="SAC.CLIENTES", left_column="MUNICIPIO", right_table="SAC.MUNICIPIOS", right_column="MUNICIPIO"),
        ],
        examples=[],
    )
    sql = asyncio.run(generator.generate("Cuantos medidores hay por municipio", retrieval))
    assert "JOIN SAC.CLIENTES" in sql
    assert "JOIN SAC.MUNICIPIOS" in sql
    assert "MULTITABLA" not in sql
    assert "COUNT(MED.MEDIDOR_ID)" in sql or "COUNT(*)" in sql
    assert "Join paths aprobados:" in client.last_user_prompt
    assert "SAC.MEDIDORES.CLIENTE_ID = SAC.CLIENTES.CLIENTE_ID" in client.last_user_prompt
    assert "SAC.CLIENTES.MUNICIPIO = SAC.MUNICIPIOS.MUNICIPIO" in client.last_user_prompt
    assert "Regla de cadena aprobada (obligatoria para medidores por municipio)" in client.last_user_prompt


class StaticEstadoClient:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.last_user_prompt = ""

    async def chat_completion(self, **kwargs):
        self.last_user_prompt = kwargs["user_prompt"]
        return self.sql


def _medidores_estado_retrieval() -> RetrievalResult:
    return RetrievalResult(
        domain="medidores",
        tables=[TableMetadata(schema="SAC", name="MEDIDORES", description="", domain="medidores", columns=[])],
        relationships=[],
        examples=[],
        static_value_mappings=[
            {
                "table": "SAC.MEDIDORES",
                "column": "ESTADO",
                "values": {
                    "I": {"label": "Instalado", "synonyms": ["activo", "instalado"]},
                    "R": {"label": "Retirado", "synonyms": ["inactivo", "retirado"]},
                },
            }
        ],
    )


def test_medidores_activos_uses_estado_i():
    client = StaticEstadoClient("SELECT COUNT(*) FROM SAC.MEDIDORES MED WHERE MED.ESTADO = 'I'")
    generator = SQLGenerator(client=client)
    sql = asyncio.run(generator.generate("Cuantos medidores activos hay", _medidores_estado_retrieval()))
    assert "ESTADO = 'I'" in sql.upper()
    assert "MULTITABLA" not in sql.upper()
    assert "Static value mappings:" in client.last_user_prompt
    assert "SAC.MEDIDORES.ESTADO" in client.last_user_prompt


def test_medidores_instalados_uses_estado_i():
    client = StaticEstadoClient("SELECT COUNT(*) FROM SAC.MEDIDORES MED WHERE MED.ESTADO = 'I'")
    generator = SQLGenerator(client=client)
    sql = asyncio.run(generator.generate("Cuantos medidores instalados hay", _medidores_estado_retrieval()))
    assert "ESTADO = 'I'" in sql.upper()
    assert "MULTITABLA" not in sql.upper()


def test_medidores_retirados_uses_estado_r():
    client = StaticEstadoClient("SELECT COUNT(*) FROM SAC.MEDIDORES MED WHERE MED.ESTADO = 'R'")
    generator = SQLGenerator(client=client)
    sql = asyncio.run(generator.generate("Cuantos medidores retirados hay", _medidores_estado_retrieval()))
    assert "ESTADO = 'R'" in sql.upper()
    assert "MULTITABLA" not in sql.upper()


def test_medidores_inactivos_uses_estado_r():
    client = StaticEstadoClient("SELECT COUNT(*) FROM SAC.MEDIDORES MED WHERE MED.ESTADO = 'R'")
    generator = SQLGenerator(client=client)
    sql = asyncio.run(generator.generate("Cuantos medidores inactivos hay", _medidores_estado_retrieval()))
    assert "ESTADO = 'R'" in sql.upper()
    assert "MULTITABLA" not in sql.upper()


def test_medidores_por_estado_no_multitabla_and_case_mapping():
    client = StaticEstadoClient(
        "SELECT CASE MED.ESTADO WHEN 'I' THEN 'Instalado' WHEN 'R' THEN 'Retirado' ELSE MED.ESTADO END AS ESTADO_LABEL, COUNT(*) "
        "FROM SAC.MEDIDORES MED GROUP BY CASE MED.ESTADO WHEN 'I' THEN 'Instalado' WHEN 'R' THEN 'Retirado' ELSE MED.ESTADO END"
    )
    generator = SQLGenerator(client=client)
    sql = asyncio.run(generator.generate("Cuantos medidores hay por estado", _medidores_estado_retrieval()))
    assert "MULTITABLA" not in sql.upper()
    assert "CASE MED.ESTADO" in sql.upper()
    assert "WHEN 'I' THEN 'INSTALADO'" in sql.upper()
    assert "WHEN 'R' THEN 'RETIRADO'" in sql.upper()


def test_prompt_contains_rule_for_exact_count_users_with_two_meters():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="medidores",
        tables=[TableMetadata(schema="SAC", name="MEDIDORES", description="", domain="medidores", columns=[])],
        relationships=[],
        examples=[],
    )
    asyncio.run(generator.generate("Cantidad de usuarios con dos medidores instalados", retrieval))
    assert "Regla de conteo exacto de entidades con condicion de cardinalidad" in client.last_user_prompt
    assert "HAVING COUNT(MED.MEDIDOR_ID) = 2" in client.last_user_prompt
    assert "COUNT(*) AS CANTIDAD_USUARIOS" in client.last_user_prompt
    assert "Si la pregunta usa 'mas de N' medidores, usa HAVING COUNT(MED.MEDIDOR_ID) > N." in client.last_user_prompt
    assert "Si la pregunta dice 'mas de dos', interpreta N=2." in client.last_user_prompt


def test_prompt_includes_cardinality_skeleton_when_pattern_detected():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="medidores",
        tables=[TableMetadata(schema="SAC", name="MEDIDORES", description="", domain="medidores", columns=[])],
        relationships=[],
        examples=[],
        detected_query_pattern={
            "type": "entity_count_with_cardinality_condition",
            "entity": "clientes",
            "related_entity": "medidores",
            "operator": ">",
            "threshold": 2,
            "sql_skeleton": "SELECT COUNT(*) AS TOTAL FROM ( SELECT <ENTITY_ID> FROM ... GROUP BY <ENTITY_ID> HAVING COUNT(<RELATED_ID>) > 2 ) Q",
        },
    )
    asyncio.run(generator.generate("cantidad de usuarios con mas de dos medidores", retrieval))
    prompt_lower = client.last_user_prompt.lower()
    assert "sql skeleton obligatorio" in prompt_lower
    assert "debes respetarlo exactamente" in prompt_lower
    assert "no reemplazar por count(distinct ...)" in prompt_lower


def test_prompt_contains_mandatory_estado_filter_rule_for_superlative():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="medidores",
        tables=[TableMetadata(schema="SAC", name="MEDIDORES", description="", domain="medidores", columns=[])],
        relationships=[],
        examples=[],
        static_value_mappings=[
            {
                "table": "SAC.MEDIDORES",
                "column": "ESTADO",
                "values": {
                    "I": {"label": "Instalado", "synonyms": ["activo", "instalado"]},
                    "R": {"label": "Retirado", "synonyms": ["inactivo", "retirado"]},
                },
            }
        ],
    )
    asyncio.run(generator.generate("Marca de medidor con mas medidores instalados", retrieval))
    assert "Regla de filtro de estado de medidores (obligatoria)" in client.last_user_prompt
    assert "filtra con MED.ESTADO = 'I'" in client.last_user_prompt
    assert "consultas de ranking/superlativo" in client.last_user_prompt


def test_prompt_includes_resolved_lookup_values_rule():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="procesos",
        tables=[
            TableMetadata(schema="SAC", name="PROCESOS", description="", domain="procesos", columns=[]),
            TableMetadata(schema="SAC", name="MULTITABLA", description="", domain="procesos", columns=[]),
        ],
        relationships=[],
        examples=[],
        parametric_mappings=[
            ParametricMapping(
                source_table="SAC.PROCESOS",
                source_column="ESTADO",
                lookup_table="SAC.MULTITABLA",
                lookup_key="CODIGO_CAR",
                lookup_description="DESCRIPCION",
                fixed_filter="SAC.MULTITABLA.TABLA = 'PRO_ESTADO'",
            )
        ],
        resolved_lookup_values=[
            ResolvedLookupValue(
                source_table="SAC.PROCESOS",
                source_column="ESTADO",
                lookup_table="SAC.MULTITABLA",
                lookup_description="DESCRIPCION",
                fixed_filter_value="PRO_ESTADO",
                canonical_value="Tramite",
                matched_synonym="en tramite",
                valid_values=["Tramite", "Finalizado"],
            )
        ],
    )
    asyncio.run(generator.generate("cantidad de procesos con estado en tramite", retrieval))
    assert "Regla de resolved_lookup_values (obligatoria)" in client.last_user_prompt
    assert "Tramite" in client.last_user_prompt
    assert "NLS_SORT=BINARY_AI" in client.last_user_prompt


def test_prompt_includes_resolved_numeric_filters_rule():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="procesos",
        tables=[TableMetadata(schema="SAC", name="PROCESOS", description="", domain="procesos", columns=[])],
        relationships=[],
        examples=[],
        resolved_numeric_filters=[
            {
                "source_table": "SAC.PROCESOS",
                "source_column": "PROCESO",
                "operator": "=",
                "value": "4106",
                "value_type": "string",
                "entity": "procesos",
                "matched_text": "procesos 4106",
                "forbidden_columns": ["CODIGO_CUENTA", "NUMERO_PROCESO", "TIPO_TRAMITE"],
            }
        ],
    )
    asyncio.run(generator.generate("cuantos procesos 4106 entraron por municipio", retrieval))
    assert "Regla de resolved_numeric_filters (obligatoria)" in client.last_user_prompt
    assert "SAC.PROCESOS.PROCESO = '4106'" in client.last_user_prompt
    assert "CODIGO_CUENTA" in client.last_user_prompt


def test_prompt_includes_intent_guardrails():
    client = CapturingClient()
    generator = SQLGenerator(client=client)
    retrieval = RetrievalResult(
        domain="clientes",
        tables=[TableMetadata(schema="SAC", name="CLIENTES", description="", domain="clientes", columns=[])],
        relationships=[],
        examples=[],
        intent_guardrails=[
            "No inferir 'conectado(s)' como SAC.CLIENTES.ESTADO_SUMINISTRO sin aclaracion del usuario."
        ],
    )
    asyncio.run(generator.generate("usuarios conectados", retrieval))
    assert "Guardrails de intencion (obligatorios)" in client.last_user_prompt
    assert "No inferir 'conectado(s)'" in client.last_user_prompt
