from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from fastapi import UploadFile


@dataclass(frozen=True)
class StoredFile:
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_extension: str
    content_hash: str
    storage_path: str


class StorageService(Protocol):
    async def save_upload(
        self,
        *,
        upload_file: UploadFile,
        owner_id: UUID,
        document_id: UUID,
    ) -> StoredFile:
        raise NotImplementedError

    def delete_path(self, storage_path: str) -> None:
        raise NotImplementedError

    def resolve_path(self, storage_path: str) -> Path:
        raise NotImplementedError
