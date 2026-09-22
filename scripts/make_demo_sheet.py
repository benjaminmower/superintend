# /// script
# dependencies = ["gspread", "google-auth"]
# ///
"""One-time setup script: seed the demo spreadsheet with fixture data.

Writes the same invented data as tests/fixtures/demo_sheet.py into an
*existing*, empty Google Sheet — never a copy of the real tracker, so
there's no hand-scrubbing step and no risk of a missed real name or
address leaking into the demo.

You create the blank spreadsheet yourself first (your own account has
normal Drive quota; a service account's own quota is ~0 and Shared
Drives add their own headaches — see docs/setup.md step 4), share it
with the service account as an Editor, then this script fills it in.

Usage:
    uv run python -m scripts.make_demo_sheet --sheet-id <ID>

Requires GOOGLE_SERVICE_ACCOUNT_FILE (see docs/setup.md) and the sheet
already shared with the service account as Editor.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from tests.fixtures.demo_sheet import CHANGELOG_GRID, WEEKLY_GRID

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

TABS: list[tuple[str, list[list[str]]]] = [
    ("wk 7/14", WEEKLY_GRID),
    ("Wk 7/21", WEEKLY_GRID),
    ("Wk of 7/28", WEEKLY_GRID),
    ("Copy of Wk 7/21", WEEKLY_GRID),
    ("Change log", CHANGELOG_GRID),
    ("AI Brief", [["Section", "Text"], ["", ""]]),
    ("Ask", [["Question", "Project", "Answer", "Status"]]),
    ("AI Log", [["Run", "Command", "Status"]]),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sheet-id",
        required=True,
        help="ID of an existing, empty Google Sheet (from its URL: "
        "docs.google.com/spreadsheets/d/<ID>/edit), already shared with "
        "the service account as Editor.",
    )
    args = parser.parse_args()

    credentials_file = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service_account.json"
    )
    if not Path(credentials_file).exists():
        raise SystemExit(f"{credentials_file} not found. Follow docs/setup.md steps 1-3 first.")

    creds = Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(args.sheet_id)

    existing_default = spreadsheet.sheet1 if len(spreadsheet.worksheets()) == 1 else None

    first = True
    for name, grid in TABS:
        if first and existing_default is not None:
            ws = existing_default
            ws.update_title(name)
        else:
            ws = spreadsheet.add_worksheet(name, rows=100, cols=20)
        first = False
        if grid:
            ws.update(values=grid, range_name="A1")

    print(f"Seeded {spreadsheet.title!r}: {spreadsheet.id}")
    print(f"\nSHEET_ID_DEMO={spreadsheet.id}")
    print("\nAdd that line to .env, then:")
    print("  uv run tracker inspect --project demo-1")


if __name__ == "__main__":
    main()
