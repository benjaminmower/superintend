"""GSheetsSource: behavior specific to this adapter (not covered by the
generic contract suite), like handling a configured agent tab that doesn't
actually exist on the spreadsheet yet.
"""

from __future__ import annotations

import pytest

from tests.fixtures.demo_sheet import make_demo_client, make_sheet_config
from tracker_agent.core.models import Annotation
from tracker_agent.sources.gsheets.source import GSheetsSource

PROJECT = "demo-1"


def _source_without_ai_log() -> GSheetsSource:
    """A demo client/config identical to the fixture but with the AI Log
    tab removed, mimicking a real sheet where the headers were added but
    the log tab itself wasn't created yet.
    """
    client = make_demo_client()
    client._tabs.pop("AI Log")
    sheet_config = make_sheet_config()
    return GSheetsSource(client, sheet_config)


def test_write_annotations_dry_run_does_not_require_ai_log_tab():
    """A --dry-run must be safe to try even before AI Log exists — it never
    appends a log row, so it should never need to read that tab at all.
    """
    source = _source_without_ai_log()
    framing_id = next(i.id for i in source.items(PROJECT).items if i.title == "Rough framing")

    result = source.write_annotations(
        PROJECT, [Annotation(item_id=framing_id, field="flag", value="🔴 Overdue")], dry_run=True
    )

    assert result.ok
    assert result.dry_run


def test_write_annotations_real_write_raises_clear_error_without_ai_log_tab():
    source = _source_without_ai_log()
    framing_id = next(i.id for i in source.items(PROJECT).items if i.title == "Rough framing")

    with pytest.raises(ValueError, match="AI Log"):
        source.write_annotations(
            PROJECT,
            [Annotation(item_id=framing_id, field="flag", value="🔴 Overdue")],
            dry_run=False,
        )


def test_write_annotations_flags_colliding_rows_for_consolidation_instead_of_guessing():
    """Two rows on the same tab with identical (SUBCONTRACTOR, ITEM) text hash
    to the same item_id but may be genuinely different tasks (e.g. one done,
    one still open, with different notes) — write_annotations() must not
    apply flags.py's single computed flag/next_action to both as if they
    were the same item. Instead each row gets a "consolidate with row N"
    flag, pointing at the other row(s), and a blank next_action.
    """
    client = make_demo_client()
    header = [
        "SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES", "AI Flag", "AI Next Action",
    ]
    client.add_tab(
        "Wk of 7/28",
        [
            ["Fake Construction Co. Weekly Report - 123 Invented St"],
            [],
            header,
            ["Soil Engineer", "Recompaction", "7/1/2025", "In progress", "On the schedule", ""],
            ["Soil Engineer", "Recompaction", "7/15/2025", "Not started", "", ""],
        ],
    )
    sheet_config = make_sheet_config()
    source = GSheetsSource(client, sheet_config)

    dup_id = next(i.id for i in source.items(PROJECT).items if i.title == "Recompaction")
    result = source.write_annotations(
        PROJECT,
        [
            Annotation(item_id=dup_id, field="flag", value="🟡 Stale"),
            Annotation(item_id=dup_id, field="next_action", value="Some LLM-written text"),
        ],
        dry_run=False,
    )

    row1 = client.read_rows("Wk of 7/28", header_row=3)[0]
    row2 = client.read_rows("Wk of 7/28", header_row=3)[1]
    assert row1["AI Flag"] == "⚠️ Duplicate — consolidate with row 5"
    assert row2["AI Flag"] == "⚠️ Duplicate — consolidate with row 4"
    assert row1["AI Next Action"] == ""
    assert row2["AI Next Action"] == ""
    assert result.written == 2  # only the two flag cells; next_action was already blank


def test_write_annotations_consolidate_message_lists_all_rows_for_three_way_collision():
    client = make_demo_client()
    header = [
        "SUBCONTRACTOR", "ITEM", "", "STATUS", "DETAILS", "NOTES", "AI Flag", "AI Next Action",
    ]
    client.add_tab(
        "Wk of 7/28",
        [
            ["Fake Construction Co. Weekly Report - 123 Invented St"],
            [],
            header,
            ["Plumber", "Meter placement", "7/1/2025", "Completed", "Done!", ""],
            ["Plumber", "Meter placement", "", "Not started", "Needs Clarification", ""],
            ["Plumber", "Meter Placement", "", "Not started", "Waiting for Response", ""],
        ],
    )
    sheet_config = make_sheet_config()
    source = GSheetsSource(client, sheet_config)

    dup_id = next(i.id for i in source.items(PROJECT).items if "meter placement" in i.title.lower())
    source.write_annotations(
        PROJECT, [Annotation(item_id=dup_id, field="flag", value="🟡 Stale")], dry_run=False
    )

    rows = client.read_rows("Wk of 7/28", header_row=3)
    assert rows[0]["AI Flag"] == "⚠️ Duplicate — consolidate with rows 5, 6"
    assert rows[1]["AI Flag"] == "⚠️ Duplicate — consolidate with rows 4, 6"
    assert rows[2]["AI Flag"] == "⚠️ Duplicate — consolidate with rows 4, 5"
