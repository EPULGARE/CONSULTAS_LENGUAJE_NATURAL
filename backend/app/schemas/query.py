from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    user_id: str = Field(min_length=2, max_length=100)
    dry_run: bool | None = None
    conversation_id: str | None = Field(default=None, max_length=100)
    clarification_answer: str | None = Field(default=None, max_length=200)
