from pathlib import Path
import shutil
import tempfile

import yaml

from app.semantic_normalization import SemanticNormalizer


def _write_numeric_metadata(root: Path, *, with_process_lookup: bool) -> None:
    (root / "curated").mkdir(parents=True, exist_ok=True)
    approved = []
    if with_process_lookup:
        approved.append(
            {
                "source_table": "SAC.PROCESOS",
                "source_column": "PROCESO",
                "lookup_table": "SAC.MULTITABLA",
                "lookup_key": "CODIGO_CAR",
                "lookup_description": "DESCRIPCION",
                "fixed_filter": "SAC.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
            }
        )
    (root / "curated" / "business_overrides.yml").write_text(
        yaml.safe_dump({"approved_parametric_mappings": approved, "static_value_mappings": []}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "curated" / "numeric_entity_mappings.yml").write_text(
        yaml.safe_dump(
            {
                "numeric_entity_mappings": [
                    {
                        "entity": "procesos",
                        "source_table": "SAC.PROCESOS",
                        "default_code_column": "PROCESO",
                        "code_type": "string",
                        "business_terms": ["proceso", "procesos", "tramite", "tramites", "pqr"],
                        "forbidden_columns_for_entity_code": ["CODIGO_CUENTA", "NUMERO_PROCESO", "TIPO_TRAMITE"],
                        "explicit_column_terms": [
                            {"source_column": "CODIGO_CUENTA", "code_type": "number", "terms": ["codigo cuenta"]}
                        ],
                        "description_lookup": {
                            "enabled": True,
                            "use_approved_parametric_mapping_only": True,
                            "source_column": "PROCESO",
                            "preferred_description_column": "SAC.MULTITABLA.DESCRIPCION",
                            "required_fixed_filter": "PED_SOLSRV_PRO",
                        },
                    },
                    {
                        "entity": "clientes",
                        "source_table": "SAC.CLIENTES",
                        "default_code_column": "CLIENTE_ID",
                        "code_type": "number",
                        "business_terms": ["cliente", "clientes", "usuario", "usuarios"],
                        "forbidden_columns_for_entity_code": ["CODIGO_CUENTA", "CONSECUTIVO"],
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_procesos_4106_resolves_to_proceso_code_column():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("Cuantos procesos 4106 entraron por municipio en mayo del 2026")
    assert result.resolved_numeric_filters
    item = result.resolved_numeric_filters[0]
    assert item.source_table == "SAC.PROCESOS"
    assert item.source_column == "PROCESO"
    assert item.value == "4106"
    assert item.value_type == "string"
    assert "CODIGO_CUENTA" in item.forbidden_columns
    assert "NUMERO_PROCESO" in item.forbidden_columns
    assert "TIPO_TRAMITE" in item.forbidden_columns


def test_clientes_12345_resolves_to_cliente_id():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("clientes 12345")
    item = result.resolved_numeric_filters[0]
    assert item.source_table == "SAC.CLIENTES"
    assert item.source_column == "CLIENTE_ID"
    assert item.value == "12345"
    assert item.value_type == "number"


def test_procesos_codigo_cuenta_12345_uses_explicit_column():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("procesos con codigo cuenta 12345")
    item = result.resolved_numeric_filters[0]
    assert item.source_table == "SAC.PROCESOS"
    assert item.source_column == "CODIGO_CUENTA"
    assert item.value == "12345"
    assert item.value_type == "number"


def test_descripcion_del_proceso_4106_marks_lookup_unavailable_without_approved_mapping(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="numeric-entity-", dir="C:/tmp"))
    try:
        _write_numeric_metadata(temp_dir, with_process_lookup=False)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        normalizer = SemanticNormalizer()
        result = normalizer.normalize("descripcion del proceso 4106")
        item = result.resolved_numeric_filters[0]
        assert item.source_column == "PROCESO"
        assert item.description_lookup_available is False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_descripcion_del_proceso_4106_marks_lookup_available_when_mapping_is_approved(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="numeric-entity-", dir="C:/tmp"))
    try:
        _write_numeric_metadata(temp_dir, with_process_lookup=True)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        normalizer = SemanticNormalizer()
        result = normalizer.normalize("descripcion del proceso 4106")
        item = result.resolved_numeric_filters[0]
        assert item.description_lookup_available is True
        assert item.lookup_table == "SAC.MULTITABLA"
        assert item.lookup_description == "DESCRIPCION"
        assert item.fixed_filter_value == "PED_SOLSRV_PRO"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
