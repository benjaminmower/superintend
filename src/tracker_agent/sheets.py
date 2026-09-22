"""SheetClient protocol + GspreadClient (real) + FakeSheetClient (tests).

Guardrail: all writes go through write_ai_cells(), which refuses to touch
any header not listed under ai_columns in sheet.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tracker_agent.config import SheetConfig


class AiColumnWriteError(ValueError):
    """Raised when code tries to write to a header not in ai_columns."""


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


def write_ai_cells(
    client: SheetClient,
    sheet_config: SheetConfig,
    updates: list[CellUpdate],
    *,
    dry_run: bool,
) -> list[CellUpdate]:
    """The only sanctioned way to write AI-owned cells.

    Refuses any update whose header isn't listed under ai_columns in
    sheet.yaml. Batches into a single write per call. In dry-run mode,
    validates and returns the would-be updates without writing.
    """
    allowed = sheet_config.ai_column_headers()
    for update in updates:
        if update.header not in allowed:
            raise AiColumnWriteError(
                f"Refusing to write to {update.header!r}: "
                f"not listed under ai_columns in sheet.yaml"
            )

    if not dry_run and updates:
        client.batch_write(sheet_config.tab, updates)

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
