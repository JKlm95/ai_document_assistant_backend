from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ParsedDocument:
    text: str

    @property
    def text_length(self) -> int:
        return len(self.text)


class DocumentParser(Protocol):
    def parse(self, path: Path, *, max_chars: int) -> ParsedDocument:
        raise NotImplementedError


class ParserError(Exception):
    """Raised when parsing fails in a controlled way."""


class UnsupportedDocumentTypeError(ParserError):
    """Raised when no parser is registered for a document."""


class MissingDocumentFileError(ParserError):
    """Raised when the stored document file does not exist."""
