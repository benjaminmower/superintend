from datetime import date

import pytest

from tracker_agent.sheets import (
    AiColumnWriteError,
    CellUpdate,
    FakeSheetClient,
    NoWeeklyTabFoundError,
    latest_weekly_tab,
    write_ai_cells,
)

WEEKLY_HEADERS = ["Project", "Status", "AI Summary", "AI Flag"]
WEEKLY_ALLOWED = {"AI Summary", "AI Flag"}


def weekly_row() -> dict[str, str]:
    return {"Project": "Fake St. Remodel", "Status": "In progress", "AI Summary": "", "AI Flag": ""}


def make_client_with_weekly_tabs() -> FakeSheetClient:
    client = FakeSheetClient()
    for name in ["wk 09/07", "wk 09/14", "wk 09/21"]:
        client.add_tab(name, WEEKLY_HEADERS, [weekly_row()])
    client.add_tab("Change log", ["Cell", "Old", "New", "Timestamp", "User"], [])
    client.add_tab("AI Brief", ["Section", "Text"], [{"Section": "", "Text": ""}])
    client.add_tab("Ask", ["Question", "Answer", "Status"], [])
    client.add_tab("AI Log", ["Run", "Command", "Status"], [])
    return client


def test_write_ai_cells_writes_allowed_headers():
    client = make_client_with_weekly_tabs()
    updates = [CellUpdate(row=2, header="AI Summary", value="Framing underway.")]

    write_ai_cells(client, "wk 09/21", WEEKLY_ALLOWED, updates, dry_run=False)

    assert client.written == updates
    assert client.read_rows("wk 09/21")[0]["AI Summary"] == "Framing underway."


def test_write_ai_cells_rejects_non_ai_header():
    client = make_client_with_weekly_tabs()
    updates = [CellUpdate(row=2, header="Status", value="Done")]

    with pytest.raises(AiColumnWriteError):
        write_ai_cells(client, "wk 09/21", WEEKLY_ALLOWED, updates, dry_run=False)

    assert client.written == []
    assert client.read_rows("wk 09/21")[0]["Status"] == "In progress"


def test_write_ai_cells_dry_run_writes_nothing():
    client = make_client_with_weekly_tabs()
    updates = [CellUpdate(row=2, header="AI Flag", value="Overdue")]

    result = write_ai_cells(client, "wk 09/21", WEEKLY_ALLOWED, updates, dry_run=True)

    assert result == updates
    assert client.written == []
    assert client.read_rows("wk 09/21")[0]["AI Flag"] == ""


def test_write_ai_cells_allows_anything_on_wholly_owned_tab():
    client = make_client_with_weekly_tabs()
    updates = [CellUpdate(row=2, header="Section", value="Overview")]

    write_ai_cells(client, "AI Brief", None, updates, dry_run=False)

    assert client.written == updates


def test_latest_weekly_tab_picks_max_date():
    client = make_client_with_weekly_tabs()

    assert latest_weekly_tab(client, today=date(2025, 9, 22)) == "wk 09/21"


def test_latest_weekly_tab_handles_year_rollover():
    client = FakeSheetClient()
    client.add_tab("wk 12/29", WEEKLY_HEADERS, [weekly_row()])
    client.add_tab("wk 01/05", WEEKLY_HEADERS, [weekly_row()])

    # "Today" is early January; "wk 12/29" belongs to last year, so
    # "wk 01/05" (this year) is the latest tab, not the other way around.
    assert latest_weekly_tab(client, today=date(2026, 1, 6)) == "wk 01/05"


def test_latest_weekly_tab_raises_when_no_tab_matches():
    client = FakeSheetClient()
    client.add_tab("Ask", ["Question"], [])

    with pytest.raises(NoWeeklyTabFoundError):
        latest_weekly_tab(client, today=date(2025, 9, 22))
