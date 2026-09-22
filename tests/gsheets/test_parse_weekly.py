import datetime as dt

from tests.fixtures.demo_sheet import make_demo_client, make_sheet_config
from tracker_agent.core.models import Ball, Status
from tracker_agent.sources.gsheets.parse_weekly import parse_weekly_tab
from tracker_agent.sources.gsheets.raw import find_header_row


def test_find_header_row_skips_title_and_blank_rows():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    assert find_header_row(client, "wk 7/14", sheet_config) == 3


def test_fill_down_subcontractor():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    groups = [item.group for item in result.items]
    # "Install shear walls" has no SUBCONTRACTOR of its own; it should
    # inherit "Framer" from the row above.
    assert groups == ["Framer", "Framer", "Plumber", "LA DBS", "Electrician"]


def test_blank_row_is_skipped():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    titles = [item.title for item in result.items]
    assert "" not in titles
    assert len(titles) == 5  # the fully blank row and title/header rows don't count


def test_blank_date_header_uses_positional_fallback():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    framing = next(item for item in result.items if item.title == "Rough framing")
    assert framing.due_date == dt.date(2025, 7, 20)


def test_missing_date_parses_as_none():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    shear_walls = next(item for item in result.items if item.title == "Install shear walls")
    assert shear_walls.due_date is None


def test_multiselect_status_takes_last_value_and_warns():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    electrical = next(item for item in result.items if "Rough electrical" in item.title)
    assert electrical.status == Status.IN_PROGRESS
    assert any("multi-select" in w.message for w in result.warnings)


def test_notes_and_details_pass_through():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    plumbing = next(item for item in result.items if item.title == "Rough plumbing")
    assert plumbing.raw["ball_detail"] == "Need to Respond"
    assert plumbing.notes == "Waiting on permit"
    assert plumbing.status == Status.BLOCKED


def test_ball_classification_from_details():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    plumbing = next(item for item in result.items if item.title == "Rough plumbing")
    assert plumbing.ball == Ball.US  # "Need to Respond" -> ball_in_our_court

    inspection = next(item for item in result.items if item.title == "Foundation inspection")
    assert inspection.status == Status.DONE
    assert inspection.ball == Ball.NONE  # done items have no ball to hold


def test_item_id_is_stable_across_calls():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result1 = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)
    result2 = parse_weekly_tab(client, "Wk 7/21", "demo-1", sheet_config)

    framing1 = next(item for item in result1.items if item.title == "Rough framing")
    framing2 = next(item for item in result2.items if item.title == "Rough framing")
    assert framing1.id == framing2.id
