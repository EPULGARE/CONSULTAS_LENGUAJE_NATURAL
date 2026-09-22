from pathlib import Path
import shutil
import uuid

from app.semantic_catalog.loader import SemanticCatalogLoader


def test_loader_supports_empty_catalog():
    metadata_path = Path("backend/tests/_tmp") / str(uuid.uuid4()) / "metadata"
    try:
        metadata_path.mkdir(parents=True, exist_ok=True)

        (metadata_path / "domains.yml").write_text("domains: []\n", encoding="utf-8")
        (metadata_path / "tables.yml").write_text("tables: []\n", encoding="utf-8")
        (metadata_path / "relationships.yml").write_text("relationships: []\n", encoding="utf-8")
        (metadata_path / "examples.yml").write_text("examples: {}\n", encoding="utf-8")

        loader = SemanticCatalogLoader(metadata_path)
        assert loader.load_domains() == []
        assert loader.load_tables() == []
        assert loader.load_relationships() == []
        assert loader.load_examples() == {}
    finally:
        shutil.rmtree(metadata_path.parent, ignore_errors=True)


def test_loader_applies_business_overrides():
    metadata_path = Path("backend/tests/_tmp") / str(uuid.uuid4()) / "metadata"
    try:
        (metadata_path / "curated").mkdir(parents=True, exist_ok=True)
        (metadata_path / "domains.yml").write_text("domains: []\n", encoding="utf-8")
        (metadata_path / "relationships.yml").write_text("relationships: []\n", encoding="utf-8")
        (metadata_path / "examples.yml").write_text("examples: {}\n", encoding="utf-8")
        (metadata_path / "tables.yml").write_text(
            """
tables:
  - schema: TEST_SCHEMA
    name: TEST_TABLE
    description: ""
    domain: raw_domain
    columns:
      - name: ID
        type: number
      - name: SECRET_COL
        type: varchar
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (metadata_path / "curated" / "business_overrides.yml").write_text(
            """
tables:
  TEST_SCHEMA.TEST_TABLE:
    domain: curated_domain
    allowed_for_query: false
    sensitive_columns:
      - SECRET_COL
    columns:
      SECRET_COL:
        allowed_for_select: false
""".strip()
            + "\n",
            encoding="utf-8",
        )

        loader = SemanticCatalogLoader(metadata_path)
        tables = loader.load_tables()
        assert len(tables) == 1
        assert tables[0].domain == "curated_domain"
        assert tables[0].allowed_for_query is False
        assert "SECRET_COL" in tables[0].sensitive_columns
        secret = next(column for column in tables[0].columns if column.name == "SECRET_COL")
        assert secret.sensitive is True
        assert secret.allowed_for_select is False
    finally:
        shutil.rmtree(metadata_path.parent, ignore_errors=True)


def test_loader_supports_manual_tables_and_relationships():
    metadata_path = Path("backend/tests/_tmp") / str(uuid.uuid4()) / "metadata"
    try:
        (metadata_path / "curated").mkdir(parents=True, exist_ok=True)
        (metadata_path / "domains.yml").write_text("domains: []\n", encoding="utf-8")
        (metadata_path / "relationships.yml").write_text("relationships: []\n", encoding="utf-8")
        (metadata_path / "examples.yml").write_text("examples: {}\n", encoding="utf-8")
        (metadata_path / "tables.yml").write_text(
            """
tables:
  - schema: SAC
    name: CLIENTES
    description: ""
    domain: clientes
    columns:
      - name: ESTADO_CLIENTE
        type: NUMBER
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (metadata_path / "curated" / "business_overrides.yml").write_text(
            """
manual_tables:
  - schema: SAC
    name: MULTITABLA
    description: "manual"
    domain: clientes
    allowed_for_query: true
    columns:
      - name: TABLA
        type: VARCHAR2
      - name: CODIGO_NUM
        type: NUMBER
      - name: DESCRIPCION
        type: VARCHAR2
        allowed_for_select: true
manual_relationships:
  - left_table: SAC.CLIENTES
    left_column: ESTADO_CLIENTE
    right_table: SAC.MULTITABLA
    right_column: CODIGO_NUM
    fixed_filter: "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'"
""".strip()
            + "\n",
            encoding="utf-8",
        )

        loader = SemanticCatalogLoader(metadata_path)
        tables = loader.load_tables()
        rels = loader.load_relationships()
        names = {t.full_name for t in tables}
        assert "SAC.MULTITABLA" in names
        assert any(r.fixed_filter == "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'" for r in rels)
    finally:
        shutil.rmtree(metadata_path.parent, ignore_errors=True)


def test_loader_supports_oracle_comments():
    metadata_path = Path("backend/tests/_tmp") / str(uuid.uuid4()) / "metadata"
    try:
        (metadata_path / "generated").mkdir(parents=True, exist_ok=True)
        (metadata_path / "generated" / "oracle_comments.yml").write_text(
            """
tables:
  SAC.CLIENTES:
    table_comment: "Tabla de clientes"
    columns:
      ESTADO_CLIENTE:
        comment: "Estado [CLI_ESTADO]"
        detected_parametric_hint: CLI_ESTADO
        confidence: low
""".strip()
            + "\n",
            encoding="utf-8",
        )
        loader = SemanticCatalogLoader(metadata_path)
        comments = loader.load_oracle_comments()
        assert "SAC.CLIENTES" in comments["tables"]
        assert comments["tables"]["SAC.CLIENTES"]["columns"]["ESTADO_CLIENTE"]["detected_parametric_hint"] == "CLI_ESTADO"
    finally:
        shutil.rmtree(metadata_path.parent, ignore_errors=True)


def test_loader_supports_static_value_mappings():
    metadata_path = Path("backend/tests/_tmp") / str(uuid.uuid4()) / "metadata"
    try:
        (metadata_path / "curated").mkdir(parents=True, exist_ok=True)
        (metadata_path / "curated" / "business_overrides.yml").write_text(
            """
static_value_mappings:
  - table: SAC.MEDIDORES
    column: ESTADO
    values:
      I:
        label: Instalado
        synonyms: [activo]
      R:
        label: Retirado
        synonyms: [inactivo]
""".strip()
            + "\n",
            encoding="utf-8",
        )
        loader = SemanticCatalogLoader(metadata_path)
        mappings = loader.load_static_value_mappings()
        assert len(mappings) == 1
        assert mappings[0].table == "SAC.MEDIDORES"
        assert mappings[0].column == "ESTADO"
        assert mappings[0].values["I"].label == "Instalado"
    finally:
        shutil.rmtree(metadata_path.parent, ignore_errors=True)


def test_loader_supports_generated_approved_lookup_values():
    metadata_path = Path("backend/tests/_tmp") / str(uuid.uuid4()) / "metadata"
    try:
        (metadata_path / "generated").mkdir(parents=True, exist_ok=True)
        (metadata_path / "generated" / "approved_lookup_values.yml").write_text(
            """
approved_lookup_values:
  - source_table: SAC.PROCESOS
    source_column: PROCESO
    lookup_table: SAC.MULTITABLA
    lookup_key: CODIGO_CAR
    lookup_description: DESCRIPCION
    fixed_filter_value: PED_SOLSRV_PRO
    values:
      - code: "4106"
        description: "Conexion del Servicio"
        normalized_description: "conexion del servicio"
        synonyms:
          - conexion del servicio
          - conexión del servicio
""".strip()
            + "\n",
            encoding="utf-8",
        )
        loader = SemanticCatalogLoader(metadata_path)
        entries = loader.load_approved_lookup_values()
        assert len(entries) == 1
        assert entries[0].source_table == "SAC.PROCESOS"
        assert entries[0].values[0].code == "4106"
    finally:
        shutil.rmtree(metadata_path.parent, ignore_errors=True)

def test_a2_approved_sensitivity_classification_is_exact():
    loader = SemanticCatalogLoader(Path("metadata"))
    tables = {table.full_name: table for table in loader.load_tables()}

    medidores = tables["SAC.MEDIDORES"]
    columns = {column.name: column for column in medidores.columns}

    approved_sensitive = {"IP", "IMEI", "CODIGO_AUTENTICACION"}
    reviewed_non_sensitive = {"NRO_TELEFONICO", "APN"}

    assert set(medidores.sensitive_columns) == approved_sensitive
    for name in approved_sensitive:
        assert columns[name].sensitive is True
        assert columns[name].allowed_for_select is False
    for name in reviewed_non_sensitive:
        assert columns[name].sensitive is False
        assert columns[name].allowed_for_select is True

    procesos = tables["SAC.PROCESOS"]
    process_columns = {column.name: column for column in procesos.columns}
    for name in {"CEDULA_SOL", "CLIENTE_ID", "OBSERVACION", "USER_SISTEMA"}:
        assert process_columns[name].sensitive is False
        assert process_columns[name].allowed_for_select is True

