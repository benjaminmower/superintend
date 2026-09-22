"""GSheetsSource: the Google Sheets TrackerSource adapter.

The messiest source, and the one the rest of the interface is proven
against first. Wraps raw.py's SheetClient + write guards and the two
parsers behind the TrackerSource contract.
"""

from __future__ import annotations

import datetime as dt

from tracker_agent.config import SheetConfig, SpreadsheetConfig
from tracker_agent.core.capabilities import Capability
from tracker_agent.core.models import (
    Annotation,
    Answer,
    Brief,
    Change,
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
    is_changelog_tab,
    latest_weekly_tab,
    write_ai_cells,
)


class GSheetsSource(TrackerSource):
    name = "gsheets"
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

    def _changelog_tab(self) -> str | None:
        for name in self._client.tab_names():
            if is_changelog_tab(self._client, name, self._sheet_config):
                return name
        return None

    def health(self) -> SourceHealth:
        try:
            self._latest_tab()
        except NoWeeklyTabFoundError as exc:
            return SourceHealth(ok=False, detail=str(exc))
        if self._changelog_tab() is None:
            return SourceHealth(ok=False, detail="no change log tab found")
        return SourceHealth(ok=True)

    def items(self, project: str) -> ParseResult:
        self._spreadsheet_for(project)
        latest = self._latest_tab()
        return parse_weekly_tab(self._client, latest, project, self._sheet_config)

    def history(self, project: str, since: dt.date | None = None) -> list[Change]:
        self._spreadsheet_for(project)
        changelog_tab = self._changelog_tab()
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
        self._spreadsheet_for(project)
        latest = self._latest_tab()
        result = parse_weekly_tab(self._client, latest, project, self._sheet_config)
        row_by_item_id = {item.id: item.raw["row"] for item in result.items}

        cell_updates = []
        for annotation in annotations:
            row = row_by_item_id.get(annotation.item_id)
            if row is None:
                raise ValueError(f"item_id {annotation.item_id!r} not found on {latest!r}")
            header = self._sheet_config.ai_columns.get(annotation.field)
            if header is None:
                raise ValueError(f"{annotation.field!r} is not an agent-owned item field")
            cell_updates.append(CellUpdate(row=row, header=header, value=annotation.value))

        write_ai_cells(self._client, latest, self._sheet_config, cell_updates, dry_run=dry_run)
        return WriteResult(ok=True, written=len(cell_updates), dry_run=dry_run)

    def write_brief(self, brief: Brief, *, dry_run: bool) -> WriteResult:
        raise NotImplementedError("GSheetsSource.write_brief: Phase 2 (see SPEC.md)")

    def questions(self, project: str | None = None) -> list[Question]:
        raise NotImplementedError("GSheetsSource.questions: Phase 4 (see SPEC.md)")

    def answer_question(self, question_id: str, answer: Answer, *, dry_run: bool) -> WriteResult:
        raise NotImplementedError("GSheetsSource.answer_question: Phase 4 (see SPEC.md)")
