from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True)
class SourceReference:
    citation_id: str
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_index: int
    source_url: str | None
    page_number: int | None
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    text: str
    similarity_score: float
    source_reference: SourceReference
    metadata: dict[str, object | None]


@dataclass(frozen=True)
class RetrievalResponse:
    query: str
    project_id: UUID
    results: list[RetrievalResult]
    context: str | None
    citations: list[SourceReference]


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    FAILED = "failed"


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    project_id: UUID
    question: str
    citations: list[SourceReference]
    sources: list[RetrievalResult]
    used_context: str | None
    confidence: float | None
    status: AnswerStatus
