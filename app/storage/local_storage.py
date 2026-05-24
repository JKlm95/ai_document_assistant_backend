import hashlib
import re
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from app.storage.base import StoredFile

CHUNK_SIZE_BYTES = 1024 * 1024


class LocalStorageService:
    def __init__(
        self,
        *,
        storage_root: Path,
        max_upload_size_bytes: int,
        allowed_extensions: set[str],
        allowed_mime_types: set[str],
    ) -> None:
        self._storage_root = storage_root.resolve()
        self._max_upload_size_bytes = max_upload_size_bytes
        self._allowed_extensions = {
            extension.lower().lstrip(".") for extension in allowed_extensions
        }
        self._allowed_mime_types = {mime_type.lower() for mime_type in allowed_mime_types}

    async def save_upload(
        self,
        *,
        upload_file: UploadFile,
        owner_id: UUID,
        document_id: UUID,
    ) -> StoredFile:
        original_filename = sanitize_filename(upload_file.filename)
        file_extension = _extract_extension(original_filename)
        mime_type = (upload_file.content_type or "").lower()

        self._validate_upload_metadata(file_extension=file_extension, mime_type=mime_type)

        document_dir = self._document_dir(owner_id=owner_id, document_id=document_id)
        document_dir.mkdir(parents=True, exist_ok=True)
        final_path = document_dir / f"original.{file_extension}"
        temporary_path = document_dir / f"{final_path.name}.tmp"

        if final_path.exists() or temporary_path.exists():
            raise StorageConflictError

        file_hash = hashlib.sha256()
        total_size = 0

        try:
            with temporary_path.open("xb") as output:
                while chunk := await upload_file.read(CHUNK_SIZE_BYTES):
                    total_size += len(chunk)
                    if total_size > self._max_upload_size_bytes:
                        raise UploadTooLargeError
                    file_hash.update(chunk)
                    output.write(chunk)

            if total_size == 0:
                raise EmptyUploadError

            temporary_path.replace(final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            self._remove_empty_parent_dirs(document_dir)
            raise

        return StoredFile(
            original_filename=original_filename,
            mime_type=mime_type,
            file_size_bytes=total_size,
            file_extension=file_extension,
            content_hash=file_hash.hexdigest(),
            storage_path=str(final_path.relative_to(self._storage_root).as_posix()),
        )

    def delete_path(self, storage_path: str) -> None:
        path = self.resolve_path(storage_path)
        path.unlink(missing_ok=True)
        self._remove_empty_parent_dirs(path.parent)

    def resolve_path(self, storage_path: str) -> Path:
        candidate_path = (self._storage_root / storage_path).resolve()
        if not candidate_path.is_relative_to(self._storage_root):
            raise InvalidStoragePathError
        return candidate_path

    def _document_dir(self, *, owner_id: UUID, document_id: UUID) -> Path:
        return self._storage_root / "documents" / str(owner_id) / str(document_id)

    def _validate_upload_metadata(self, *, file_extension: str, mime_type: str) -> None:
        if file_extension not in self._allowed_extensions:
            raise UnsupportedUploadTypeError
        if mime_type not in self._allowed_mime_types:
            raise UnsupportedUploadTypeError

    def _remove_empty_parent_dirs(self, start_dir: Path) -> None:
        current_dir = start_dir
        while current_dir != self._storage_root and self._storage_root in current_dir.parents:
            try:
                current_dir.rmdir()
            except OSError:
                break
            current_dir = current_dir.parent


def sanitize_filename(filename: str | None) -> str:
    raw_name = Path(filename or "document").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    if not sanitized:
        return "document"

    path = Path(sanitized)
    suffix = path.suffix[:20]
    stem = path.stem[: 255 - len(suffix)]
    return f"{stem}{suffix}"


def _extract_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower().lstrip(".")
    if not extension:
        raise UnsupportedUploadTypeError
    return extension


class UploadValidationError(Exception):
    """Base class for upload validation errors."""


class UnsupportedUploadTypeError(UploadValidationError):
    """Raised when uploaded file extension or MIME type is not allowed."""


class UploadTooLargeError(UploadValidationError):
    """Raised when uploaded file exceeds configured size limit."""


class EmptyUploadError(UploadValidationError):
    """Raised when uploaded file has no content."""


class StorageConflictError(UploadValidationError):
    """Raised when generated storage path already exists."""


class InvalidStoragePathError(Exception):
    """Raised when a stored relative path escapes the storage root."""
