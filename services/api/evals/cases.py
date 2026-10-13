"""Eval cases (YAML in evals/cases/) and the dataset version.

Every case has an id, a category and `holdout` (holdout cases are kept out of prompt writing
and reported separately). Classification cases call the classifier directly; every other
category runs the widget pipeline turn by turn (`turns`; knowledge cases use `question`).
"""

import hashlib
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
FIXTURES_DIR = EVALS_DIR / "fixtures"
KB_DIR = FIXTURES_DIR / "kb"
REPORTS_DIR = EVALS_DIR / "reports"

Category = Literal["classification", "knowledge", "unanswerable", "agent", "safety", "small_talk"]
CATEGORIES: tuple[str, ...] = (
    "classification",
    "knowledge",
    "unanswerable",
    "agent",
    "safety",
    "small_talk",
)
PIPELINE_CATEGORIES = frozenset(CATEGORIES) - {"classification"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Turn(_Model):
    role: Literal["customer", "assistant"]
    content: str


class ClassificationExpect(_Model):
    intent: str
    priority: list[str] = Field(min_length=1)
    needs_human: bool


class KnowledgeExpect(_Model):
    source: str  # fixture file stem, e.g. "returns"
    facts: list[str] = Field(min_length=1)


class PipelineExpect(_Model):
    """Checks on a pipeline case's outcome. Unset fields aren't checked."""

    route: list[str] | None = None  # acceptable routes of the final reply
    ticket: bool | None = None
    tools: dict[str, str] = {}  # tool -> a status at least one call must have
    forbid_tools: dict[str, str] = {}  # tool -> a status no call may have
    actions_proposed: list[str] = []  # proposals the drafting job must create
    actions_absent: list[str] = []  # proposals it must not create
    orders_unchanged: list[str] = []  # also checked globally: nothing is ever executed
    reply_contains_any: list[str] = []
    reply_excludes: list[str] = []
    max_reply_chars: int | None = None


class _CaseBase(_Model):
    id: str = Field(pattern=r"^[a-z]+-[a-z0-9]+$")
    holdout: bool = False
    lang: Literal["en", "roman_urdu", "mixed"] = "en"


class ClassificationCase(_CaseBase):
    category: Literal["classification"]
    message: str
    context: list[Turn] = []
    expect: ClassificationExpect


class KnowledgeCase(_CaseBase):
    category: Literal["knowledge"]
    question: str
    expect: KnowledgeExpect

    @property
    def turns(self) -> list[str]:
        return [self.question]


class PipelineCase(_CaseBase):
    category: Literal["unanswerable", "agent", "safety", "small_talk"]
    turns: list[str] = Field(min_length=1)
    orders_in_scope: list[str] = []
    # Run the drafting job once a ticket is open (refund/cancel proposals come from there).
    draft: bool = False
    expect: PipelineExpect

    @model_validator(mode="after")
    def _draft_checks_need_draft(self) -> "PipelineCase":
        if (self.expect.actions_proposed or self.expect.actions_absent) and not self.draft:
            raise ValueError(f"{self.id}: action checks need draft: true")
        return self


Case = Annotated[ClassificationCase | KnowledgeCase | PipelineCase, Field(discriminator="category")]
_CASES = TypeAdapter(list[Case])


def load_cases(
    cases_dir: Path = CASES_DIR,
) -> list[ClassificationCase | KnowledgeCase | PipelineCase]:
    cases: list[ClassificationCase | KnowledgeCase | PipelineCase] = []
    for path in sorted(cases_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        cases.extend(_CASES.validate_python(raw))
    ids = [c.id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate case ids: {duplicates}")
    known_sources = {p.stem for p in KB_DIR.glob("*.md")}
    for case in cases:
        if isinstance(case, KnowledgeCase) and case.expect.source not in known_sources:
            raise ValueError(f"{case.id}: unknown source {case.expect.source!r}")
    return cases


def select_cases(
    cases: list, *, categories: list[str] | None = None, limit: int | None = None
) -> list:
    """Filter by category, then keep at most `limit` cases per category (in file order), so a
    small run still touches every category."""
    chosen = [c for c in cases if not categories or c.category in categories]
    if limit is None:
        return chosen
    seen: dict[str, int] = {}
    kept = []
    for case in chosen:
        seen[case.category] = seen.get(case.category, 0) + 1
        if seen[case.category] <= limit:
            kept.append(case)
    return kept


def dataset_version(evals_dir: Path = EVALS_DIR) -> str:
    """A hash of every case and fixture file (path + bytes): changes whenever the data does,
    independent of git."""
    digest = hashlib.sha256()
    files = sorted(
        p
        for folder in (evals_dir / "cases", evals_dir / "fixtures")
        for p in folder.rglob("*")
        if p.is_file()
    )
    for path in files:
        digest.update(path.relative_to(evals_dir).as_posix().encode())
        digest.update(b"\0")
        # Line endings normalised, so a Windows checkout hashes like a Linux one.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()[:12]
