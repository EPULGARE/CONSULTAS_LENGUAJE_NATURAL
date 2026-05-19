from __future__ import annotations

import re
import unicodedata


CLIENT_ENTITY_TERMS = ("cliente", "clientes", "usuario", "usuarios", "abonado", "abonados")
MEDIDOR_ENTITY_TERMS = ("medidor", "medidores", "contador", "contadores")
PROCESO_ENTITY_TERMS = ("proceso", "procesos", "pqr", "pqrs")
OPERATIONAL_VERBS = ("consumen", "facturan", "usan", "generan", "reportan")
ACTIVE_TERMS = ("activo", "activos", "vigente", "vigentes")
CONNECTED_TERMS = ("conectado", "conectados")


def normalize_text(value: str) -> str:
    lowered = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(lowered.split())


def contains_phrase(question: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", question) is not None


def append_hint(question: str, hint: str) -> str:
    clean_hint = hint.strip()
    if not clean_hint or clean_hint in question:
        return question
    return f"{question}. {clean_hint}."


def extract_fixed_filter_value(fixed_filter: str) -> str:
    match = re.search(r"=\s*'([^']+)'", fixed_filter or "")
    return match.group(1) if match else ""
