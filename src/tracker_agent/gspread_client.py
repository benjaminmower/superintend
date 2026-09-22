"""Real SheetClient backed by gspread + a Google service account."""

from __future__ import annotations

import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from tracker_agent.sheets import CellUpdate

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

    def headers(self, tab: str) -> list[str]:
        ws = self._spreadsheet.worksheet(tab)
        return ws.row_values(1)

    def read_rows(self, tab: str) -> list[dict[str, str]]:
        ws = self._spreadsheet.worksheet(tab)
        return ws.get_all_records()

    def batch_write(self, tab: str, updates: list[CellUpdate]) -> None:
        ws = self._spreadsheet.worksheet(tab)
        header_row = ws.row_values(1)
        col_index = {h: i + 1 for i, h in enumerate(header_row)}
        body = [
            {
                "range": gspread.utils.rowcol_to_a1(u.row, col_index[u.header]),
                "values": [[u.value]],
            }
            for u in updates
        ]
        ws.batch_update(body)
