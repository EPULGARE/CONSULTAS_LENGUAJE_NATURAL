from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationQuestion(BaseModel):
    id: str
    domain: str
    question: str
    clarification_answer: str | None = None
    expected_tables: list[str] = Field(default_factory=list)
    forbidden_tables: list[str] = Field(default_factory=list)
    expected_columns: list[str] = Field(default_factory=list)
    forbidden_columns: list[str] = Field(default_factory=list)
    expected_sql_contains: list[str] = Field(default_factory=list)
    forbidden_sql: list[str] = Field(default_factory=list)
    forbidden_sql_contains: list[str] = Field(default_factory=list)
    notes: str = ""
    approved: bool = False


class EvaluationFailure(BaseModel):
    id: str
    question: str
    reason: str
    detected_domain: str | None = None
    retrieved_tables: list[str] = Field(default_factory=list)
    raw_llm_response: str | None = None
    extraction_error: str | None = None
    debug_llm_prompt: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    generated_sql: str | None = None
    validated_sql: str | None = None
    missing_expected_tables: list[str] = Field(default_factory=list)
    forbidden_tables_found: list[str] = Field(default_factory=list)
    missing_expected_columns: list[str] = Field(default_factory=list)
    forbidden_columns_found: list[str] = Field(default_factory=list)
    forbidden_sql_found: list[str] = Field(default_factory=list)
    relationship_candidates: list[dict] = Field(default_factory=list)
    relationship_candidates_review_file: str | None = None


class EvaluationSuccess(BaseModel):
    id: str
    question: str
    detected_domain: str | None = None
    retrieved_tables: list[str] = Field(default_factory=list)
    raw_llm_response: str | None = None
    debug_llm_prompt: str | None = None
    generated_sql: str | None = None
    validated_sql: str | None = None


class EvaluationReport(BaseModel):
    total_questions: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    pass_rate: float = 0.0
    failures: list[EvaluationFailure] = Field(default_factory=list)
    successful_queries: list[EvaluationSuccess] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    ok: bool
    failure: EvaluationFailure | None = None
    success: EvaluationSuccess | None = None
