"""SheetClient protocol + GspreadClient (real) + FakeSheetClient (tests).

Guardrail: all writes go through write_ai_cells() (latest weekly tab,
ai_columns allow-list only) or write_agent_tab() (AI Brief / Ask / AI Log,
wholly agent-owned). Never write anywhere else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from tracker_agent.config import SheetConfig


class AiColumnWriteError(ValueError):
    """Raised when code tries to write to a header not in ai_columns."""


class NoWeeklyTabFoundError(ValueError):
    """Raised when no tab is classified as the latest weekly tab."""


class NotAgentTabError(ValueError):
    """Raised when write_agent_tab() is called on a tab not in agent_tabs."""


TabRole = str  # "weekly" | "changelog" | "ignored" | "other"


@dataclass
class CellUpdate:
    row: int  # 1-indexed sheet row, including any title/header rows
    header: str
    value: str


class SheetClient(Protocol):
    def tab_names(self) -> list[str]: ...

    def headers(self, tab: str, header_row: int = 1) -> list[str]:
        """Header row for a tab, 1-indexed."""
        ...

    def all_values(self, tab: str) -> list[list[str]]:
        """Every cell in a tab as a grid of raw strings, row-major."""
        ...

    def read_rows(self, tab: str, header_row: int = 1) -> list[dict[str, str]]:
        """Data rows below header_row, keyed by header text."""
        ...

    def batch_write(self, tab: str, updates: list[CellUpdate]) -> None:
        """Low-level batch write. Call only from write_ai_cells()/write_agent_tab()."""
        ...


def classify_tab(name: str, sheet_config: SheetConfig) -> TabRole:
    """Classify a tab by name: "weekly", "changelog", "ignored", or "other"."""
    if re.match(sheet_config.ignore_tab_regex, name, re.IGNORECASE):
        return "ignored"
    if re.match(sheet_config.weekly_tab_regex, name, re.IGNORECASE):
        return "weekly"
    if sheet_config.changelog_tab != "auto" and name == sheet_config.changelog_tab:
        return "changelog"
    return "other"


def is_changelog_tab(client: SheetClient, name: str, sheet_config: SheetConfig) -> bool:
    """For changelog_tab: auto, detect by the tab's header row."""
    if sheet_config.changelog_tab != "auto":
        return name == sheet_config.changelog_tab
    try:
        headers = client.headers(name)
    except (KeyError, IndexError):
        return False
    return "Timestamp" in headers and "User" in headers and "Sheet Name" in headers


def find_header_row(client: SheetClient, tab: str, sheet_config: SheetConfig) -> int:
    """Search the first 10 rows of a weekly tab for the SUBCONTRACTOR/ITEM header row.

    Returns the 1-indexed row number. Raises ValueError if none is found.
    """
    grid = client.all_values(tab)[:10]
    sub_header = sheet_config.columns.sub
    item_header = sheet_config.columns.item
    for i, row in enumerate(grid, start=1):
        if sub_header in row and item_header in row:
            return i
    raise ValueError(f"No header row found in the first 10 rows of {tab!r}.")


def resolve_weekly_tab_dates(
    client: SheetClient, sheet_config: SheetConfig, start_year: int
) -> list[tuple[str, date]]:
    """Resolve a (tab name, date) pair for every weekly tab, in sheet order.

    Tab names carry no year, so the year is resolved by walking tabs in
    the order they appear in the spreadsheet (gspread returns worksheets
    left-to-right) and incrementing the year whenever the month goes
    backwards relative to the previous weekly tab (e.g. ... 12/29, 1/5 ->
    1/5 is the next year). This matches how the tabs are actually created:
    each new week is appended after the last.
    """
    pattern = re.compile(sheet_config.weekly_tab_regex, re.IGNORECASE)
    resolved: list[tuple[str, date]] = []
    year = start_year
    last_month = None

    for name in client.tab_names():
        if classify_tab(name, sheet_config) != "weekly":
            continue
        match = pattern.match(name)
        month, day = int(match.group(3)), int(match.group(4))
        if last_month is not None and month < last_month:
            year += 1
        last_month = month
        resolved.append((name, date(year, month, day)))

    return resolved


