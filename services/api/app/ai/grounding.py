"""Delimiting untrusted text for prompts, and validating [S#] citations against sources.

Customer messages, document chunks and tool results are data. Before they go into a prompt,
anything that could open or close one of our delimiter tags is escaped, so text inside a
block can never pretend to end it.
"""

import re

from app.modules.conversations.schemas import Citation
from app.modules.knowledge.retrieval import RetrievedChunk

SNIPPET_CHARS = 600

# [S1], [S1, S3] and [S1][S2] all count; anything else in brackets is left alone.
CITATION_GROUP = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")
_SOURCE_ID = re.compile(r"S\d+")
# Text that could close or open our delimiters inside untrusted content.
_DELIMITERS = re.compile(
    r"<(/?)(sources?|customer_message|tool_result|ticket|conversation|message)\b",
    re.IGNORECASE,
)


def neutralize(value: str) -> str:
    return _DELIMITERS.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", value)


def attr(value: str) -> str:
    escaped = value.replace("&", "&amp;").replace('"', "&quot;").replace("\n", " ")
    return neutralize(escaped)


def source_id(index: int) -> str:
    return f"S{index + 1}"


def format_source(index: int, chunk: RetrievedChunk) -> str:
    section = " > ".join(chunk.heading_path)
    return (
        f'<source id="{source_id(index)}" title="{attr(chunk.document_title)}"'
        f' section="{attr(section)}">\n{neutralize(chunk.content)}\n</source>'
    )


def strip_citations(text: str) -> str:
    """Drop [S#] markers, e.g. from earlier answers whose sources are no longer in context."""
    return CITATION_GROUP.sub("", text)


def extract_citations(text: str, sources: list[RetrievedChunk]) -> tuple[str, list[Citation]]:
    """Keep only [S#] ids that refer to `sources`; return the cleaned text and its citations."""
    by_id = {source_id(i): chunk for i, chunk in enumerate(sources)}
    cited: list[str] = []

    def keep_valid(match: re.Match[str]) -> str:
        ids = [sid for sid in _SOURCE_ID.findall(match.group(1)) if sid in by_id]
        for sid in ids:
            if sid not in cited:
                cited.append(sid)
        return "".join(f"[{sid}]" for sid in dict.fromkeys(ids))

    content = CITATION_GROUP.sub(keep_valid, text)
    content = re.sub(r"[ \t]+([.,;:!?])", r"\1", content)
    content = re.sub(r"[ \t]{2,}", " ", content).strip()
    citations = [
        Citation(
            source_id=sid,
            chunk_id=by_id[sid].chunk_id,
            document_id=by_id[sid].document_id,
            title=by_id[sid].document_title,
            heading_path=by_id[sid].heading_path,
            snippet=by_id[sid].content[:SNIPPET_CHARS],
        )
        for sid in cited
    ]
    return content, citations
