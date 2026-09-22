"""A FakeSheetClient loaded with invented data mimicking the real tracker's
structure: title row, header row, SUBCONTRACTOR fill-down, a blank DATE
header, multi-select values, and a change log tab. No real project data.
"""

from __future__ import annotations

from tracker_agent.config import ColumnsConfig, DateColumnConfig, SheetConfig, SpreadsheetConfig
from tracker_agent.sheets import FakeSheetClient

TITLE_ROW = ["Fake Construction Co. Weekly Report - 123 Invented St", "", "", "", "", "", "", ""]
HEADER_ROW = [
    "SUBCONTRACTOR",
    "ITEM",
    "",
    "STATUS",
    "DETAILS",
    "NOTES",
    "AI Flag",
    "AI Next Action",
]

WEEKLY_GRID = [
    TITLE_ROW,
    [],
    HEADER_ROW,
    ["Framer", "Rough framing", "7/20/2025", "In progress", "On the schedule", "Started Monday"],
    ["", "Install shear walls", "", "Not started", "Waiting for Response", ""],
    ["Plumber", "Rough plumbing", "7/22/2025", "Blocked", "Need to Respond", "Waiting on permit"],
    ["LA DBS", "Foundation inspection", "7/18/2025", "Completed", "Done!", "Passed"],
    [],  # fully blank row, should be skipped
    ["Electrician", "Rough electrical, panel", "", "Not started, In progress", "Reached out", ""],
]

CHANGELOG_HEADER = [
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

CHANGELOG_GRID = [
    CHANGELOG_HEADER,
    [
        "7/15/2025 9:00:00",
        "bronco@example.com",
        "wk 7/14",
        "5",
        "STATUS",
        "Not started",
        "In progress",
        "Rough framing",
        "Framer",
    ],
    [
        "7/21/2025 14:30:00",
        "bronco@example.com",
        "wk 7/21",
        "6",
        "DETAILS",
        "Reached out",
        "Need to Respond",
        "Rough plumbing",
        "Plumber",
    ],
]


def make_demo_client() -> FakeSheetClient:
    client = FakeSheetClient()
    client.add_tab("wk 7/14", WEEKLY_GRID)
    client.add_tab("Wk 7/21", WEEKLY_GRID)
    client.add_tab("Wk of 7/28", WEEKLY_GRID)
    client.add_tab("Copy of Wk 7/21", WEEKLY_GRID)
    client.add_tab("Change log", CHANGELOG_GRID)
    client.add_tab("AI Brief", [["Section", "Text"], ["", ""]])
    client.add_tab("Ask", [["Question", "Project", "Answer", "Status"]])
    client.add_tab("AI Log", [["Run", "Command", "Status"]])
    return client


def make_sheet_config() -> SheetConfig:
    return SheetConfig(
        spreadsheets=[SpreadsheetConfig(project_id="demo-1", sheet_id_env="SHEET_ID_DEMO")],
        changelog_tab="auto",
        weekly_tab_regex=r"^\s*(wk|week)\s*(of\s*)?(\d{1,2})/(\d{1,2})\s*$",
        ignore_tab_regex=r"^copy of",
        columns=ColumnsConfig(
            sub="SUBCONTRACTOR",
            item="ITEM",
            date=DateColumnConfig(header="DATE", fallback_after="ITEM"),
            status="STATUS",
            details="DETAILS",
            notes="NOTES",
        ),
        ai_columns={"flag": "AI Flag", "next_action": "AI Next Action"},
        agent_tabs=["AI Brief", "Ask", "AI Log"],
        done_status=["Completed", "Cancelled"],
        ball_in_our_court=["Need to Respond", "Needs Clarification", "Seeking Approval"],
        waiting_on_others=["Waiting for Response", "Reached out", "No Answer – Followed Up"],
    )
