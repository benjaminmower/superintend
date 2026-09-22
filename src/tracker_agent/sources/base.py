"""TrackerSource: the interface every adapter implements.

Feature code (flags, brief, report, RAG, backtest) is written only
against this interface and core.models — never against a source's
native shape, and never imports sources/gsheets/ or anything else
source-specific directly. Swapping trackers means writing one adapter
here and passing tests/contract/.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from tracker_agent.core.capabilities import Capability
from tracker_agent.core.models import (
    Annotation,
    Answer,
    Brief,
    Change,
    ParseResult,
    Question,
    SourceHealth,
    WriteResult,
)


class TrackerSource(ABC):
    """A tracker data source: Google Sheets, a CSV export, Procore, etc."""

    name: str
    capabilities: Capability

    @abstractmethod
    def health(self) -> SourceHealth:
        """Check the source is reachable and parseable with confidence.

        A bad parse or an expired token must show up here so a run stops
        instead of writing junk — never raise mid-write.
        """
        ...

    @abstractmethod
    def items(self, project: str) -> ParseResult:
        """Every current item for a project, plus any parse warnings. Requires READ_ITEMS."""
        ...

    @abstractmethod
    def history(self, project: str, since: dt.date | None = None) -> list[Change]:
        """Change history for a project, optionally since a date. Requires READ_HISTORY."""
        ...

    @abstractmethod
    def write_annotations(
        self, project: str, annotations: list[Annotation], *, dry_run: bool
    ) -> WriteResult:
        """Write agent-owned item fields (e.g. flag, next_action). Requires WRITE_ANNOTATIONS."""
        ...

    @abstractmethod
    def write_brief(self, brief: Brief, *, dry_run: bool) -> WriteResult:
        """Rewrite the fully agent-owned brief. Requires WRITE_BRIEF."""
        ...

    @abstractmethod
    def questions(self, project: str | None = None) -> list[Question]:
        """Unanswered questions (the Ask-tab equivalent). May be empty. Requires QUESTIONS."""
        ...

    @abstractmethod
    def answer_question(self, question_id: str, answer: Answer, *, dry_run: bool) -> WriteResult:
        """Write an answer back to a question. Requires QUESTIONS."""
        ...
