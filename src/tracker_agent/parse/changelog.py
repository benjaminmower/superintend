"""Parse the change log tab into list[Change].

Row numbers shift between weekly tabs (each week is a duplicate of the
last), so changes are matched to items by normalized (sub, item), never
by row. See CLAUDE.md's "Sheet quirks to respect".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from tracker_agent.sheets import SheetClient

_CHANGELOG_HEADERS = [
    "Timestamp",
    "User",
    "Sheet Name",
    "Row",
    "Column Name",
    "Old Value",
    "New Value",
    "Item (Current)",
    "Subcontractor (Current)",
]


@dataclass
class Change:
    timestamp: dt.datetime | None
    user: str
    sheet_name: str
    column_name: str
    old_value: str
    new_value: str
    item: str
    sub: str

    def item_key(self) -> tuple[str, str]:
        return normalize_key(self.sub, self.item)


def normalize_key(sub: str, item: str) -> tuple[str, str]:
    return (sub.strip().lower(), item.strip().lower())


def _parse_timestamp(value: str) -> dt.datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_changelog_tab(client: SheetClient, tab: str) -> list[Change]:
    rows = client.read_rows(tab, header_row=1)
    changes: list[Change] = []

    for row in rows:
        if not any(row.values()):
            continue
        changes.append(
            Change(
                timestamp=_parse_timestamp(row.get("Timestamp", "")),
                user=row.get("User", "").strip(),
                sheet_name=row.get("Sheet Name", "").strip(),
                column_name=row.get("Column Name", "").strip(),
                old_value=row.get("Old Value", "").strip(),
                new_value=row.get("New Value", "").strip(),
                item=row.get("Item (Current)", "").strip(),
                sub=row.get("Subcontractor (Current)", "").strip(),
            )
        )

    return changes


def index_by_item(changes: list[Change]) -> dict[tuple[str, str], list[Change]]:
    """Group changes by normalized (sub, item), each list sorted oldest-first."""
    index: dict[tuple[str, str], list[Change]] = {}
    for change in changes:
        index.setdefault(change.item_key(), []).append(change)
    for group in index.values():
        group.sort(key=lambda c: c.timestamp or dt.datetime.min)
    return index
