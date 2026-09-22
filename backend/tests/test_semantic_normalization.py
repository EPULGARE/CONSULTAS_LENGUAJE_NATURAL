from pathlib import Path
import shutil
import tempfile

import yaml

from app.core.config import settings
from app.semantic_normalization import SemanticNormalizer


def test_clientes_activos_normalizes_to_estado_cliente_activo():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("clientes activos")
    assert "activos -> estado cliente activo" in result.normalized_terms
    assert any("SAC.CLIENTES.ESTADO_CLIENTE" in item and "CLI_ESTADO='Activo'" in item for item in result.applied_governed_rules)
    assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)
    assert result.unresolved_ambiguities == []


def test_usuarios_vigentes_normalizes_to_clientes_activos():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("usuarios vigentes")
    assert "vigentes -> estado cliente activo" in result.normalized_terms
    assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)


def test_medidores_retirados_use_static_mapping():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("medidores retirados")
    assert "MED.ESTADO='R'" in result.resolved_filters
    assert any("SAC.MEDIDORES.ESTADO='R'" == item for item in result.applied_governed_rules)


def test_medidores_activos_use_installed_static_mapping():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("medidores activos")
    assert "MED.ESTADO='I'" in result.resolved_filters
    assert result.unresolved_ambiguities == []


def test_clientes_activos_con_medidores_retirados_resolve_both_without_ambiguity():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("clientes activos con mas de dos medidores retirados")
    assert "estado cliente activo (mapping aprobado)" in result.resolved_filters
    assert "MED.ESTADO='R'" in result.resolved_filters
    assert result.unresolved_ambiguities == []


def test_clientes_conectados_stays_governed_but_unresolved_without_canonical_value():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("clientes conectados")
    assert "conectados (missing_governed_canonical_value)" in result.skipped_normalizations
    assert result.resolved_lookup_values == []


def test_clientes_activos_por_municipio_keeps_nominal_status_not_superlative():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("top 10 clientes activos por municipio")
    assert "activos -> estado cliente activo" in result.normalized_terms
    assert "mas activos" not in result.normalized_question.lower()


def test_operational_verbs_keep_ambiguity():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("usuarios activos que consumen mas energia")
    assert "activos => cliente o medidor" in result.unresolved_ambiguities
    assert "activos (operational_context)" in result.skipped_normalizations


def test_activos_sin_entidad_clara_keeps_ambiguity():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("activos por municipio")
    assert "activos => cliente o medidor" in result.unresolved_ambiguities


def test_procesos_4601_adds_resolved_numeric_filter():
    normalizer = SemanticNormalizer()
    result = normalizer.normalize("Cuantos procesos 4601 entraron por municipio en 2026")
    assert any(item.source_table == "SAC.PROCESOS" and item.source_column == "PROCESO" and item.value == "4601" for item in result.resolved_numeric_filters)


