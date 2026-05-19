from scripts.extract_oracle_comments import detect_parametric_hint


def test_detect_hint_from_brackets():
    hint, confidence = detect_parametric_hint("Estado cliente [CLI_ESTADO]")
    assert hint == "CLI_ESTADO"
    assert confidence == "low"


def test_detect_hint_from_parametrizado_en():
    hint, confidence = detect_parametric_hint("Parametro parametrizado en TBL_XYZ")
    assert hint == "TBL_XYZ"
    assert confidence == "low"


def test_detect_hint_from_codes_descriptions():
    hint, confidence = detect_parametric_hint("Campo de codigo y descripcion")
    assert hint == "CODES_DESCRIPTIONS_HINT"
    assert confidence == "low"
