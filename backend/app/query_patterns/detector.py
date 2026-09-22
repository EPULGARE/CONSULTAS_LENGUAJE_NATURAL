from __future__ import annotations

import re

from app.query_patterns.models import DetectedQueryPattern
from app.query_patterns.skeletons import attach_skeleton

_NUMBER_WORDS = {
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


def _extract_number(question: str) -> int | None:
    match = re.search(r"\b(\d+)\b", question)
    if match:
        return int(match.group(1))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", question):
            return value
    return None


def _extract_top_n(question: str) -> int | None:
    match = re.search(r"\btop\s+(\d+)\b", question)
    if match:
        return int(match.group(1))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\btop\s+{word}\b", question):
            return value
    return None


def _extract_cardinality_threshold(question: str) -> int | None:
    patterns = (
        r"\bmas de\s+(\d+)\b",
        r"\bmÃ¡s de\s+(\d+)\b",
        r"\bmenos de\s+(\d+)\b",
        r"\bigual a\s+(\d+)\b",
        r"\bexactamente\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            return int(match.group(1))
    for word, value in _NUMBER_WORDS.items():
        word_patterns = (
            rf"\bmas de\s+{word}\b",
            rf"\bmÃ¡s de\s+{word}\b",
            rf"\bmenos de\s+{word}\b",
            rf"\bigual a\s+{word}\b",
            rf"\bexactamente\s+{word}\b",
        )
        if any(re.search(pattern, question) for pattern in word_patterns):
            return value
    return None


def detect_query_pattern(question: str) -> DetectedQueryPattern | None:
    q = f" {question.lower()} "

    if re.search(r"\bnumero\s+de\s+proceso\b|\bnúmero\s+de\s+proceso\b|\bnro\s+de\s+proceso\b", q):
        return None

    has_user_entity = any(token in q for token in (" usuario ", " usuarios ", " cliente ", " clientes "))
    has_meter_entity = any(token in q for token in (" medidor ", " medidores ", " contador ", " contadores "))
    has_count_intent = any(token in q for token in (" cantidad ", " cuantos ", " cuÃ¡nto ", " cuantos ", " numero ", " nÃºmero "))
    has_ranking_intent = any(token in q for token in (" top ", " ranking ", " mayor cantidad "))

    operator = ""
    if " mas de " in q or " mÃ¡s de " in q:
        operator = ">"
    elif " menos de " in q:
        operator = "<"
    elif " igual a " in q or " exactamente " in q:
        operator = "="

    threshold = _extract_cardinality_threshold(q)
    top_n = _extract_top_n(q)

    if has_ranking_intent and has_user_entity and has_meter_entity and operator and threshold is not None:
        return attach_skeleton(
            DetectedQueryPattern(
                type="ranking_top_n",
                entity="clientes",
                related_entity="medidores",
                operator=operator,
                threshold=threshold,
                top_n=top_n or 10,
            )
        )

    if has_user_entity and has_meter_entity and has_count_intent and operator and threshold is not None:
        return attach_skeleton(
            DetectedQueryPattern(
                type="entity_count_with_cardinality_condition",
                entity="clientes",
                related_entity="medidores",
                operator=operator,
                threshold=threshold,
            )
        )

    if has_ranking_intent:
        return attach_skeleton(DetectedQueryPattern(type="ranking_top_n", top_n=top_n or 1))

    # "cerradas por los usuarios X" identifies an actor, not a GROUP BY.
    # Keep any other "por" (e.g. "por mes") as an aggregation dimension.
    grouping_question = re.sub(
        r"\b(?:cerrad[oa]s?|terminad[oa]s?|finalizad[oa]s?|realizad[oa]s?|"
        r"ejecutad[oa]s?|atendid[oa]s?|respondid[oa]s?)\s+por\b",
        " ",
        q,
    )
    if has_count_intent and " por " in grouping_question:
        return attach_skeleton(DetectedQueryPattern(type="grouped_aggregation"))

    if any(token in q for token in (" municipio ", " ciudad ", " armenia ", " calarca ", " calarcÃ¡ ")):
        return attach_skeleton(DetectedQueryPattern(type="municipality_filter"))

    if any(token in q for token in (" estado cliente ", " clientes activos ", " cliente activo ", " estado de cliente ")):
        return attach_skeleton(DetectedQueryPattern(type="parametric_status_filter"))

    if any(token in q for token in (" descripcion ", " descripciÃ³n ", " nombre de ", " significado ")):
        return attach_skeleton(DetectedQueryPattern(type="descriptive_lookup"))

    return None
