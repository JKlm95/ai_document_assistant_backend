from datetime import UTC, datetime
from uuid import UUID

from app.models.document import Document, DocumentProcessingStatus
from app.parsers.base import ParserError
from app.parsers.registry import ParserRegistry
from app.repositories.document_repository import DocumentRepository
from app.storage.local_storage import InvalidStoragePathError, LocalStorageService


class DocumentProcessingService:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        parser_registry: ParserRegistry,
        storage_service: LocalStorageService,
        max_extracted_text_chars: int,
    ) -> None:
        self._document_repository = document_repository
        self._parser_registry = parser_registry
        self._storage_service = storage_service
        self._max_extracted_text_chars = max_extracted_text_chars

    async def process_document(self, *, document_id: UUID, owner_id: UUID) -> Document:
        document = await self._get_owned_document(document_id=document_id, owner_id=owner_id)
        if document.processing_status == DocumentProcessingStatus.PROCESSING:
            raise DocumentAlreadyProcessingError

        await self._mark_processing(document)

        try:
            if document.storage_path is None:
                raise DocumentProcessingError("Document has no stored file")

            file_path = self._storage_service.resolve_path(document.storage_path)
            parser = self._parser_registry.get_parser(
                mime_type=document.mime_type,
                file_extension=document.file_extension,
            )
            parsed_document = parser.parse(file_path, max_chars=self._max_extracted_text_chars)
        except (ParserError, InvalidStoragePathError, OSError, Exception) as exc:
            await self._mark_failed(document, str(exc) or exc.__class__.__name__)
            return document

        document.extracted_text = parsed_document.text
        document.extracted_text_length = parsed_document.text_length
        document.processed_at = datetime.now(UTC)
        document.processing_error = None
        document.processing_status = DocumentProcessingStatus.READY
        await self._document_repository.commit()
        await self._document_repository.refresh(document)
        return document

    async def get_document_content(self, *, document_id: UUID, owner_id: UUID) -> Document:
        return await self._get_owned_document(document_id=document_id, owner_id=owner_id)

    async def _get_owned_document(self, *, document_id: UUID, owner_id: UUID) -> Document:
        document = await self._document_repository.get_by_id(document_id)
        if document is None or document.owner_id != owner_id:
            raise DocumentNotFoundError
        return document

    async def _mark_processing(self, document: Document) -> None:
        document.processing_status = DocumentProcessingStatus.PROCESSING
        document.processing_error = None
        await self._document_repository.commit()
        await self._document_repository.refresh(document)

    async def _mark_failed(self, document: Document, error_message: str) -> None:
        document.processing_status = DocumentProcessingStatus.FAILED
        document.processing_error = error_message[:2000]
        document.processed_at = None
        await self._document_repository.commit()
        await self._document_repository.refresh(document)


class DocumentNotFoundError(Exception):
    """Raised when a document does not exist or is not owned by the user."""


class DocumentAlreadyProcessingError(Exception):
    """Raised when a document is already being processed."""


class DocumentProcessingError(Exception):
    """Raised when a document cannot be processed."""
