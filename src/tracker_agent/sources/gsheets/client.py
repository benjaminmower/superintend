"""Real SheetClient backed by gspread + a Google service account."""

from __future__ import annotations

import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from tracker_agent.sources.gsheets.raw import CellUpdate

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GspreadClient:
    def __init__(self, sheet_id: str, credentials_file: str | Path | None = None):
        credentials_file = credentials_file or os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service_account.json"
        )
        creds = Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._spreadsheet = self._gc.open_by_key(sheet_id)

    def tab_names(self) -> list[str]:
        return [ws.title for ws in self._spreadsheet.worksheets()]

    def all_values(self, tab: str) -> list[list[str]]:
        ws = self._spreadsheet.worksheet(tab)
        return ws.get_all_values()

    def headers(self, tab: str, header_row: int = 1) -> list[str]:
        ws = self._spreadsheet.worksheet(tab)
        return ws.row_values(header_row)

    def read_rows(self, tab: str, header_row: int = 1) -> list[dict[str, str]]:
        headers = self.headers(tab, header_row)
        grid = self.all_values(tab)[header_row:]
        rows = []
        for raw_row in grid:
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            rows.append(dict(zip(headers, padded, strict=False)))
        return rows

    def batch_write(self, tab: str, updates: list[CellUpdate]) -> None:
        self.batch_write_many({tab: updates})

    def batch_write_many(self, updates_by_tab: dict[str, list[CellUpdate]]) -> None:
        # One values_batch_update call across every tab (guardrail 5), each
        # range qualified with its tab name so cells land on the right sheet.
        body = []
        for tab, updates in updates_by_tab.items():
            ws = self._spreadsheet.worksheet(tab)
            # The header row for a weekly tab isn't necessarily row 1 (there's
            # a title row above it), so find each update's header by scanning
            # the first 10 rows rather than assuming row 1.
            grid = ws.get_values("A1:Z10")
            col_index: dict[str, int] = {}
            for row in grid:
                for i, cell in enumerate(row, start=1):
                    if cell and cell not in col_index:
                        col_index[cell] = i

            for u in updates:
                a1 = gspread.utils.rowcol_to_a1(u.row, col_index[u.header])
                body.append({"range": f"'{tab}'!{a1}", "values": [[u.value]]})

        if body:
            self._spreadsheet.values_batch_update({"valueInputOption": "RAW", "data": body})
