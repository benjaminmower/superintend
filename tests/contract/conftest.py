"""Builds one FakeSource and one GSheetsSource with equivalent data, so
tests/contract/test_contract.py can run the same assertions against both.
Any new adapter added later just needs an entry in SOURCE_BUILDERS.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tests.fixtures.demo_sheet import make_demo_client, make_sheet_config
from tracker_agent.core.models import Ball, Change, Item, Status
from tracker_agent.sources.base import TrackerSource
from tracker_agent.sources.fake import FakeSource
from tracker_agent.sources.gsheets.parse_weekly import item_id
from tracker_agent.sources.gsheets.source import GSheetsSource

PROJECT = "demo-1"


def _build_fake_source() -> TrackerSource:
    source = FakeSource()
    framing_id = item_id(PROJECT, "Framer", "Rough framing")
    plumbing_id = item_id(PROJECT, "Plumber", "Rough plumbing")
    source.seed_items(
        PROJECT,
        [
            Item(
                id=framing_id,
                project=PROJECT,
                group="Framer",
                title="Rough framing",
                due_date=dt.date(2025, 7, 20),
                status=Status.IN_PROGRESS,
                ball=Ball.UNKNOWN,
                notes="Started Monday",
                last_changed=dt.datetime(2025, 7, 15, 9, 0, 0),
            ),
            Item(
                id=plumbing_id,
                project=PROJECT,
                group="Plumber",
                title="Rough plumbing",
                due_date=dt.date(2025, 7, 22),
                status=Status.BLOCKED,
                ball=Ball.US,
                notes="Waiting on permit",
                last_changed=dt.datetime(2025, 7, 21, 14, 30, 0),
            ),
        ],
    )
    source.seed_changes(
        PROJECT,
        [
            Change(
                item_id=framing_id,
                timestamp=dt.datetime(2025, 7, 15, 9, 0, 0),
                user="bronco@example.com",
                field="status",
                old_value="Not started",
                new_value="In progress",
            )
        ],
    )
    return source


def _build_gsheets_source() -> TrackerSource:
    client = make_demo_client()
    sheet_config = make_sheet_config()
    return GSheetsSource(client, sheet_config)


SOURCE_BUILDERS = {
    "fake": _build_fake_source,
    "gsheets": _build_gsheets_source,
}


@pytest.fixture(params=list(SOURCE_BUILDERS), ids=list(SOURCE_BUILDERS))
def source(request) -> TrackerSource:
    return SOURCE_BUILDERS[request.param]()
