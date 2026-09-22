"""One-time setup script: create the demo spreadsheet from scratch.

Builds a brand-new Google Sheet seeded with the same invented data as
tests/fixtures/demo_sheet.py — never a copy of the real tracker, so
there's no hand-scrubbing step and no risk of a missed real name or
address leaking into the demo. Prints the new sheet's ID to put in
.env as SHEET_ID_DEMO.

Usage:
    uv run python -m scripts.make_demo_sheet --shared-drive <ID> [--share you@example.com]

Requires GOOGLE_SERVICE_ACCOUNT_FILE (see docs/setup.md) and a service
account with the Drive file-creation scope, already true of the scopes
in sources/gsheets/client.py.

Service accounts get ~0 usable quota in their own "My Drive", so the
sheet must be created inside a Shared Drive (Workspace-only) that the
service account is a member of — see docs/setup.md step 4. Pass that
Shared Drive's ID (from its URL: drive.google.com/drive/folders/<ID>)
via --shared-drive.
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
    "https://www.googleapis.com/auth/drive",
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
        "--shared-drive",
        required=True,
        help="ID of a Shared Drive the service account is a member of. Service "
        "accounts have ~0 quota in their own My Drive, so the sheet must be "
        "created here instead (see docs/setup.md step 4).",
    )
    parser.add_argument(
        "--share",
        help="Also share the new sheet (Editor) with this email — your own account, "
        "so you can open it in a browser. The service account already owns it.",
    )
    args = parser.parse_args()

    credentials_file = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service_account.json"
    )
    if not Path(credentials_file).exists():
        raise SystemExit(f"{credentials_file} not found. Follow docs/setup.md steps 1-3 first.")

    creds = Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
    gc = gspread.authorize(creds)

    spreadsheet = gc.create("Tracker (demo)", folder_id=args.shared_drive)

    first = True
    for name, grid in TABS:
        ws = spreadsheet.sheet1 if first else spreadsheet.add_worksheet(name, rows=100, cols=20)
        if first:
            ws.update_title(name)
            first = False
        if grid:
            ws.update(values=grid, range_name="A1")

    if args.share:
        spreadsheet.share(args.share, perm_type="user", role="writer")

    print(f"Created {spreadsheet.title!r}: {spreadsheet.id}")
    print(f"\nSHEET_ID_DEMO={spreadsheet.id}")
    print("\nAdd that line to .env, then:")
    print("  uv run tracker inspect --project demo-1")


if __name__ == "__main__":
    main()
