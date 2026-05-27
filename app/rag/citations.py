from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.rag.models import SourceReference


def build_source_reference(
    *,
    index: int,
    document: Document,
    chunk: DocumentChunk,
) -> SourceReference:
    return SourceReference(
        citation_id=f"[{index}]",
        document_id=document.id,
        document_title=document.title,
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        source_url=document.source_url,
        page_number=None,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
    )
