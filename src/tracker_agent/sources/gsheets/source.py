"""GSheetsSource: the Google Sheets TrackerSource adapter.

The messiest source, and the one the rest of the interface is proven
against first. Wraps raw.py's SheetClient + write guards and the two
parsers behind the TrackerSource contract.
"""

from __future__ import annotations

import datetime as dt

from tracker_agent.config import SheetConfig, SpreadsheetConfig
from tracker_agent.core.capabilities import Capability, requires
from tracker_agent.core.models import (
    Annotation,
    Answer,
    Brief,
    Change,
    FieldDiff,
    ParseResult,
    Question,
    SourceHealth,
    WriteResult,
)
from tracker_agent.sources.base import TrackerSource
from tracker_agent.sources.gsheets.parse_changelog import parse_changelog_tab
from tracker_agent.sources.gsheets.parse_weekly import parse_weekly_tab
from tracker_agent.sources.gsheets.raw import (
    CellUpdate,
    NoWeeklyTabFoundError,
    SheetClient,
    TabNotFoundError,
    find_header_row,
    is_changelog_tab,
    latest_weekly_tab,
    write_ai_cells_and_log,
)

AI_LOG_TAB = "AI Log"


class GSheetsSource(TrackerSource):
    name = "gsheets"
    # Only what's implemented today. A feature that needs WRITE_BRIEF or
    # QUESTIONS must see that absence in capabilities and degrade — never
    # discover it by catching NotImplementedError from this adapter.
    capabilities = Capability.READ_ITEMS | Capability.READ_HISTORY | Capability.WRITE_ANNOTATIONS

    def __init__(self, client: SheetClient, sheet_config: SheetConfig):
        self._client = client
        self._sheet_config = sheet_config

    def _spreadsheet_for(self, project: str) -> SpreadsheetConfig:
        for spreadsheet in self._sheet_config.spreadsheets:
            if spreadsheet.project_id == project:
                return spreadsheet
        raise ValueError(f"No spreadsheet with project_id={project!r} in sheet.yaml")

    def _latest_tab(self) -> str:
        return latest_weekly_tab(self._client, self._sheet_config, start_year=dt.date.today().year)

    def _changelog_tab(self, spreadsheet: SpreadsheetConfig) -> str | None:
        changelog_tab = spreadsheet.changelog_tab
        for name in self._client.tab_names():
            if is_changelog_tab(self._client, name, self._sheet_config, changelog_tab):
                return name
        return None

    def health(self) -> SourceHealth:
        # One GSheetsSource always talks to exactly one spreadsheet (the client
        # it was built with in _resolve_source()), so any configured entry's
        # changelog_tab override is the right one — health() has no project.
        spreadsheet = self._sheet_config.spreadsheets[0]
        try:
            self._latest_tab()
        except NoWeeklyTabFoundError as exc:
            return SourceHealth(ok=False, detail=str(exc))
        if self._changelog_tab(spreadsheet) is None:
            return SourceHealth(ok=False, detail="no change log tab found")
        return SourceHealth(ok=True)

    def items(self, project: str) -> ParseResult:
        self._spreadsheet_for(project)
        latest = self._latest_tab()
        return parse_weekly_tab(self._client, latest, project, self._sheet_config)

    def history(self, project: str, since: dt.date | None = None) -> list[Change]:
        spreadsheet = self._spreadsheet_for(project)
        changelog_tab = self._changelog_tab(spreadsheet)
        if changelog_tab is None:
            return []
        raw_changes = parse_changelog_tab(self._client, changelog_tab)
        changes = [rc.to_change(project) for rc in raw_changes]
        if since is None:
            return changes
        return [c for c in changes if c.timestamp is None or c.timestamp.date() >= since]

    def write_annotations(
        self, project: str, annotations: list[Annotation], *, dry_run: bool
    ) -> WriteResult:
        requires(self.capabilities, Capability.WRITE_ANNOTATIONS)
        self._spreadsheet_for(project)
        latest = self._latest_tab()
        result = parse_weekly_tab(self._client, latest, project, self._sheet_config)
        # item_id() hashes (group, title) so it's stable week to week, but two
        # rows on the SAME tab can share that text (see
        # parse_weekly._warn_duplicate_items) and thus the same id — write to
        # every matching row, not just the last one a naive {id: row} dict
        # comprehension would keep.
        rows_by_item_id: dict[str, list[int]] = {}
        for item in result.items:
            rows_by_item_id.setdefault(item.id, []).append(item.raw["row"])

        header_row = find_header_row(self._client, latest, self._sheet_config)
        current_rows = self._client.read_rows(latest, header_row=header_row)
        # read_rows() is 0-indexed from just below the header row; map sheet row -> values.
        current_by_row = {header_row + 1 + i: row for i, row in enumerate(current_rows)}

        cell_updates = []
        diff = []
        for annotation in annotations:
            rows = rows_by_item_id.get(annotation.item_id)
            if not rows:
                raise ValueError(f"item_id {annotation.item_id!r} not found on {latest!r}")
            header = self._sheet_config.ai_columns.get(annotation.field)
            if header is None:
                raise ValueError(f"{annotation.field!r} is not an agent-owned item field")

            for row in rows:
                value = annotation.value
                if len(rows) > 1:
                    # Rows sharing an id are indistinguishable (same
                    # SUBCONTRACTOR + ITEM text) — flags.py computed one
                    # flag/next_action for "the item", but that's not
                    # trustworthy when it could really be N different rows.
                    # Tell a human to fix the sheet instead of guessing.
                    other_rows = [r for r in rows if r != row]
                    if annotation.field == "flag":
                        others = ", ".join(str(r) for r in other_rows)
                        noun = "rows" if len(other_rows) > 1 else "row"
                        value = f"⚠️ Duplicate — consolidate with {noun} {others}"
                    elif annotation.field == "next_action":
                        value = ""

                old_value = current_by_row.get(row, {}).get(header, "")
                if old_value == value:
                    continue  # no-op: don't touch cells that already hold this value
                cell_updates.append(CellUpdate(row=row, header=header, value=value))
                diff.append(
                    FieldDiff(
                        item_id=annotation.item_id,
                        field=annotation.field,
                        old=old_value,
                        new=value,
                    )
                )

        log_updates = []
        # Dry-run never appends a log row (nothing real happened to log), so
        # skip reading the log tab's current length too — that read alone
        # would otherwise crash a dry-run against a sheet missing AI Log,
        # even though dry-run is exactly the mode meant to be safe to try.
        if AI_LOG_TAB in self._sheet_config.agent_tabs and cell_updates and not dry_run:
            try:
                next_row = len(self._client.all_values(AI_LOG_TAB)) + 1
            except TabNotFoundError as exc:
                raise ValueError(
                    f"agent_tabs lists {AI_LOG_TAB!r}, but no tab by that name exists on "
                    f"the spreadsheet. Add it (e.g. headers: Run | Command | Status) or "
                    f"remove it from agent_tabs in sheet.yaml."
                ) from exc
            timestamp = dt.datetime.now().isoformat(timespec="seconds")
            log_updates = [
                CellUpdate(row=next_row, header="Run", value=timestamp),
                CellUpdate(row=next_row, header="Command", value="flag"),
                CellUpdate(row=next_row, header="Status", value=f"wrote {len(cell_updates)} cells"),
            ]

        write_ai_cells_and_log(
            self._client,
            latest,
            AI_LOG_TAB,
            self._sheet_config,
            cell_updates,
            log_updates,
            dry_run=dry_run,
        )
        return WriteResult(ok=True, written=len(cell_updates), dry_run=dry_run, diff=diff)

    def write_brief(self, brief: Brief, *, dry_run: bool) -> WriteResult:
        # Not yet in `capabilities` (Phase 2), so `requires` raises
        # CapabilityError here — callers should have checked first.
        requires(self.capabilities, Capability.WRITE_BRIEF)
        raise AssertionError("unreachable: WRITE_BRIEF is not declared")

    def questions(self, project: str | None = None) -> list[Question]:
        # Not yet in `capabilities` (Phase 4).
        requires(self.capabilities, Capability.QUESTIONS)
        raise AssertionError("unreachable: QUESTIONS is not declared")

    def answer_question(self, question_id: str, answer: Answer, *, dry_run: bool) -> WriteResult:
        # Not yet in `capabilities` (Phase 4).
        requires(self.capabilities, Capability.QUESTIONS)
        raise AssertionError("unreachable: QUESTIONS is not declared")
