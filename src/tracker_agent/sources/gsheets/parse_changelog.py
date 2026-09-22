"""Parse the change log tab into canonical core.models.Change objects.

Row numbers shift between weekly tabs (each week is a duplicate of the
last), so changes are matched to items by normalized (sub, item), never
by row. See CLAUDE.md's "Sheet quirks to respect".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from tracker_agent.core.models import Change
from tracker_agent.sources.gsheets.parse_weekly import item_id
from tracker_agent.sources.gsheets.raw import SheetClient

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
class RawChange:
    """One change-log row, in the sheet's own vocabulary.

    Kept alongside the canonical Change because `sheet_name` (which
    weekly tab the edit happened on) and the raw sub/item text are
    useful for display and for the Phase 5 backtest, but aren't part of
    the source-agnostic Change model.
    """

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

    def to_change(self, project: str) -> Change:
        return Change(
            item_id=item_id(project, self.sub, self.item),
            timestamp=self.timestamp,
            user=self.user,
            field=canonical_field(self.column_name),
            old_value=self.old_value,
            new_value=self.new_value,
        )


# The sheet's own column header -> the canonical Item field flags.py reasons about.
# Independent of `sheet_config.columns` because the change log's "Column Name" is
# free text written by the sheet's own edit trigger, not a header lookup.
_CANONICAL_FIELD_MAP = {
    "SUBCONTRACTOR": "group",
    "ITEM": "title",
    "DATE": "due_date",
    "STATUS": "status",
    "DETAILS": "ball",
    "NOTES": "notes",
}


def canonical_field(column_name: str) -> str:
    """Map a change log's raw "Column Name" to a canonical Item field name.

    Falls back to the header text lowercased for anything not in the map
    (e.g. a future column), so callers never see an empty field.
    """
    mapped = _CANONICAL_FIELD_MAP.get(column_name.strip().upper())
    if mapped:
        return mapped
    return column_name.strip().lower()


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


def parse_changelog_tab(client: SheetClient, tab: str) -> list[RawChange]:
    rows = client.read_rows(tab, header_row=1)
    changes: list[RawChange] = []

    for row in rows:
        if not any(row.values()):
            continue
        changes.append(
            RawChange(
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


def index_by_item(changes: list[RawChange]) -> dict[tuple[str, str], list[RawChange]]:
    """Group changes by normalized (sub, item), each list sorted oldest-first."""
    index: dict[tuple[str, str], list[RawChange]] = {}
    for change in changes:
        index.setdefault(change.item_key(), []).append(change)
    for group in index.values():
        group.sort(key=lambda c: c.timestamp or dt.datetime.min)
    return index
