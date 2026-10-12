"""File type detection and text extraction for knowledge documents.

Files are untrusted input: types are checked by extension AND content, and parse errors
surface as short, user-safe messages (never the underlying library's error text).
"""

import io
import re
import zipfile
from dataclasses import dataclass, field

from docx import Document as DocxDocument
from pypdf import PdfReader

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"
MD = "text/markdown"

EXTENSION_TYPES = {".pdf": PDF, ".docx": DOCX, ".txt": TXT, ".md": MD}
# Refuse DOCX archives that would inflate beyond this (zip-bomb guard).
MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_FENCE = re.compile(r"^\s*(```|~~~)")
_DOCX_HEADING = re.compile(r"^Heading\s+(\d)$", re.IGNORECASE)
_INLINE_WS = re.compile(r"[ \t\f\v ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class UnsupportedFileType(Exception):
    pass


class ParseError(Exception):
    """Raised with a user-safe message when a file has no usable text."""


@dataclass
class Section:
    text: str
    heading_path: list[str] = field(default_factory=list)
    page_number: int | None = None


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [_INLINE_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _decode_utf8(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def detect_mime_type(filename: str, data: bytes) -> str:
    """Return our canonical MIME type, or raise UnsupportedFileType.

    The extension must be allowed and the content must match it. The client's
    Content-Type header is ignored.
    """
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    mime = EXTENSION_TYPES.get(ext)
    if mime is None:
        raise UnsupportedFileType("Only .pdf, .docx, .txt and .md files are supported")

    if mime == PDF:
        ok = b"%PDF-" in data[:1024]
    elif mime == DOCX:
        ok = _is_docx(data)
    else:
        ok = _decode_utf8(data) is not None
    if not ok:
        raise UnsupportedFileType(f"File content does not match the {ext} extension")
    return mime


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "word/document.xml" in zf.namelist()
    except (zipfile.BadZipFile, ValueError):
        return False


def parse_document(data: bytes, mime_type: str) -> list[Section]:
    if mime_type == PDF:
        sections = _parse_pdf(data)
    elif mime_type == DOCX:
        sections = _parse_docx(data)
    elif mime_type in (TXT, MD):
        text = _decode_utf8(data)
        if text is None:
            raise ParseError("The file is not valid UTF-8 text.")
        sections = _parse_markdown(text) if mime_type == MD else [Section(text=text)]
    else:
        raise ParseError("Unsupported file type.")

    for section in sections:
        section.text = normalize_whitespace(section.text)
    sections = [s for s in sections if s.text]
    if not sections:
        raise ParseError("The document contains no extractable text.")
    return sections


def _parse_pdf(data: bytes) -> list[Section]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("Password-protected PDFs are not supported.")
        return [
            Section(text=page.extract_text() or "", page_number=number)
            for number, page in enumerate(reader.pages, start=1)
        ]
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("The PDF could not be read.") from exc


def _parse_docx(data: bytes) -> list[Section]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if sum(i.file_size for i in zf.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ParseError("The DOCX file is too large once uncompressed.")
        doc = DocxDocument(io.BytesIO(data))
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("The DOCX file could not be read.") from exc

    sections: list[Section] = []
    path: list[str] = []
    lines: list[str] = []

    def flush() -> None:
        if lines:
            sections.append(Section(text="\n\n".join(lines), heading_path=list(path)))
            lines.clear()

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style is not None else ""
        level = 1 if style == "Title" else None
        if match := _DOCX_HEADING.match(style):
            level = int(match.group(1))
        if level is not None:
            flush()
            path = path[: level - 1] + [text]
        else:
            lines.append(text)
    flush()
    return sections


def _parse_markdown(text: str) -> list[Section]:
    sections: list[Section] = []
    path: list[str] = []
    lines: list[str] = []
    in_fence = False

    def flush() -> None:
        if any(line.strip() for line in lines):
            sections.append(Section(text="\n".join(lines), heading_path=list(path)))
        lines.clear()

    for line in text.splitlines():
        if _MD_FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and (match := _MD_HEADING.match(line)):
            flush()
            level = len(match.group(1))
            path = path[: level - 1] + [match.group(2)]
            continue
        lines.append(line)
    flush()
    return sections
