import asyncio
import json
from pathlib import Path
import shutil
import tempfile

import yaml

from app.intent_enhancer import IntentEnhancer


class FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload

    async def chat_completion(self, **kwargs):
        return json.dumps(self.payload, ensure_ascii=True)


def test_usuarios_conectados_generates_ambiguity():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "Cantidad de usuarios conectados",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["usuarios"],
                "detected_filters": ["conectados"],
                "confidence": 0.97,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("usuarios conectados"))
    assert result.ambiguity_detected is True
    assert result.requires_user_confirmation is True
    assert any("conectados" in q.lower() for q in result.clarification_questions)
    assert any("conectados => cliente o medidor" == x.lower() for x in result.unresolved_ambiguities)
    assert any("no inferir 'conectado" in x.lower() for x in result.intent_guardrails)


def test_complex_question_resolves_locally_without_unnecessary_ambiguity():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "Cantidad de clientes del municipio Armenia activos con mas de dos medidores retirados",
                "ambiguity_detected": False,
                "clarification_questions": ["ruido"],
                "detected_entities": ["usuarios", "Armenia", "medidores"],
                "detected_filters": ["retirados", "mas de dos", "activos"],
                "confidence": 0.98,
            }
        )
    )
    result = asyncio.run(
        enhancer.enhance("cantidad de usuarios de armenia activos con mas de dos medidores retirados")
    )
    assert "clientes" in [x.lower() for x in result.resolved_entities]
    assert any("municipio armenia" == x.lower() for x in result.resolved_entities)
    assert any("medidores" == x.lower() for x in result.resolved_entities)
    assert any("med.estado='r'" in f.lower() for f in result.resolved_filters)
    assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)
    assert result.unresolved_ambiguities == []
    assert result.clarification_questions == []
    assert result.requires_user_confirmation is False


def test_medidores_retirados_without_ambiguity():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "Cuantos medidores retirados hay",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["medidores"],
                "detected_filters": ["retirados"],
                "confidence": 0.99,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("cuantos medidores retirados hay"))
    assert result.ambiguity_detected is False
    assert result.requires_user_confirmation is False
    assert "medidores" in result.enhanced_question.lower()
    assert "MED.ESTADO='R'" in result.resolved_filters


def test_top_clientes_activos_por_municipio_keeps_estado_cliente_activo_without_false_superlative():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "top 10 clientes activos por municipio",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["clientes", "municipio"],
                "detected_filters": ["activos"],
                "confidence": 0.96,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("top 10 clientes activos por municipio"))
    assert result.requires_user_confirmation is False
    assert "activos -> estado cliente activo" in result.normalized_terms
    assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)
    assert "mas activos" not in result.enhanced_question.lower()


def test_intent_enhancer_does_not_generate_sql():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "SELECT * FROM SAC.CLIENTES",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["clientes"],
                "detected_filters": [],
                "confidence": 0.9,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("clientes"))
    assert "select" not in result.enhanced_question.lower()
    assert "from" not in result.enhanced_question.lower()


def test_no_local_ambiguity_does_not_require_confirmation_even_with_low_confidence():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "Cuantos medidores hay por municipio",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["medidores", "municipio"],
                "detected_filters": [],
                "confidence": 0.2,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("Cuantos medidores hay por municipio"))
    assert result.requires_user_confirmation is False


def test_resolve_clarification_clientes_adds_parametric_mapping_hint():
    enhancer = IntentEnhancer(client=FakeClient({"enhanced_question": "q", "ambiguity_detected": True, "clarification_questions": ["x"], "detected_entities": [], "detected_filters": [], "confidence": 0.5}))
    intent = asyncio.run(enhancer.enhance("cantidad de usuarios activos"))
    resolved = enhancer.resolve_clarification("cantidad de usuarios activos", intent, "clientes")
    assert "CLI_ESTADO" in resolved
    assert "ESTADO_CLIENTE" in resolved


def test_resolve_clarification_medidores_adds_static_mapping_hint():
    enhancer = IntentEnhancer(client=FakeClient({"enhanced_question": "q", "ambiguity_detected": True, "clarification_questions": ["x"], "detected_entities": [], "detected_filters": [], "confidence": 0.5}))
    intent = asyncio.run(enhancer.enhance("cantidad de usuarios activos"))
    resolved = enhancer.resolve_clarification("cantidad de usuarios activos", intent, "medidores")
    assert "MEDIDORES.ESTADO='I'" in resolved


def test_resolve_clarification_clientes_for_conectados_adds_parametric_mapping_hint():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "cantidad de usuarios conectados",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["usuarios"],
                "detected_filters": ["conectados"],
                "confidence": 0.9,
            }
        )
    )
    intent = asyncio.run(enhancer.enhance("cantidad de usuarios conectados"))
    resolved = enhancer.resolve_clarification("cantidad de usuarios conectados", intent, "clientes")
    assert "CLI_ESTADO" in resolved
    assert "ESTADO_CLIENTE" in resolved