def test_procesos_conexion_del_servicio_resolves_from_generated_approved_lookup_values(monkeypatch):
    temp_dir = Path(tempfile.mkdtemp(prefix="approved-lookups-"))
    try:
        (temp_dir / "curated").mkdir(parents=True, exist_ok=True)
        (temp_dir / "generated").mkdir(parents=True, exist_ok=True)
        (temp_dir / "curated" / "business_overrides.yml").write_text(
            yaml.safe_dump(
                {
                    "approved_parametric_mappings": [
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "PROCESO",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_CAR",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter": "SAC.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
                        }
                    ],
                    "static_value_mappings": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (temp_dir / "generated" / "approved_lookup_values.yml").write_text(
            yaml.safe_dump(
                {
                    "approved_lookup_values": [
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "PROCESO",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_CAR",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter_value": "PED_SOLSRV_PRO",
                            "values": [
                                {
                                    "code": "4106",
                                    "description": "Conexion del Servicio",
                                    "normalized_description": "conexion del servicio",
                                    "synonyms": ["conexion del servicio", "conexión del servicio"],
                                }
                            ],
                        }
                    ]
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        normalizer = SemanticNormalizer()
        result = normalizer.normalize("Cuantos procesos Conexión del Servicio entraron por municipio en mayo del 2026")
        assert any(item.canonical_value == "Conexion del Servicio" for item in result.resolved_lookup_values)
        lookup = result.resolved_lookup_values[0]
        assert lookup.code == "4106"
        assert lookup.fixed_filter_value == "PED_SOLSRV_PRO"
        assert lookup.resolution_source == "approved_lookup_values"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_generated_approved_lookup_values_do_not_auto_resolve_cross_mapping_duplicates(monkeypatch):
    temp_dir = Path(tempfile.mkdtemp(prefix="approved-lookups-"))
    try:
        (temp_dir / "curated").mkdir(parents=True, exist_ok=True)
        (temp_dir / "generated").mkdir(parents=True, exist_ok=True)
        (temp_dir / "curated" / "business_overrides.yml").write_text(
            yaml.safe_dump(
                {
                    "approved_parametric_mappings": [
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "PROCESO",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_CAR",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter": "SAC.MULTITABLA.TABLA = 'PED_SOLSRV_PRO'",
                        },
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "TIPO",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_CAR",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter": "SAC.MULTITABLA.TABLA = 'PRO_TIPO'",
                        },
                    ],
                    "static_value_mappings": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (temp_dir / "generated" / "approved_lookup_values.yml").write_text(
            yaml.safe_dump(
                {
                    "approved_lookup_values": [
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "PROCESO",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_CAR",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter_value": "PED_SOLSRV_PRO",
                            "values": [
                                {
                                    "code": "4106",
                                    "description": "Conexion del Servicio",
                                    "normalized_description": "conexion del servicio",
                                    "synonyms": ["conexion del servicio"],
                                }
                            ],
                        },
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "TIPO",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_CAR",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter_value": "PRO_TIPO",
                            "values": [
                                {
                                    "code": "ABC",
                                    "description": "Conexion del Servicio",
                                    "normalized_description": "conexion del servicio",
                                    "synonyms": ["conexion del servicio"],
                                }
                            ],
                        },
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        normalizer = SemanticNormalizer()
        result = normalizer.normalize("Cuantos procesos conexion del servicio entraron por municipio")
        assert result.resolved_lookup_values == []
        assert any(item.startswith("approved_lookup_value_ambiguous:") for item in result.unresolved_ambiguities)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_generated_approved_lookup_values_do_not_override_clientes_activos(monkeypatch):
    temp_dir = Path(tempfile.mkdtemp(prefix="approved-lookups-"))
    try:
        (temp_dir / "curated").mkdir(parents=True, exist_ok=True)
        (temp_dir / "generated").mkdir(parents=True, exist_ok=True)
        (temp_dir / "curated" / "business_overrides.yml").write_text(
            yaml.safe_dump(
                {
                    "approved_parametric_mappings": [
                        {
                            "source_table": "SAC.CLIENTES",
                            "source_column": "ESTADO_CLIENTE",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_NUM",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter": "SAC.MULTITABLA.TABLA = 'CLI_ESTADO'",
                        }
                    ],
                    "static_value_mappings": [],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (temp_dir / "generated" / "approved_lookup_values.yml").write_text(
            yaml.safe_dump(
                {
                    "approved_lookup_values": [
                        {
                            "source_table": "SAC.CLIENTES",
                            "source_column": "ESTADO_CLIENTE",
                            "lookup_table": "SAC.MULTITABLA",
                            "lookup_key": "CODIGO_NUM",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter_value": "CLI_ESTADO",
                            "values": [
                                {
                                    "code": "1",
                                    "description": "Activo",
                                    "normalized_description": "activo",
                                    "synonyms": ["activo"],
                                }
                            ],
                        }
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        normalizer = SemanticNormalizer()
        result = normalizer.normalize("clientes activos")
        assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)
        assert all(item.resolution_source != "approved_lookup_values" for item in result.resolved_lookup_values)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