def latest_weekly_tab(client: SheetClient, sheet_config: SheetConfig, start_year: int) -> str:
    """Return the name of the most recent weekly tab.

    See resolve_weekly_tab_dates() for how the (missing) year is resolved.
    """
    resolved = resolve_weekly_tab_dates(client, sheet_config, start_year)
    if not resolved:
        raise NoWeeklyTabFoundError("No tab matches weekly_tab_regex in sheet.yaml.")
    return max(resolved, key=lambda pair: pair[1])[0]


def write_ai_cells(
    client: SheetClient,
    tab: str,
    sheet_config: SheetConfig,
    updates: list[CellUpdate],
    *,
    dry_run: bool,
) -> list[CellUpdate]:
    """The only sanctioned way to write AI columns on a weekly tab.

    Refuses any update whose header isn't listed under ai_columns in
    sheet.yaml. Batches into a single write per call. In dry-run mode,
    validates and returns the would-be updates without writing.
    """
    allowed = sheet_config.ai_column_headers()
    for update in updates:
        if update.header not in allowed:
            raise AiColumnWriteError(
                f"Refusing to write to {tab!r}.{update.header!r}: "
                f"not listed under ai_columns in sheet.yaml"
            )

    if not dry_run and updates:
        client.batch_write(tab, updates)

    return updates


def write_agent_tab(
    client: SheetClient,
    tab: str,
    sheet_config: SheetConfig,
    updates: list[CellUpdate],
    *,
    dry_run: bool,
) -> list[CellUpdate]:
    """The only sanctioned way to write to a wholly agent-owned tab.

    `tab` must be listed under agent_tabs in sheet.yaml (AI Brief, Ask,
    AI Log). Every cell on such a tab is writable — there's no
    per-header allow-list, unlike write_ai_cells().
    """
    if tab not in sheet_config.agent_tabs:
        raise NotAgentTabError(f"{tab!r} is not listed under agent_tabs in sheet.yaml")

    if not dry_run and updates:
        client.batch_write(tab, updates)

    return updates


@dataclass
class FakeSheetClient:
    """In-memory SheetClient for tests. No network."""

    _tabs: dict[str, list[list[str]]] = field(default_factory=dict)

    def add_tab(self, name: str, grid: list[list[str]]) -> None:
        """grid is every row of the tab, including any title/header rows."""
        self._tabs[name] = [list(row) for row in grid]

    def tab_names(self) -> list[str]:
        return list(self._tabs)

    def all_values(self, tab: str) -> list[list[str]]:
        return [list(row) for row in self._tabs[tab]]

    def headers(self, tab: str, header_row: int = 1) -> list[str]:
        return list(self._tabs[tab][header_row - 1])

    def read_rows(self, tab: str, header_row: int = 1) -> list[dict[str, str]]:
        headers = self.headers(tab, header_row)
        rows = self._tabs[tab][header_row:]
        return [
            dict(zip(headers, row + [""] * (len(headers) - len(row)), strict=False)) for row in rows
        ]

    def batch_write(self, tab: str, updates: list[CellUpdate]) -> None:
        grid = self._tabs[tab]
        col_idx_by_header: dict[str, int] = {}
        for row in grid[:10]:
            for i, cell in enumerate(row):
                if cell and cell not in col_idx_by_header:
                    col_idx_by_header[cell] = i

        for update in updates:
            row_idx = update.row - 1
            col_idx = col_idx_by_header[update.header]
            while len(grid) <= row_idx:
                grid.append([])
            row = grid[row_idx]
            while len(row) <= col_idx:
                row.append("")
            row[col_idx] = update.value
