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


def test_blank_status_infers_cancelled_from_details():
    """The real tracker has rows where DETAILS was set to Cancelled but
    STATUS was never updated to match — infer it rather than treating the
    item as not_started (and log why, so it's visible on a --dry-run).
    """
    from tracker_agent.sources.gsheets.raw import FakeSheetClient

    client = FakeSheetClient()
    header = ["SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES"]
    client.add_tab(
        "wk 7/14",
        [header, ["Framer", "stub out for kitchen island", "", "", "Cancelled", "dry run"]],
    )
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    item = result.items[0]
    assert item.status == Status.CANCELLED
    assert any("inferred" in w.message for w in result.warnings)


def test_unrecognized_status_with_unhelpful_details_falls_back_to_not_started():
    """STATUS="Reached out" is really a DETAILS value typed in the wrong
    column; DETAILS itself doesn't imply a lifecycle state here, so this
    should still fall back to not_started (with a warning), not guess.
    """
    from tracker_agent.sources.gsheets.raw import FakeSheetClient

    client = FakeSheetClient()
    header = ["SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES"]
    client.add_tab(
        "wk 7/14",
        [header, ["Framer", "Exterior fixtures", "", "Reached out", "Waiting for Response", ""]],
    )
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    item = result.items[0]
    assert item.status == Status.NOT_STARTED
    assert any(
        "unrecognized STATUS" in w.message and "inferred" not in w.message
        for w in result.warnings
    )


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


def test_ball_stays_independent_of_status_for_inconsistency_detection():
    """DETAILS drives ball, not STATUS, so a Completed row whose DETAILS isn't
    a done_details value keeps a real ball — flags.py's inconsistent rule
    needs to see that disagreement, not have it silently erased here.
    """
    from tracker_agent.sources.gsheets.raw import FakeSheetClient

    client = FakeSheetClient()
    header = ["SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES"]
    client.add_tab(
        "wk 7/14",
        [
            header,
            ["Framer", "Rough framing", "7/20/2025", "Completed", "Need to Respond", ""],
        ],
    )
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    framing = result.items[0]
    assert framing.status == Status.DONE
    assert framing.ball == Ball.US  # not forced to NONE just because STATUS is done


def test_duplicate_item_on_same_tab_warns():
    """Two rows on the same tab sharing (SUBCONTRACTOR, ITEM) text collide
    onto the same item_id (it's a hash of that pair, meant to stay stable
    across weeks) — surface that loudly rather than silently merging them.
    """
    from tracker_agent.sources.gsheets.raw import FakeSheetClient

    client = FakeSheetClient()
    header = ["SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES"]
    client.add_tab(
        "wk 7/14",
        [
            header,
            ["Soil Engineer", "Recompaction", "7/1/2025", "In progress", "On the schedule", ""],
            ["Soil Engineer", "Recompaction", "7/15/2025", "Not started", "", ""],
        ],
    )
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    assert len(result.items) == 2
    assert result.items[0].id == result.items[1].id
    assert any("duplicate item" in w.message for w in result.warnings)


def test_distinct_items_on_same_tab_do_not_warn():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)

    assert not any("duplicate item" in w.message for w in result.warnings)


def test_item_id_is_stable_across_calls():
    client = make_demo_client()
    sheet_config = make_sheet_config()

    result1 = parse_weekly_tab(client, "wk 7/14", "demo-1", sheet_config)
    result2 = parse_weekly_tab(client, "Wk 7/21", "demo-1", sheet_config)

    framing1 = next(item for item in result1.items if item.title == "Rough framing")
    framing2 = next(item for item in result2.items if item.title == "Rough framing")
    assert framing1.id == framing2.id
