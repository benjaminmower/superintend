import pytest

from tracker_agent.config import SheetConfig
from tracker_agent.sheets import AiColumnWriteError, CellUpdate, FakeSheetClient, write_ai_cells


def make_sheet_config() -> SheetConfig:
    return SheetConfig(
        tab="Projects",
        key_column="Project",
        columns={"project": "Project", "status": "Status"},
        ai_columns={"summary": "AI Summary", "flag": "AI Flag"},
    )


def make_client() -> FakeSheetClient:
    client = FakeSheetClient()
    client.add_tab(
        "Projects",
        ["Project", "Status", "AI Summary", "AI Flag"],
        [
            {"Project": "Fake St. Remodel", "Status": "In progress", "AI Summary": "", "AI Flag": ""},
        ],
    )
    return client


def test_write_ai_cells_writes_allowed_headers():
    client = make_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=2, header="AI Summary", value="Framing underway.")]

    write_ai_cells(client, sheet_config, updates, dry_run=False)

    assert client.written == updates
    assert client.read_rows("Projects")[0]["AI Summary"] == "Framing underway."


def test_write_ai_cells_rejects_non_ai_header():
    client = make_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=2, header="Status", value="Done")]

    with pytest.raises(AiColumnWriteError):
        write_ai_cells(client, sheet_config, updates, dry_run=False)

    assert client.written == []
    assert client.read_rows("Projects")[0]["Status"] == "In progress"


def test_write_ai_cells_dry_run_writes_nothing():
    client = make_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=2, header="AI Flag", value="Overdue")]

    result = write_ai_cells(client, sheet_config, updates, dry_run=True)

    assert result == updates
    assert client.written == []
    assert client.read_rows("Projects")[0]["AI Flag"] == ""
