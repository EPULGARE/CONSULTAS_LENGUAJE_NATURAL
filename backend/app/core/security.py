import re
import unicodedata


_whitespace_re = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).strip()
    return _whitespace_re.sub(" ", normalized)
