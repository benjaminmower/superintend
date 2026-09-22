import pytest

from tests.fixtures.demo_sheet import make_demo_client, make_sheet_config
from tracker_agent.sources.gsheets.raw import (
    AiColumnWriteError,
    CellUpdate,
    NotAgentTabError,
    NoWeeklyTabFoundError,
    classify_tab,
    latest_weekly_tab,
    write_agent_tab,
    write_ai_cells,
    write_ai_cells_and_log,
)


def test_classify_tab_recognizes_weekly_tab_name_variants():
    sheet_config = make_sheet_config()
    for name in ["wk 7/14", "Wk 7/21", "Wk of 7/28", "week 12/1", "WK OF 8/18"]:
        assert classify_tab(name, sheet_config) == "weekly", name


def test_classify_tab_ignores_copy_of_tabs():
    sheet_config = make_sheet_config()
    assert classify_tab("Copy of Wk 7/21", sheet_config) == "ignored"


def test_classify_tab_other_for_unrelated_names():
    sheet_config = make_sheet_config()
    assert classify_tab("AI Brief", sheet_config) == "other"


def test_latest_weekly_tab_picks_most_recent_by_sheet_order():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    assert latest_weekly_tab(client, sheet_config, start_year=2025) == "Wk of 7/28"


def test_latest_weekly_tab_handles_year_rollover():
    from tracker_agent.sources.gsheets.raw import FakeSheetClient

    client = FakeSheetClient()
    header = ["SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES"]
    for name in ["wk 12/1", "wk 12/29", "wk 1/5"]:
        client.add_tab(name, [header])
    sheet_config = make_sheet_config()

    assert latest_weekly_tab(client, sheet_config, start_year=2025) == "wk 1/5"


def test_latest_weekly_tab_raises_when_no_weekly_tab():
    from tracker_agent.sources.gsheets.raw import FakeSheetClient

    client = FakeSheetClient()
    client.add_tab("Change log", [["Timestamp", "User", "Sheet Name"]])
    sheet_config = make_sheet_config()

    with pytest.raises(NoWeeklyTabFoundError):
        latest_weekly_tab(client, sheet_config, start_year=2025)


def test_write_ai_cells_allows_listed_headers():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=4, header="AI Flag", value="🔴 Overdue")]

    write_ai_cells(client, "Wk of 7/28", sheet_config, updates, dry_run=False)

    row = client.read_rows("Wk of 7/28", header_row=3)[0]
    assert row["AI Flag"] == "🔴 Overdue"


def test_write_ai_cells_rejects_human_column():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=4, header="STATUS", value="Completed")]

    with pytest.raises(AiColumnWriteError):
        write_ai_cells(client, "Wk of 7/28", sheet_config, updates, dry_run=False)


def test_write_ai_cells_dry_run_writes_nothing():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=4, header="AI Next Action", value="Chase the framer")]

    write_ai_cells(client, "Wk of 7/28", sheet_config, updates, dry_run=True)

    row = client.read_rows("Wk of 7/28", header_row=3)[0]
    assert row.get("AI Next Action", "") == ""


def test_write_agent_tab_allows_agent_owned_tab():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=2, header="Section", value="Project snapshot")]

    write_agent_tab(client, "AI Brief", sheet_config, updates, dry_run=False)

    row = client.read_rows("AI Brief", header_row=1)[0]
    assert row["Section"] == "Project snapshot"


def test_write_agent_tab_rejects_non_agent_tab():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    updates = [CellUpdate(row=4, header="AI Flag", value="🔴 Overdue")]

    with pytest.raises(NotAgentTabError):
        write_agent_tab(client, "Wk of 7/28", sheet_config, updates, dry_run=False)


def test_write_ai_cells_and_log_writes_both_tabs_in_one_call():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    ai_updates = [CellUpdate(row=4, header="AI Flag", value="🔴 Overdue")]
    log_updates = [CellUpdate(row=2, header="Run", value="2025-08-01T00:00:00")]

    write_ai_cells_and_log(
        client, "Wk of 7/28", "AI Log", sheet_config, ai_updates, log_updates, dry_run=False
    )

    ai_row = client.read_rows("Wk of 7/28", header_row=3)[0]
    assert ai_row["AI Flag"] == "🔴 Overdue"
    log_row = client.read_rows("AI Log", header_row=1)[0]
    assert log_row["Run"] == "2025-08-01T00:00:00"


def test_write_ai_cells_and_log_dry_run_writes_nothing():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    ai_updates = [CellUpdate(row=4, header="AI Flag", value="🔴 Overdue")]
    log_updates = [CellUpdate(row=2, header="Run", value="2025-08-01T00:00:00")]

    write_ai_cells_and_log(
        client, "Wk of 7/28", "AI Log", sheet_config, ai_updates, log_updates, dry_run=True
    )

    ai_row = client.read_rows("Wk of 7/28", header_row=3)[0]
    assert ai_row.get("AI Flag", "") == ""


def test_write_ai_cells_and_log_rejects_human_column():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    ai_updates = [CellUpdate(row=4, header="STATUS", value="Completed")]

    with pytest.raises(AiColumnWriteError):
        write_ai_cells_and_log(
            client, "Wk of 7/28", "AI Log", sheet_config, ai_updates, [], dry_run=False
        )


def test_write_ai_cells_and_log_allows_empty_log_tab_not_configured():
    client = make_demo_client()
    sheet_config = make_sheet_config()
    sheet_config.agent_tabs = ["AI Brief", "Ask"]  # no "AI Log"
    ai_updates = [CellUpdate(row=4, header="AI Flag", value="🔴 Overdue")]

    write_ai_cells_and_log(
        client, "Wk of 7/28", "AI Log", sheet_config, ai_updates, [], dry_run=False
    )

    ai_row = client.read_rows("Wk of 7/28", header_row=3)[0]
    assert ai_row["AI Flag"] == "🔴 Overdue"
