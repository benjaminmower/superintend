import datetime as dt

from tests.fixtures.demo_sheet import make_demo_client, make_sheet_config
from tracker_agent.parse.weekly import parse_weekly_tab
from tracker_agent.sheets import find_header_row


def test_find_header_row_skips_title_and_blank_rows():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    assert find_header_row(client, "wk 7/14", sheet_config) == 3


def test_fill_down_subcontractor():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", sheet_config)

    subs = [item.sub for item in result.items]
    # "Install shear walls" has no SUBCONTRACTOR of its own; it should
    # inherit "Framer" from the row above.
    assert subs == ["Framer", "Framer", "Plumber", "LA DBS", "Electrician"]


def test_blank_row_is_skipped():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", sheet_config)

    items = [item.item for item in result.items]
    assert "" not in items
    assert len(items) == 5  # the fully blank row and title/header rows don't count


def test_blank_date_header_uses_positional_fallback():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", sheet_config)

    framing = next(item for item in result.items if item.item == "Rough framing")
    assert framing.date == dt.date(2025, 7, 20)


def test_missing_date_parses_as_none():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", sheet_config)

    shear_walls = next(item for item in result.items if item.item == "Install shear walls")
    assert shear_walls.date is None


def test_multiselect_status_takes_last_value_and_warns():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", sheet_config)

    electrical = next(item for item in result.items if "Rough electrical" in item.item)
    assert electrical.status == "In progress"
    assert any("multi-select" in w.message for w in result.warnings)


def test_notes_and_details_pass_through():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", sheet_config)

    plumbing = next(item for item in result.items if item.item == "Rough plumbing")
    assert plumbing.details == "Need to Respond"
    assert plumbing.notes == "Waiting on permit"
    assert plumbing.status == "Blocked"
