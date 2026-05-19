from __future__ import annotations

from app.relationship_feedback.models import RelationshipCandidate, RelationshipCandidateScore


def score_candidate_relationship(candidate: RelationshipCandidate) -> RelationshipCandidateScore:
    evidence = candidate.evidence
    from_kind = _type_kind(evidence.from_column_type)
    to_kind = _type_kind(evidence.to_column_type)
    if from_kind != "unknown" and to_kind != "unknown" and from_kind != to_kind:
        return RelationshipCandidateScore(
            candidate_strength="invalid",
            rationale=f"Tipos incompatibles: {evidence.from_column_type} vs {evidence.to_column_type}",
        )

    coverage = evidence.coverage_percent
    reverse = evidence.reverse_coverage_percent
    if coverage is None or reverse is None:
        return RelationshipCandidateScore(
            candidate_strength="low",
            rationale="Sin evidencia suficiente para puntuar la relacion.",
        )

    strength = "low"
    if coverage >= 0.95 and reverse >= 0.5:
        strength = "high"
    elif 0.70 <= coverage < 0.95:
        strength = "medium"

    if _has_many_nulls(evidence.null_rate_from) or _has_many_nulls(evidence.null_rate_to):
        strength = _downgrade(strength)

    return RelationshipCandidateScore(
        candidate_strength=strength,
        rationale=(
            f"coverage={coverage:.4f}, reverse_coverage={reverse:.4f}, "
            f"null_rate_from={_fmt(evidence.null_rate_from)}, null_rate_to={_fmt(evidence.null_rate_to)}"
        ),
    )


def _type_kind(type_name: str | None) -> str:
    normalized = (type_name or "").strip().upper()
    if not normalized:
        return "unknown"
    if any(token in normalized for token in ("NUMBER", "INTEGER", "FLOAT", "DECIMAL")):
        return "numeric"
    if any(token in normalized for token in ("CHAR", "CLOB", "TEXT", "VARCHAR")):
        return "text"
    return "other"


def _has_many_nulls(value: float | None) -> bool:
    return value is not None and value > 0.5


def _downgrade(value: str) -> str:
    if value == "high":
        return "medium"
    if value == "medium":
        return "low"
    return value


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "null"
