from app.parsers.base import DocumentParser, UnsupportedDocumentTypeError
from app.parsers.markdown_parser import MarkdownParser
from app.parsers.txt_parser import TextParser


class ParserRegistry:
    def __init__(self) -> None:
        text_parser = TextParser()
        markdown_parser = MarkdownParser()
        self._mime_type_parsers: dict[str, DocumentParser] = {
            "text/plain": text_parser,
            "text/markdown": markdown_parser,
            "application/markdown": markdown_parser,
        }
        self._extension_parsers: dict[str, DocumentParser] = {
            "txt": text_parser,
            "md": markdown_parser,
        }

    def get_parser(self, *, mime_type: str, file_extension: str | None) -> DocumentParser:
        normalized_mime_type = mime_type.lower()
        normalized_extension = (file_extension or "").lower().lstrip(".")

        parser = self._mime_type_parsers.get(normalized_mime_type)
        if parser is not None:
            return parser

        parser = self._extension_parsers.get(normalized_extension)
        if parser is not None:
            return parser

        raise UnsupportedDocumentTypeError
