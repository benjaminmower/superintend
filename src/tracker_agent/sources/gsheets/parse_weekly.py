"""Parse a weekly tab's raw grid into canonical core.models.Item objects.

Handles the sheet quirks documented in CLAUDE.md: fill-down on
SUBCONTRACTOR, the blank-header DATE column (positional fallback), and
multi-select STATUS/DETAILS values (take the last value, log a warning).
"""

from __future__ import annotations

import datetime as dt
import hashlib

from tracker_agent.config import SheetConfig
from tracker_agent.core.models import Ball, Item, ParseResult, ParseWarning, Status
from tracker_agent.sources.gsheets.raw import SheetClient, find_header_row

_MISSING_VALUES = {"", "tbd", "n/a", "na"}

# The sheet's own STATUS vocabulary -> the canonical Status enum.
_STATUS_MAP = {
    "not started": Status.NOT_STARTED,
    "in progress": Status.IN_PROGRESS,
    "blocked": Status.BLOCKED,
    "completed": Status.DONE,
    "cancelled": Status.CANCELLED,
}


def item_id(project: str, group: str, title: str) -> str:
    """A stable id across weeks: row numbers move when a tab is duplicated,
    so the id is a hash of the normalized (project, group, title) instead.
    """
    key = f"{project}|{group.strip().lower()}|{title.strip().lower()}"
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]


def _is_missing(value: str) -> bool:
    return value.strip().lower() in _MISSING_VALUES


def _normalize_multiselect(value: str, location: str, warnings: list[ParseWarning]) -> str:
    """Multi-select values like "Blocked, Completed" -> take the last value."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) <= 1:
        return value.strip()
    warnings.append(
        ParseWarning(
            location=location, message=f"multi-select value {value!r}, using {parts[-1]!r}"
        )
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


# DETAILS values that imply a STATUS, used only when the raw STATUS cell
# doesn't map on its own (blank, or a DETAILS value typed in by mistake —
# e.g. "Reached out" belongs in DETAILS, not STATUS).
_STATUS_FROM_DETAILS = {
    "cancelled": Status.CANCELLED,
    "done!": Status.DONE,
}


def _classify_status(
    status_text: str, details: str, location: str, warnings: list[ParseWarning]
) -> Status:
    status = _STATUS_MAP.get(status_text.strip().lower())
    if status is not None:
        return status

    inferred = _STATUS_FROM_DETAILS.get(details.strip().lower())
    if inferred is not None:
        warnings.append(
            ParseWarning(
                location=location,
                message=(
                    f"STATUS {status_text!r} not recognized; inferred {inferred.value!r} "
                    f"from DETAILS {details!r}"
                ),
            )
        )
        return inferred

    warnings.append(
        ParseWarning(location=location, message=f"unrecognized STATUS value {status_text!r}")
    )
    return Status.NOT_STARTED


def _classify_ball(status: Status, details: str, sheet_config: SheetConfig) -> Ball:
    """DETAILS decides who has the ball. Kept independent of STATUS (rather than
    forcing NONE whenever STATUS is done) so flags.py can catch the two disagreeing
    — e.g. Completed but DETAILS isn't a done_details value.
    """
    if details in sheet_config.done_details:
        return Ball.NONE
    if details in sheet_config.ball_in_our_court:
        return Ball.US
    if details in sheet_config.waiting_on_others:
        return Ball.THEM
    return Ball.UNKNOWN


def parse_weekly_tab(
    client: SheetClient, tab: str, project: str, sheet_config: SheetConfig
) -> ParseResult:
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
        location = f"{tab} row {i}"
        if not any(cell.strip() for cell in row):
            continue  # fully blank row

        sub = row[sub_idx].strip()
        if sub:
            current_sub = sub
        elif not current_sub:
            warnings.append(
                ParseWarning(location=location, message="no SUBCONTRACTOR to fill down")
            )

        item_text = row[item_idx].strip()
        if not item_text:
            continue  # a group label row with no task

        status_text = _normalize_multiselect(row[status_idx], location, warnings)
        details = _normalize_multiselect(row[details_idx], location, warnings)
        status = _classify_status(status_text, details, location, warnings)

        items.append(
            Item(
                id=item_id(project, current_sub, item_text),
                project=project,
                group=current_sub,
                title=item_text,
                due_date=_parse_date(row[date_idx]),
                status=status,
                ball=_classify_ball(status, details, sheet_config),
                notes=row[notes_idx].strip(),
                last_changed=None,  # filled in from the change log by the source, not here
                url="",
                raw={"tab": tab, "row": i, "ball_detail": details},
            )
        )

    _warn_duplicate_items(items, tab, warnings)

    return ParseResult(items=items, warnings=warnings)


def _warn_duplicate_items(items: list[Item], tab: str, warnings: list[ParseWarning]) -> None:
    """item_id() hashes (group, title) so an item's id stays stable week to
    week — but that means two genuinely different rows on the SAME tab with
    the same (group, title) text collide onto one id, and flags.py/writes
    can't tell them apart. Not fixable here (nothing in the sheet
    disambiguates them), so surface it loudly instead of silently merging.
    """
    seen: dict[str, list[int]] = {}
    for item in items:
        seen.setdefault(item.id, []).append(item.raw["row"])
    for item_id_value, rows in seen.items():
        if len(rows) > 1:
            title = next(i.title for i in items if i.id == item_id_value)
            warnings.append(
                ParseWarning(
                    location=f"{tab} rows {rows}",
                    message=(
                        f"duplicate item {title!r} on rows {rows}: identical "
                        f"(SUBCONTRACTOR, ITEM) text makes these rows indistinguishable "
                        f"to item_id() — GSheetsSource.write_annotations() writes a "
                        f"\"consolidate\" flag to each row instead of guessing a shared "
                        f"flag/next_action"
                    ),
                )
            )
