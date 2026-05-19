from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings
from app.relationship_feedback.models import (
    DetectedRelationshipJoin,
    RelationshipCandidate,
    RelationshipCandidateReview,
    RelationshipCandidateWriteResult,
)


def generated_candidates_path(metadata_path: Path | None = None) -> Path:
    base = (metadata_path or settings.metadata_path).resolve()
    return base / "generated" / "relationship_candidates.yml"


def review_candidates_path(metadata_path: Path | None = None) -> Path:
    base = (metadata_path or settings.metadata_path).resolve()
    return base / "approvals" / "relationship_candidates_review.yml"


def load_candidate_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"candidate_relationships": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"candidate_relationships": []}


def write_candidate_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def record_relationship_candidates(
    candidates: list[DetectedRelationshipJoin],
    *,
    question: str,
    blocked_reason: str,
    source: str = "sql_generation_blocked",
    metadata_path: Path | None = None,
) -> RelationshipCandidateWriteResult:
    metadata_root = (metadata_path or settings.metadata_path).resolve()
    output_path = generated_candidates_path(metadata_root)
    payload = load_candidate_payload(output_path)
    existing_items = [
        item if isinstance(item, RelationshipCandidate) else RelationshipCandidate(**item)
        for item in payload.get("candidate_relationships", [])
    ]

    written: list[RelationshipCandidate] = []
    for detected in candidates:
        new_item = RelationshipCandidate(
            from_table=detected.from_table,
            from_column=detected.from_column,
            to_table=detected.to_table,
            to_column=detected.to_column,
            source=source,
            first_seen_question=question,
            blocked_reason=blocked_reason,
            approved=False,
        )
        index = _find_existing_candidate(existing_items, new_item)
        if index is None:
            existing_items.append(new_item)
            written.append(new_item)
            continue
        current = existing_items[index]
        merged = current.model_copy(
            update={
                "source": current.source or source,
                "first_seen_question": current.first_seen_question or question,
                "blocked_reason": blocked_reason or current.blocked_reason,
            }
        )
        existing_items[index] = merged
        written.append(merged)

    write_candidate_payload(
        output_path,
        {"candidate_relationships": [item.model_dump(mode="json") for item in existing_items]},
    )
    return RelationshipCandidateWriteResult(
        output_path=_display_path(output_path, metadata_root),
        review_path=_display_path(review_candidates_path(metadata_root), metadata_root),
        candidates=written,
    )


def write_review_payload(path: Path, reviews: list[RelationshipCandidateReview]) -> None:
    write_candidate_payload(path, {"candidate_relationships": [item.model_dump(mode="json") for item in reviews]})


def _find_existing_candidate(existing_items: list[RelationshipCandidate], new_item: RelationshipCandidate) -> int | None:
    for idx, item in enumerate(existing_items):
        same_direction = (
            item.from_table == new_item.from_table
            and item.from_column == new_item.from_column
            and item.to_table == new_item.to_table
            and item.to_column == new_item.to_column
        )
        reverse_direction = (
            item.from_table == new_item.to_table
            and item.from_column == new_item.to_column
            and item.to_table == new_item.from_table
            and item.to_column == new_item.from_column
        )
        if same_direction or reverse_direction:
            return idx
    return None


def _display_path(path: Path, metadata_root: Path) -> str:
    try:
        return str(path.relative_to(metadata_root.parent))
    except ValueError:
        return str(path)
