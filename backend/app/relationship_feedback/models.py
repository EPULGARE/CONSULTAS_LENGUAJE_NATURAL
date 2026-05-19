from __future__ import annotations

from pydantic import BaseModel, Field


class RelationshipEvidence(BaseModel):
    sampled: bool = False
    source_distinct_count: int | None = None
    target_distinct_count: int | None = None
    matched_distinct_count: int | None = None
    reverse_matched_distinct_count: int | None = None
    coverage_percent: float | None = None
    reverse_coverage_percent: float | None = None
    null_rate_from: float | None = None
    null_rate_to: float | None = None
    from_column_type: str | None = None
    to_column_type: str | None = None
    sample_matches: list[dict[str, object]] = Field(default_factory=list)


class RelationshipCandidateScore(BaseModel):
    candidate_strength: str = "low"
    rationale: str = ""


class DetectedRelationshipJoin(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str

    @property
    def as_text(self) -> str:
        return f"{self.from_table}.{self.from_column} = {self.to_table}.{self.to_column}"


class RelationshipCandidate(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    source: str = "sql_generation_blocked"
    first_seen_question: str = ""
    blocked_reason: str = "UNAPPROVED_JOIN_PATH"
    approved: bool = False
    evidence: RelationshipEvidence = Field(default_factory=RelationshipEvidence)

    @property
    def as_text(self) -> str:
        return f"{self.from_table}.{self.from_column} = {self.to_table}.{self.to_column}"


class RelationshipCandidateReview(RelationshipCandidate):
    score: RelationshipCandidateScore = Field(default_factory=RelationshipCandidateScore)
    reviewer_notes: str = ""


class RelationshipCandidateWriteResult(BaseModel):
    output_path: str
    review_path: str
    candidates: list[RelationshipCandidate] = Field(default_factory=list)


class UnapprovedJoinPathError(ValueError):
    def __init__(self, candidates: list[DetectedRelationshipJoin]) -> None:
        super().__init__("UNAPPROVED_JOIN_PATH")
        self.error_code = "UNAPPROVED_JOIN_PATH"
        self.candidates = candidates
