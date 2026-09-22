"""SheetClient protocol + GspreadClient (real) + FakeSheetClient (tests).

Guardrail: all writes go through write_ai_cells(), which refuses to touch
any header not listed under ai_columns in sheet.yaml (for tabs that have
an allow-list) or writes freely to tabs that are wholly agent-owned
(AI Brief, AI Log — pass allowed_headers=None for those).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

_WEEKLY_TAB_RE = re.compile(r"^wk (\d{1,2})/(\d{1,2})$")

# A weekly tab dated further than this many days in the future (relative
# to "today") is treated as belonging to last year, not next year — the
# sheet only ever gets new tabs going forward in time, one per week.
_FUTURE_TOLERANCE_DAYS = 60


class AiColumnWriteError(ValueError):
    """Raised when code tries to write to a header not in a tab's ai_columns."""


class NoWeeklyTabFoundError(ValueError):
    """Raised when no tab name matches the weekly tab pattern."""


@dataclass
class CellUpdate:
    row: int  # 1-indexed sheet row, including header
    header: str
    value: str


class SheetClient(Protocol):
    def tab_names(self) -> list[str]: ...

    def headers(self, tab: str) -> list[str]:
        """Header row for a tab."""
        ...

    def read_rows(self, tab: str) -> list[dict[str, str]]:
        """All data rows for a tab, keyed by header text."""
        ...

    def batch_write(self, tab: str, updates: list[CellUpdate]) -> None:
        """Low-level batch write. Do not call directly outside write_ai_cells()."""
        ...


def latest_weekly_tab(client: SheetClient, today: date | None = None) -> str:
    """Return the name of the most recent "wk M/D" tab.

    Tab names carry no year, so a parsed date more than
    _FUTURE_TOLERANCE_DAYS ahead of `today` is assumed to be from last
    year (e.g. today is January and a tab says "wk 12/29").
    """
    today = today or date.today()
    candidates: list[tuple[date, str]] = []

    for name in client.tab_names():
        match = _WEEKLY_TAB_RE.match(name)
        if not match:
            continue
        month, day = int(match.group(1)), int(match.group(2))
        try:
            parsed = date(today.year, month, day)
        except ValueError:
            continue
        if (parsed - today).days > _FUTURE_TOLERANCE_DAYS:
            parsed = date(today.year - 1, month, day)
        candidates.append((parsed, name))

    if not candidates:
        raise NoWeeklyTabFoundError('No tab matches the "wk M/D" naming pattern.')

    candidates.sort(key=lambda c: c[0])
    return candidates[-1][1]


def write_ai_cells(
    client: SheetClient,
    tab: str,
    allowed_headers: set[str] | None,
    updates: list[CellUpdate],
    *,
    dry_run: bool,
) -> list[CellUpdate]:
    """The only sanctioned way to write AI-owned cells.

    `allowed_headers` is the ai_columns allow-list for `tab` (from
    sheet.yaml); pass None only for tabs that are wholly agent-owned
    (AI Brief, AI Log), where every cell is writable. Batches into a
    single write per call. In dry-run mode, validates and returns the
    would-be updates without writing.
    """
    if allowed_headers is not None:
        for update in updates:
            if update.header not in allowed_headers:
                raise AiColumnWriteError(
                    f"Refusing to write to {tab!r}.{update.header!r}: "
                    f"not listed under ai_columns in sheet.yaml"
                )

    if not dry_run and updates:
        client.batch_write(tab, updates)

    return updates


@dataclass
class FakeSheetClient:
    """In-memory SheetClient for tests. No network."""

    _tabs: dict[str, list[str]] = field(default_factory=dict)
    _rows: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    written: list[CellUpdate] = field(default_factory=list)

    def add_tab(self, name: str, headers: list[str], rows: list[dict[str, str]]) -> None:
        self._tabs[name] = headers
        self._rows[name] = rows

    def tab_names(self) -> list[str]:
        return list(self._tabs)

    def headers(self, tab: str) -> list[str]:
        return list(self._tabs[tab])

    def read_rows(self, tab: str) -> list[dict[str, str]]:
        return [dict(r) for r in self._rows[tab]]

    def batch_write(self, tab: str, updates: list[CellUpdate]) -> None:
        self.written.extend(updates)
        for update in updates:
            row_idx = update.row - 2  # header is row 1, data starts row 2
            self._rows[tab][row_idx][update.header] = update.value
