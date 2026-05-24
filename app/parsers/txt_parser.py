from pathlib import Path

from app.parsers.base import MissingDocumentFileError, ParsedDocument, ParserError


class TextParser:
    def parse(self, path: Path, *, max_chars: int) -> ParsedDocument:
        if not path.exists() or not path.is_file():
            raise MissingDocumentFileError

        try:
            raw_content = path.read_bytes()
        except OSError as exc:
            raise ParserError("Could not read document file") from exc

        text = _decode_text(raw_content)
        text = _normalize_line_endings(text)
        return ParsedDocument(text=text[:max_chars])


def _decode_text(raw_content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1250", "latin-1"):
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_content.decode("utf-8", errors="replace")


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
