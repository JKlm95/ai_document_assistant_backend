from uuid import UUID

from pydantic import BaseModel, Field

from app.rag.models import AnswerStatus


class ProjectSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int | None = Field(default=None, ge=1)
    include_context: bool = True


class SourceReferenceResponse(BaseModel):
    citation_id: str
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    source_url: str | None
    page_number: int | None
    start_offset: int
    end_offset: int


class ProjectSearchResultResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    text: str
    similarity_score: float
    source_reference: SourceReferenceResponse
    metadata: dict[str, object | None]


class ProjectSearchResponse(BaseModel):
    query: str
    project_id: UUID
    results: list[ProjectSearchResultResponse]
    context: str | None
    citations: list[SourceReferenceResponse]


class ProjectAskRequest(BaseModel):
    question: str = Field(min_length=1)
    retrieval_limit: int | None = Field(default=None, ge=1)
    include_context: bool = False


class ProjectAskResponse(BaseModel):
    answer: str
    project_id: UUID
    question: str
    citations: list[SourceReferenceResponse]
    sources: list[ProjectSearchResultResponse]
    used_context: str | None = None
    confidence: float | None = None
    status: AnswerStatus
