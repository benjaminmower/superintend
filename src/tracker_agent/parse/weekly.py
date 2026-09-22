"""Parse a weekly tab's raw grid into a list[Item].

Handles the sheet quirks documented in CLAUDE.md: fill-down on
SUBCONTRACTOR, the blank-header DATE column (positional fallback), and
multi-select STATUS/DETAILS values (take the last value, log a warning).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from tracker_agent.config import SheetConfig
from tracker_agent.sheets import SheetClient, find_header_row

_MISSING_VALUES = {"", "tbd", "n/a", "na"}


@dataclass
class Item:
    sub: str
    item: str
    date: dt.date | None
    status: str
    details: str
    notes: str
    tab: str
    row: int  # 1-indexed sheet row this item came from


@dataclass
class ParseWarning:
    tab: str
    row: int
    message: str


@dataclass
class ParseResult:
    items: list[Item]
    warnings: list[ParseWarning]


def _is_missing(value: str) -> bool:
    return value.strip().lower() in _MISSING_VALUES


def _normalize_multiselect(value: str, tab: str, row: int, warnings: list[ParseWarning]) -> str:
    """Multi-select values like "Blocked, Completed" -> take the last value."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) <= 1:
        return value.strip()
    warnings.append(
        ParseWarning(tab=tab, row=row, message=f"multi-select value {value!r}, using {parts[-1]!r}")
    )
    return parts[-1]


def _parse_date(value: str) -> dt.date | None:
    if _is_missing(value):
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _column_index(headers: list[str], date_header: str, fallback_after: str) -> dict[str, int]:
    """Map semantic column name -> 0-indexed column position.

    The DATE column's header may be blank; if `date_header` isn't found,
    fall back to the column immediately after `fallback_after`.
    """
    index = {h: i for i, h in enumerate(headers) if h}
    if date_header not in index:
        after_idx = index[fallback_after]
        index[date_header] = after_idx + 1
    return index


def parse_weekly_tab(client: SheetClient, tab: str, sheet_config: SheetConfig) -> ParseResult:
    header_row = find_header_row(client, tab, sheet_config)
    headers = client.headers(tab, header_row)
    cols = sheet_config.columns

    col_idx = _column_index(headers, cols.date.header, cols.date.fallback_after)
    sub_idx = col_idx[cols.sub]
    item_idx = col_idx[cols.item]
    date_idx = col_idx[cols.date.header]
    status_idx = col_idx[cols.status]
    details_idx = col_idx[cols.details]
    notes_idx = col_idx[cols.notes]

    grid = client.all_values(tab)
    items: list[Item] = []
    warnings: list[ParseWarning] = []
    current_sub = ""

    for i, raw_row in enumerate(grid[header_row:], start=header_row + 1):
        row = raw_row + [""] * (max(col_idx.values()) + 1 - len(raw_row))
        if not any(cell.strip() for cell in row):
            continue  # fully blank row

        sub = row[sub_idx].strip()
        if sub:
            current_sub = sub
        elif not current_sub:
            warnings.append(ParseWarning(tab=tab, row=i, message="no SUBCONTRACTOR to fill down"))

        item_text = row[item_idx].strip()
        if not item_text:
            continue  # a group label row with no task

        status = _normalize_multiselect(row[status_idx], tab, i, warnings)
        details = _normalize_multiselect(row[details_idx], tab, i, warnings)

        items.append(
            Item(
                sub=current_sub,
                item=item_text,
                date=_parse_date(row[date_idx]),
                status=status,
                details=details,
                notes=row[notes_idx].strip(),
                tab=tab,
                row=i,
            )
        )

    return ParseResult(items=items, warnings=warnings)
