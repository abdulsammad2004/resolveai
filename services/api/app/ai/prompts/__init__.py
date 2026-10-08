"""Versioned prompt files: `<name>_<version>.md` in this directory, e.g. answer_v1.md.

Prompts are never inline strings. Each LLM call records the version it used.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent
_SAFE_PART = re.compile(r"^[a-z0-9_]+$")


class PromptNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def id(self) -> str:
        """Value stored as prompt_version, e.g. `answer_v1`."""
        return f"{self.name}_{self.version}"


@lru_cache
def load_prompt(name: str, version: str) -> Prompt:
    # Names come from code, but keep them to a safe charset so a path can never escape.
    if not _SAFE_PART.match(name) or not _SAFE_PART.match(version):
        raise PromptNotFoundError(f"Invalid prompt name or version: {name!r} {version!r}")
    path = PROMPTS_DIR / f"{name}_{version}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"Prompt not found: {name}_{version}")
    return Prompt(name=name, version=version, text=path.read_text(encoding="utf-8").strip())
