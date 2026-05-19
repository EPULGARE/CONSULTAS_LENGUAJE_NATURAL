import json
import uuid
from pathlib import Path

import pytest

from scripts import manual_query_debug as dbg


@pytest.fixture(autouse=True)
def _disable_intent_enhancer(monkeypatch):
    monkeypatch.setattr("scripts.manual_query_debug.settings.enable_intent_enhancer", False)


def test_resolve_output_path_blocks_outside_outputs():
    with pytest.raises(ValueError):
        dbg.resolve_output_path("metadata/out.json")


def test_resolve_output_path_inside_outputs():
    path = dbg.resolve_output_path("outputs/manual_query_debug.json")
    assert str(path).lower().endswith("outputs\\manual_query_debug.json")


def test_sanitize_hides_secrets(monkeypatch):
    monkeypatch.setattr("scripts.manual_query_debug.settings.openrouter_api_key", "sk-abc")
    monkeypatch.setattr("scripts.manual_query_debug.settings.openrouter_proxy_password", "pw1")
    monkeypatch.setattr("scripts.manual_query_debug.settings.db_password", "dbpw")
    text = dbg.sanitize_text("token sk-abc pw1 dbpw")
    assert "sk-abc" not in text
    assert "pw1" not in text
    assert "dbpw" not in text


def test_prints_prompt_when_show_prompt_true(capsys):
    dbg.print_report({"question": "q", "prompt_sent_to_openrouter": "PROMPT", "execution_skipped": True, "execution_reason": "dry_run_manual_debug"}, show_prompt=True)
    out = capsys.readouterr().out
    assert "PROMPT ENVIADO A OPENROUTER" in out


def test_no_executor_call(monkeypatch):
    called = {"executor": False}

    def fail_execute(*args, **kwargs):
        called["executor"] = True
        raise AssertionError("executor should not be called")

    monkeypatch.setattr("app.sql.executor.SQLExecutor.execute", fail_execute)
    report = dbg.run_single_question("x", show_prompt=False, forced_domain="clientes")
    assert report["execution_skipped"] is True
    assert called["executor"] is False


def test_argument_mode_with_mocks(monkeypatch):
    monkeypatch.setattr("scripts.manual_query_debug.run_single_question", lambda *args, **kwargs: {"question": "q", "execution_skipped": True, "execution_reason": "dry_run_manual_debug"})
    monkeypatch.setattr("scripts.manual_query_debug.print_report", lambda *args, **kwargs: None)
    out = Path(f"outputs/test_manual_query_debug_{uuid.uuid4().hex}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("scripts.manual_query_debug.resolve_output_path", lambda p: out)
    monkeypatch.setattr("sys.argv", ["manual_query_debug.py", "Clientes por estado", "--save-output", "outputs/manual.json"])
    assert dbg.main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["question"] == "q"


def test_detect_missing_context_table_warning():
    class _Entry:
        def __init__(self, table, keywords, business_terms):
            self.table = table
            self.keywords = keywords
            self.business_terms = business_terms

    class _Loader:
        def load_directory(self):
            return [_Entry("SAC.MEDIDORES", ["medidores"], [])]

    warnings = dbg.detect_missing_context_table_warning(
        question="Cuantos medidores hay por municipio",
        loader=_Loader(),
        final_selected_tables=["SAC.CLIENTES"],
    )
    assert any("SAC.MEDIDORES" in w for w in warnings)


def test_detect_missing_relation_warning_for_medidores_municipio():
    warnings = dbg.detect_missing_relation_warning(
        question="Cuantos medidores hay por municipio",
        retrieval_tables=["SAC.MEDIDORES"],
        relationship_pairs={("SAC.MEDIDORES", "SAC.CLIENTES")},
    )
    assert any("SAC.MEDIDORES y SAC.MUNICIPIOS" in w for w in warnings)


def test_detect_missing_relation_warning_accepts_chain_via_clientes():
    warnings = dbg.detect_missing_relation_warning(
        question="Cuantos medidores hay por municipio",
        retrieval_tables=["SAC.MEDIDORES", "SAC.CLIENTES", "SAC.MUNICIPIOS"],
        relationship_pairs={
            ("SAC.MEDIDORES", "SAC.CLIENTES"),
            ("SAC.CLIENTES", "SAC.MUNICIPIOS"),
        },
    )
    assert warnings == []


def test_detect_ambiguous_connected_warning_without_mapping():
    warnings = dbg.detect_ambiguous_connected_warning(
        question="cantidad de usuarios conectados",
        parametric_mappings=[],
    )
    assert any("Termino ambiguo: conectados" in w for w in warnings)


def test_parser_accepts_auto_accept_enhanced_intent_flag(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["manual_query_debug.py", "usuarios conectados", "--auto-accept-enhanced-intent"],
    )
    args = dbg.build_parser().parse_args()
    assert args.auto_accept_enhanced_intent is True


def test_parser_accepts_clarification_answer_flag(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["manual_query_debug.py", "usuarios activos", "--clarification-answer", "clientes"],
    )
    args = dbg.build_parser().parse_args()
    assert args.clarification_answer == "clientes"


def test_print_report_shows_intent_guardrails_and_resolved_lookup_values(capsys):
    dbg.print_report(
        {
            "question": "q",
            "normalized_terms": ["activos -> estado cliente activo"],
            "applied_governed_rules": ["SAC.CLIENTES.ESTADO_CLIENTE -> CLI_ESTADO='Activo'"],
            "skipped_normalizations": ["conectados (ambiguous)"],
            "resolved_lookup_values": [
                {"canonical_value": "Tramite"},
                {
                    "canonical_value": "Conexion del Servicio",
                    "matched_synonym": "conexion del servicio",
                    "source_table": "SAC.PROCESOS",
                    "source_column": "PROCESO",
                    "fixed_filter_value": "PED_SOLSRV_PRO",
                    "code": "4106",
                    "resolution_source": "approved_lookup_values",
                },
            ],
            "resolved_numeric_filters": [{"source_table": "SAC.PROCESOS", "source_column": "PROCESO", "value": "4106"}],
            "relationship_candidates": [
                {
                    "from_table": "SAC.CLIENTES",
                    "from_column": "CLIENTE_ID",
                    "to_table": "SAC.PROCESOS",
                    "to_column": "CODIGO_CUENTA",
                }
            ],
            "relationship_candidates_review_file": "metadata/approvals/relationship_candidates_review.yml",
            "intent_guardrails": ["No inferir conectados"],
            "table_selection_strategy": "LOCAL_ONLY",
            "used_llm_table_selection": False,
            "local_selection_confidence": 0.96,
            "local_selection_reason": "approved_join_paths + query_pattern + governed_mappings",
            "execution_skipped": True,
            "execution_reason": "dry_run_manual_debug",
        },
        show_prompt=False,
    )
    out = capsys.readouterr().out
    assert "SEMANTIC NORMALIZATION" in out
    assert "RESOLVED LOOKUP VALUES" in out
    assert "APPROVED LOOKUP VALUES MATCHES" in out
    assert "PED_SOLSRV_PRO" in out
    assert "RESOLVED NUMERIC FILTERS" in out
    assert "RELATIONSHIP CANDIDATES" in out
    assert "CODIGO_CUENTA" in out
    assert "INTENT GUARDRAILS" in out
    assert "TABLE SELECTION STRATEGY" in out
    assert "LOCAL_ONLY" in out
