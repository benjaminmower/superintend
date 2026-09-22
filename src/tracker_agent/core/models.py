"""Canonical domain model: Item, Change, Annotation, Brief, Question,
Answer, WriteResult, SourceHealth. Source-agnostic.

Every feature (flags, brief, report, RAG, backtest) is written against
these types, never against a source's native shape (a Sheets row, a
Procore RFI, a CSV line). A TrackerSource adapter's only job is to
produce/consume these. `raw` on Item keeps the source's original record
for debugging only — features must not read `raw`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class Ball(StrEnum):
    """Who has the ball on an item, independent of the source's own vocabulary.

    Each adapter maps its own vocabulary onto these; the mapping table
    lives in the adapter's own config (sheet.yaml's ball_in_our_court /
    waiting_on_others / done_status for the Sheets adapter), not in code.
    """

    US = "us"
    THEM = "them"
    CITY = "city"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Item:
    """One task/row, from any source.

    `id` is stable across time even when the source has no natural key
    (the Sheets adapter hashes normalized (group, title), since row
    numbers move when a tab is duplicated week to week).
    """

    id: str
    project: str
    group: str  # e.g. subcontractor/trade
    title: str
    due_date: dt.date | None
    status: Status
    ball: Ball
    notes: str
    last_changed: dt.datetime | None
    url: str = ""
    raw: Any = None  # source's original record; debugging only, features must not read this
    kind: str = "item"  # lets a richer source (e.g. Procore) distinguish RFI/submittal/punch


@dataclass(frozen=True)
class Change:
    """One historical change to an item, from any source's change history."""

    item_id: str
    timestamp: dt.datetime | None
    user: str
    # Canonical Item field name where the adapter can map it: "title", "group",
    # "due_date", "status", "ball", "notes". Otherwise the source's own name, lowercased.
    field: str
    old_value: str
    new_value: str


@dataclass
class Annotation:
    """One agent-written field on an item (e.g. a flag, a next action)."""

    item_id: str
    field: str  # semantic field name, e.g. "flag", "next_action"
    value: str


@dataclass
class Brief:
    """The AI Brief content, source-agnostic. A source renders this into
    its own shape (for Sheets: a tab's cells).
    """

    project: str
    generated_at: dt.datetime
    snapshot: str  # 3-5 sentence project snapshot
    by_group: list[dict[str, str]]  # group | open items | worst flag | status | last activity
    waiting_on: dict[str, list[str]]  # who has the ball -> item titles
    cycle_stats: dict[str, str]


@dataclass
class Question:
    id: str
    project: str | None
    text: str
    asked_at: dt.datetime | None


@dataclass
class Citation:
    source: str
    location: str  # page/section for docs; week/tab for tracker history
    section: str | None = None


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "not_found"  # high | medium | low | not_found


@dataclass(frozen=True)
class FieldDiff:
    item_id: str
    field: str
    old: str
    new: str


@dataclass
class WriteResult:
    ok: bool
    written: int
    dry_run: bool
    detail: str = ""
    diff: list[FieldDiff] = field(default_factory=list)  # only cells whose value changes


@dataclass
class SourceHealth:
    ok: bool
    detail: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParseWarning:
    location: str  # e.g. "wk 7/28 row 12"
    message: str


@dataclass
class ParseResult:
    items: list[Item]
    warnings: list[ParseWarning]
