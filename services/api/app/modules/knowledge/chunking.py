"""Token-aware chunking: split on headings (sections) first, then into overlapping windows."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import tiktoken

from app.modules.knowledge.parsing import Section

ENCODING_NAME = "cl100k_base"
CHUNK_TOKENS = 500
OVERLAP_TOKENS = 60

# A word with its leading whitespace, matching how tiktoken attaches spaces to words.
_PIECE = re.compile(r"\s*\S+")


@dataclass
class Chunk:
    content: str
    token_count: int
    metadata: dict[str, Any]


@lru_cache
def get_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(ENCODING_NAME)


def count_tokens(text: str) -> int:
    return len(get_encoding().encode(text))


def _pieces(text: str, max_tokens: int) -> list[str]:
    """Split into whole words; only a single "word" longer than a chunk is cut by tokens."""
    enc = get_encoding()
    pieces: list[str] = []
    for piece in _PIECE.findall(text):
        tokens = enc.encode(piece)
        if len(tokens) <= max_tokens:
            pieces.append(piece)
        else:
            pieces.extend(
                enc.decode(tokens[i : i + max_tokens])
                for i in range(0, len(tokens), max_tokens)
            )
    return pieces


def _windows(
    text: str, chunk_tokens: int = CHUNK_TOKENS, overlap_tokens: int = OVERLAP_TOKENS
) -> list[str]:
    pieces = _pieces(text, chunk_tokens)
    if not pieces:
        return []
    sizes = [count_tokens(p) for p in pieces]

    windows: list[str] = []
    start = 0
    while start < len(pieces):
        end, total = start, 0
        while end < len(pieces) and (end == start or total + sizes[end] <= chunk_tokens):
            total += sizes[end]
            end += 1
        windows.append("".join(pieces[start:end]).strip())
        if end >= len(pieces):
            break
        # Step back over whole words until the overlap is reached, always moving forward.
        next_start, overlap = end, 0
        while next_start - 1 > start and overlap + sizes[next_start - 1] <= overlap_tokens:
            next_start -= 1
            overlap += sizes[next_start]
        start = next_start
    return windows


def chunk_sections(
    sections: list[Section],
    chunk_tokens: int = CHUNK_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        for content in _windows(section.text, chunk_tokens, overlap_tokens):
            if not content:
                continue
            chunks.append(
                Chunk(
                    content=content,
                    token_count=count_tokens(content),
                    metadata={
                        "heading_path": section.heading_path,
                        "page_number": section.page_number,
                    },
                )
            )
    return chunks
