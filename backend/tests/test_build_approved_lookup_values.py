from pathlib import Path
import shutil
import tempfile

import yaml

from scripts import build_approved_lookup_values as script


def test_load_approved_multitabla_mappings_filters_only_approved_multitabla_entries():
    temp_dir = Path(tempfile.mkdtemp(prefix="approved-lookup-build-", dir="C:/tmp"))
    try:
        curated = temp_dir / "curated"
        curated.mkdir(parents=True, exist_ok=True)
        (curated / "business_overrides.yml").write_text(
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
                            "source_table": "SAC.CLIENTES",
                            "source_column": "MUNICIPIO",
                            "lookup_table": "SAC.MUNICIPIOS",
                            "lookup_key": "MUNICIPIO",
                            "lookup_description": "DESCRIPCION",
                            "fixed_filter": "",
                        },
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        mappings = script.load_approved_multitabla_mappings(temp_dir)
        assert len(mappings) == 1
        assert mappings[0]["source_table"] == "SAC.PROCESOS"
        assert mappings[0]["fixed_filter_value"] == "PED_SOLSRV_PRO"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_build_payload_normalizes_descriptions_and_emits_warnings():
    mappings = [
        {
            "source_table": "SAC.PROCESOS",
            "source_column": "PROCESO",
            "lookup_table": "SAC.MULTITABLA",
            "lookup_key": "CODIGO_CAR",
            "lookup_description": "DESCRIPCION",
            "fixed_filter_value": "PED_SOLSRV_PRO",
        }
    ]
    rows_by_filter = {
        "PED_SOLSRV_PRO": [
            {"TABLA": "PED_SOLSRV_PRO", "CODIGO_CAR": "4106", "CODIGO_NUM": None, "DESCRIPCION": "Conexión del Servicio"},
            {"TABLA": "PED_SOLSRV_PRO", "CODIGO_CAR": "4107", "CODIGO_NUM": None, "DESCRIPCION": "Conexion  del   Servicio"},
        ]
    }
    payload = script.build_payload(mappings, rows_by_filter)
    assert payload["approved_lookup_values"][0]["values"][0]["normalized_description"] == "conexion del servicio"
    assert "conexión del servicio" in payload["approved_lookup_values"][0]["values"][0]["synonyms"]
    assert any(item.startswith("duplicate_normalized_description:") for item in payload["warnings"])


def test_build_payload_warns_when_fixed_filter_returns_no_rows():
    mappings = [
        {
            "source_table": "SAC.PROCESOS",
            "source_column": "PROCESO",
            "lookup_table": "SAC.MULTITABLA",
            "lookup_key": "CODIGO_CAR",
            "lookup_description": "DESCRIPCION",
            "fixed_filter_value": "PED_SOLSRV_PRO",
        }
    ]
    payload = script.build_payload(mappings, {"PED_SOLSRV_PRO": []})
    assert payload["approved_lookup_values"][0]["values"] == []
    assert any(item.startswith("fixed_filter_without_rows:") for item in payload["warnings"])