def test_resolve_clarification_ignored_when_no_active_ambiguity():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "Cuantos clientes de Calarca tienen un medidor retirado",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["clientes", "medidores", "Calarca"],
                "detected_filters": ["retirado"],
                "confidence": 0.95,
            }
        )
    )
    intent = asyncio.run(enhancer.enhance("cuantos clientes de calarca tienen un medidor retirado"))
    resolved = enhancer.resolve_clarification(
        "cuantos clientes de calarca tienen un medidor retirado",
        intent,
        "clientes",
    )
    assert "CLI_ESTADO" not in resolved


def _write_metadata_base(root: Path) -> None:
    (root / "curated").mkdir(parents=True, exist_ok=True)
    (root / "generated").mkdir(parents=True, exist_ok=True)
    (root / "curated" / "business_overrides.yml").write_text(
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
                    },
                    {
                        "source_table": "SAC.PROCESOS",
                        "source_column": "ESTADO",
                        "lookup_table": "SAC.MULTITABLA",
                        "lookup_key": "CODIGO_CAR",
                        "lookup_description": "DESCRIPCION",
                        "fixed_filter": "SAC.MULTITABLA.TABLA = 'PRO_ESTADO'",
                    },
                ],
                "static_value_mappings": [
                    {
                        "table": "SAC.MEDIDORES",
                        "column": "ESTADO",
                        "values": {
                            "I": {"label": "Instalado", "synonyms": ["activo", "instalado"]},
                            "R": {"label": "Retirado", "synonyms": ["retirado", "inactivo"]},
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "curated" / "ambiguity_rules.yml").write_text(
        yaml.safe_dump(
            {
                "ambiguities": [
                    {
                        "phrase": "activos",
                        "entity_candidates": ["SAC.CLIENTES.ESTADO_CLIENTE", "SAC.MEDIDORES.ESTADO"],
                        "approved_resolution": "",
                        "confidence": 0.0,
                        "requires_confirmation": True,
                        "observed_resolutions": {"clientes": 0, "medidores": 0},
                    },
                    {
                        "phrase": "retirados",
                        "entity_candidates": ["SAC.MEDIDORES.ESTADO"],
                        "approved_resolution": "medidores",
                        "confidence": 1.0,
                        "requires_confirmation": False,
                        "observed_resolutions": {"medidores": 0},
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "curated" / "lookup_value_normalization.yml").write_text(
        yaml.safe_dump(
            {
                "lookup_value_normalization": [
                    {
                        "source_table": "SAC.PROCESOS",
                        "source_column": "ESTADO",
                        "fixed_filter_value": "PRO_ESTADO",
                        "canonical_values": {
                            "Tramite": {
                                "synonyms": ["en tramite", "en tramite", "tramite", "tramite"]
                            },
                            "Finalizado": {
                                "synonyms": ["finalizado", "finalizados", "terminado", "cerrado"]
                            },
                        },
                    }
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def test_ambiguity_learning_updates_suggestions_without_editing_curated(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="ambiguity-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        original_rules = (temp_dir / "curated" / "ambiguity_rules.yml").read_text(encoding="utf-8")
        monkeypatch.setattr(settings, "metadata_path", temp_dir)

        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "cantidad de usuarios activos",
                    "ambiguity_detected": True,
                    "clarification_questions": [],
                    "detected_entities": ["usuarios"],
                    "detected_filters": ["activos"],
                    "confidence": 0.9,
                }
            )
        )
        intent = asyncio.run(enhancer.enhance("cantidad de usuarios activos"))
        assert intent.ambiguity_detected is True
        enhancer.resolve_clarification("cantidad de usuarios activos", intent, "clientes")

        suggestions_file = temp_dir / "generated" / "ambiguity_learning_suggestions.yml"
        assert suggestions_file.exists()
        payload = yaml.safe_load(suggestions_file.read_text(encoding="utf-8")) or {}
        assert payload["suggestions"][0]["phrase"] == "activos"
        assert payload["suggestions"][0]["selected_resolution"] == "clientes"
        assert payload["suggestions"][0]["count"] == 1
        assert (temp_dir / "curated" / "ambiguity_rules.yml").read_text(encoding="utf-8") == original_rules
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_retirados_auto_resolves_and_usuarios_activos_resolve_by_proximity(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="ambiguity-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "cantidad de usuarios activos con medidores retirados",
                    "ambiguity_detected": False,
                    "clarification_questions": [],
                    "detected_entities": ["usuarios", "medidores"],
                    "detected_filters": ["activos", "retirados"],
                    "confidence": 0.95,
                }
            )
        )
        result = asyncio.run(enhancer.enhance("cantidad de usuarios activos con medidores retirados"))
        assert any("MED.ESTADO='R'" in x for x in result.resolved_filters)
        assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)
        assert result.unresolved_ambiguities == []
        assert result.clarification_questions == []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lookup_normalization_resolves_exact(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="lookup-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "cantidad de procesos con estado en tramite",
                    "ambiguity_detected": False,
                    "clarification_questions": [],
                    "detected_entities": ["procesos"],
                    "detected_filters": ["en tramite"],
                    "confidence": 0.99,
                }
            )
        )
        result = asyncio.run(enhancer.enhance("cantidad de procesos con estado en tramite"))
        assert result.requires_user_confirmation is False
        assert result.resolved_lookup_values[0].canonical_value == "Tramite"
        assert "Tramite" in result.enhanced_question
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lookup_normalization_resolves_tilde(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="lookup-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        lookup_path = temp_dir / "curated" / "lookup_value_normalization.yml"
        lookup_path.write_text(
            yaml.safe_dump(
                {
                    "lookup_value_normalization": [
                        {
                            "source_table": "SAC.PROCESOS",
                            "source_column": "ESTADO",
                            "fixed_filter_value": "PRO_ESTADO",
                            "canonical_values": {
                                "Tramite": {
                                    "synonyms": ["en tramite", "en trámite", "tramite", "trámite"]
                                }
                            },
                        }
                    ]
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "cantidad de procesos con estado en tramite",
                    "ambiguity_detected": False,
                    "clarification_questions": [],
                    "detected_entities": ["procesos"],
                    "detected_filters": ["en tramite"],
                    "confidence": 0.99,
                }
            )
        )
        result = asyncio.run(enhancer.enhance("cantidad de procesos con estado en trámite"))
        assert result.resolved_lookup_values[0].canonical_value == "Tramite"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lookup_normalization_resolves_lowercase(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="lookup-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "procesos finalizados",
                    "ambiguity_detected": False,
                    "clarification_questions": [],
                    "detected_entities": ["procesos"],
                    "detected_filters": ["finalizados"],
                    "confidence": 0.99,
                }
            )
        )
        result = asyncio.run(enhancer.enhance("procesos finalizados"))
        assert result.resolved_lookup_values[0].canonical_value == "Finalizado"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lookup_normalization_invalid_value_requests_confirmation(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="lookup-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "cantidad de procesos con estado archivado",
                    "ambiguity_detected": False,
                    "clarification_questions": [],
                    "detected_entities": ["procesos"],
                    "detected_filters": ["archivado"],
                    "confidence": 0.99,
                }
            )
        )
        result = asyncio.run(enhancer.enhance("cantidad de procesos con estado archivado"))
        assert result.requires_user_confirmation is True
        assert result.resolved_lookup_values == []
        assert any("Tramite" in item for item in result.clarification_questions)
        assert any("Finalizado" in item for item in result.clarification_questions)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lookup_normalization_does_not_override_static_mapping(monkeypatch):
    from app.core.config import settings

    temp_dir = Path(tempfile.mkdtemp(prefix="lookup-test-", dir="C:/tmp"))
    try:
        _write_metadata_base(temp_dir)
        monkeypatch.setattr(settings, "metadata_path", temp_dir)
        enhancer = IntentEnhancer(
            client=FakeClient(
                {
                    "enhanced_question": "cuantos medidores retirados hay",
                    "ambiguity_detected": False,
                    "clarification_questions": [],
                    "detected_entities": ["medidores"],
                    "detected_filters": ["retirados"],
                    "confidence": 0.99,
                }
            )
        )
        result = asyncio.run(enhancer.enhance("cuantos medidores retirados hay"))
        assert any("MED.ESTADO='R'" in item for item in result.resolved_filters)
        assert result.resolved_lookup_values == []
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_top_clientes_activos_por_municipio_con_medidores_retirados_resolves_without_clarification():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "top 10 clientes activos por municipio con mas de dos medidores retirados",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["clientes", "medidores", "municipio"],
                "detected_filters": ["activos", "retirados", "mas de dos"],
                "confidence": 0.97,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("top 10 clientes activos por municipio con mas de dos medidores retirados"))
    assert result.requires_user_confirmation is False
    assert result.unresolved_ambiguities == []
    assert any(item.canonical_value == "Activo" for item in result.resolved_lookup_values)
    assert "MED.ESTADO='R'" in result.resolved_filters


def test_enhanced_question_preserves_cardinality_constraint_when_llm_drops_it():
    enhancer = IntentEnhancer(
        client=FakeClient(
            {
                "enhanced_question": "Cuales son los 10 clientes con mayor cantidad de medidores retirados, que se encuentren activos y agrupados por municipio",
                "ambiguity_detected": False,
                "clarification_questions": [],
                "detected_entities": ["clientes", "medidores", "municipio"],
                "detected_filters": ["activos", "retirados"],
                "confidence": 0.97,
            }
        )
    )
    result = asyncio.run(enhancer.enhance("top 10 clientes activos por municipio con mas de dos medidores retirados"))
    assert "mas de 2 medidores por cliente" in result.enhanced_question.lower()
