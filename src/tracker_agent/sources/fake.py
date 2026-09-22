"""In-memory TrackerSource. Ships with the repo; powers tests and the demo."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from tracker_agent.core.capabilities import Capability, requires
from tracker_agent.core.models import (
    Annotation,
    Answer,
    Brief,
    Change,
    FieldDiff,
    Item,
    ParseResult,
    Question,
    SourceHealth,
    WriteResult,
)
from tracker_agent.sources.base import TrackerSource

_AGENT_ITEM_FIELDS = {"flag", "next_action"}


@dataclass
class FakeSource(TrackerSource):
    name: str = "fake"
    capabilities: Capability = (
        Capability.READ_ITEMS
        | Capability.READ_HISTORY
        | Capability.WRITE_ANNOTATIONS
        | Capability.WRITE_BRIEF
        | Capability.QUESTIONS
    )
    _items: dict[str, list[Item]] = field(default_factory=dict)
    _changes: dict[str, list[Change]] = field(default_factory=dict)
    _questions: dict[str, list[Question]] = field(default_factory=dict)
    # item_id -> field -> value
    _annotations: dict[str, dict[str, str]] = field(default_factory=dict)
    _briefs: dict[str, Brief] = field(default_factory=dict)
    _answers: dict[str, Answer] = field(default_factory=dict)
    healthy: bool = True

    def seed_items(self, project: str, items: list[Item]) -> None:
        self._items[project] = items

    def seed_changes(self, project: str, changes: list[Change]) -> None:
        self._changes[project] = changes

    def seed_questions(self, project: str, questions: list[Question]) -> None:
        self._questions[project] = questions

    def health(self) -> SourceHealth:
        return SourceHealth(ok=self.healthy, detail="" if self.healthy else "seeded unhealthy")

    def items(self, project: str) -> ParseResult:
        requires(self.capabilities, Capability.READ_ITEMS)
        return ParseResult(items=list(self._items.get(project, [])), warnings=[])

    def history(self, project: str, since: dt.date | None = None) -> list[Change]:
        requires(self.capabilities, Capability.READ_HISTORY)
        changes = self._changes.get(project, [])
        if since is None:
            return list(changes)
        return [c for c in changes if c.timestamp is None or c.timestamp.date() >= since]

    def write_annotations(
        self, project: str, annotations: list[Annotation], *, dry_run: bool
    ) -> WriteResult:
        requires(self.capabilities, Capability.WRITE_ANNOTATIONS)
        for annotation in annotations:
            if annotation.field not in _AGENT_ITEM_FIELDS:
                raise ValueError(f"Refusing to write non-agent item field {annotation.field!r}")

        diff = []
        written = []
        for annotation in annotations:
            old_value = self._annotations.get(annotation.item_id, {}).get(annotation.field, "")
            if old_value == annotation.value:
                continue  # no-op: don't touch cells that already hold this value
            written.append(annotation)
            diff.append(
                FieldDiff(
                    item_id=annotation.item_id,
                    field=annotation.field,
                    old=old_value,
                    new=annotation.value,
                )
            )

        if not dry_run:
            for annotation in written:
                self._annotations.setdefault(annotation.item_id, {})[annotation.field] = (
                    annotation.value
                )
        return WriteResult(ok=True, written=len(written), dry_run=dry_run, diff=diff)

    def write_brief(self, brief: Brief, *, dry_run: bool) -> WriteResult:
        requires(self.capabilities, Capability.WRITE_BRIEF)
        if not dry_run:
            self._briefs[brief.project] = brief
        return WriteResult(ok=True, written=1, dry_run=dry_run)

    def questions(self, project: str | None = None) -> list[Question]:
        requires(self.capabilities, Capability.QUESTIONS)
        if project is None:
            return [q for qs in self._questions.values() for q in qs]
        return list(self._questions.get(project, []))

    def answer_question(self, question_id: str, answer: Answer, *, dry_run: bool) -> WriteResult:
        requires(self.capabilities, Capability.QUESTIONS)
        if not dry_run:
            self._answers[question_id] = answer
        return WriteResult(ok=True, written=1, dry_run=dry_run)

    # test helpers, not part of TrackerSource
    def written_annotation(self, item_id: str, field_name: str) -> str | None:
        return self._annotations.get(item_id, {}).get(field_name)

    def written_brief(self, project: str) -> Brief | None:
        return self._briefs.get(project)

    def written_answer(self, question_id: str) -> Answer | None:
        return self._answers.get(question_id)
