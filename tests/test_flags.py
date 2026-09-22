"""flags.py: pure rule evaluation, next-action batching, and run_flag
degradation. No network — LLM calls go through a stub, sources are FakeSource.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tracker_agent import state
from tracker_agent.config import FlagSettings, Settings
from tracker_agent.core.capabilities import Capability
from tracker_agent.core.models import Ball, Change, Item, Status
from tracker_agent.flags import (
    NextAction,
    NextActions,
    evaluate,
    fingerprint,
    run_flag,
    write_next_actions,
)
from tracker_agent.sources.fake import FakeSource

TODAY = dt.date(2025, 8, 4)
PROJECT = "demo-1"


def _settings() -> Settings:
    return Settings(
        model="claude-sonnet-5",
        flags=FlagSettings(our_move_days=2, chase_days=4, due_soon_days=7, stale_days=10),
    )


def _item(**overrides) -> Item:
    defaults = dict(
        id="item-1",
        project=PROJECT,
        group="Framer",
        title="Rough framing",
        due_date=None,
        status=Status.IN_PROGRESS,
        ball=Ball.UNKNOWN,
        notes="",
        last_changed=None,
    )
    defaults.update(overrides)
    return Item(**defaults)


def test_overdue_when_past_due_and_not_done():
    item = _item(due_date=TODAY - dt.timedelta(days=1), status=Status.IN_PROGRESS)
    [result] = evaluate([item], [], _settings(), TODAY)
    assert result.chosen == "overdue"


def test_overdue_does_not_fire_when_done():
    item = _item(
        due_date=TODAY - dt.timedelta(days=1), status=Status.DONE, ball=Ball.NONE
    )
    [result] = evaluate([item], [], _settings(), TODAY)
    assert "overdue" not in result.triggered


def test_blocked_flag():
    item = _item(status=Status.BLOCKED, due_date=TODAY + dt.timedelta(days=30))
    [result] = evaluate([item], [], _settings(), TODAY)
    assert result.chosen == "blocked"


def test_our_move_after_threshold_days_holding_ball():
    item = _item(ball=Ball.US, due_date=TODAY + dt.timedelta(days=30))
    changes = [
        Change(
            item_id=item.id,
            timestamp=dt.datetime.combine(TODAY - dt.timedelta(days=3), dt.time()),
            user="x",
            field="ball",
            old_value="them",
            new_value="us",
        )
    ]
    [result] = evaluate([item], changes, _settings(), TODAY)
    assert result.chosen == "our_move"


def test_our_move_not_triggered_within_threshold():
    item = _item(ball=Ball.US, due_date=TODAY + dt.timedelta(days=30))
    changes = [
        Change(
            item_id=item.id,
            timestamp=dt.datetime.combine(TODAY - dt.timedelta(days=1), dt.time()),
            user="x",
            field="ball",
            old_value="them",
            new_value="us",
        )
    ]
    [result] = evaluate([item], changes, _settings(), TODAY)
    assert result.chosen is None


def test_chase_after_threshold_days_holding_ball():
    item = _item(ball=Ball.THEM, due_date=TODAY + dt.timedelta(days=30))
    changes = [
        Change(
            item_id=item.id,
            timestamp=dt.datetime.combine(TODAY - dt.timedelta(days=5), dt.time()),
            user="x",
            field="ball",
            old_value="us",
            new_value="them",
        )
    ]
    [result] = evaluate([item], changes, _settings(), TODAY)
    assert result.chosen == "chase"


def test_due_soon_for_not_started_within_window():
    item = _item(status=Status.NOT_STARTED, due_date=TODAY + dt.timedelta(days=3))
    [result] = evaluate([item], [], _settings(), TODAY)
    assert result.chosen == "due_soon"


def test_stale_when_no_recent_change():
    item = _item(ball=Ball.US, due_date=TODAY + dt.timedelta(days=30))
    changes = [
        Change(
            item_id=item.id,
            timestamp=dt.datetime.combine(TODAY - dt.timedelta(days=15), dt.time()),
            user="x",
            field="notes",
            old_value="",
            new_value="started",
        )
    ]
    [result] = evaluate([item], changes, _settings(), TODAY)
    # our_move also fires (ball held > our_move_days) and is worse than stale
    assert "stale" in result.triggered
    assert result.chosen == "our_move"


def test_needs_date_when_open_with_no_due_date():
    item = _item(due_date=None, status=Status.IN_PROGRESS, ball=Ball.US)
    [result] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert "needs_date" in result.triggered


def test_inconsistent_when_done_but_ball_still_held():
    item = _item(status=Status.DONE, ball=Ball.US, due_date=TODAY)
    [result] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert result.chosen == "inconsistent"


def test_inconsistent_when_open_but_no_ball():
    item = _item(status=Status.IN_PROGRESS, ball=Ball.NONE, due_date=TODAY + dt.timedelta(days=30))
    [result] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert "inconsistent" in result.triggered


def test_worst_flag_wins_overdue_beats_due_soon():
    item = _item(status=Status.IN_PROGRESS, due_date=TODAY - dt.timedelta(days=1))
    [result] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert result.chosen == "overdue"
    assert result.cell_text == "🔴 Overdue"


def test_done_item_with_no_issues_gets_blank_cell_text():
    item = _item(status=Status.DONE, ball=Ball.NONE, due_date=TODAY - dt.timedelta(days=5))
    [result] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert result.chosen is None
    assert result.cell_text == ""


def test_without_history_skips_our_move_chase_stale():
    item = _item(ball=Ball.US, due_date=TODAY + dt.timedelta(days=30))
    [result] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert result.triggered == []  # would be our_move if history were available


class _StubLlm:
    def __init__(self, response: NextActions | Exception):
        self._response = response
        self.calls = 0

    def __call__(self, *, system, prompt, output_schema, command):
        self.calls += 1
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def test_write_next_actions_maps_known_ids_and_drops_unknown():
    item = _item(status=Status.BLOCKED, due_date=TODAY)
    [flagged] = evaluate([item], [], _settings(), TODAY, have_history=False)
    stub = _StubLlm(
        NextActions(
            actions=[
                NextAction(item_id=item.id, next_action="Call the framer"),
                NextAction(item_id="not-a-real-item", next_action="ignored"),
            ]
        )
    )

    result = write_next_actions([flagged], [], stub)

    assert result == {item.id: "Call the framer"}
    assert stub.calls == 1


def test_write_next_actions_skips_done_items():
    item = _item(status=Status.DONE, ball=Ball.NONE, due_date=None)
    [flagged] = evaluate([item], [], _settings(), TODAY, have_history=False)
    stub = _StubLlm(NextActions(actions=[]))

    result = write_next_actions([flagged], [], stub)

    assert result == {}
    assert stub.calls == 0  # nothing flagged/open to write, no LLM call made


def test_write_next_actions_leaves_batch_blank_on_llm_failure():
    from tracker_agent.llm import LlmOutputError

    item = _item(status=Status.BLOCKED, due_date=TODAY)
    [flagged] = evaluate([item], [], _settings(), TODAY, have_history=False)
    stub = _StubLlm(LlmOutputError("failed twice"))

    result = write_next_actions([flagged], [], stub)

    assert result == {}


def test_fingerprint_stable_for_identical_item_and_flag():
    item = _item(status=Status.BLOCKED, due_date=TODAY, ball=Ball.US, notes="waiting on permit")
    [a] = evaluate([item], [], _settings(), TODAY, have_history=False)
    [b] = evaluate([item], [], _settings(), TODAY, have_history=False)
    assert fingerprint(a) == fingerprint(b)


def test_fingerprint_changes_when_status_changes():
    open_item = _item(status=Status.BLOCKED, due_date=TODAY)
    done_item = _item(status=Status.DONE, ball=Ball.NONE, due_date=TODAY)
    [a] = evaluate([open_item], [], _settings(), TODAY, have_history=False)
    [b] = evaluate([done_item], [], _settings(), TODAY, have_history=False)
    assert fingerprint(a) != fingerprint(b)


def test_write_next_actions_reuses_stored_text_when_fingerprint_unchanged():
    item = _item(status=Status.BLOCKED, due_date=TODAY)
    [flagged] = evaluate([item], [], _settings(), TODAY, have_history=False)
    previous = {item.id: (fingerprint(flagged), "Previously written action")}
    stub = _StubLlm(NextActions(actions=[NextAction(item_id=item.id, next_action="New text")]))

    result = write_next_actions([flagged], [], stub, previous=previous)

    assert result == {item.id: "Previously written action"}
    assert stub.calls == 0  # nothing changed, so the LLM is never called


def test_write_next_actions_regenerates_when_fingerprint_changed():
    item = _item(status=Status.BLOCKED, due_date=TODAY)
    [flagged] = evaluate([item], [], _settings(), TODAY, have_history=False)
    previous = {item.id: ("some-other-fingerprint", "Stale action text")}
    stub = _StubLlm(NextActions(actions=[NextAction(item_id=item.id, next_action="New text")]))

    result = write_next_actions([flagged], [], stub, previous=previous)

    assert result == {item.id: "New text"}
    assert stub.calls == 1


def _seeded_source(*, capabilities=None) -> FakeSource:
    source = FakeSource()
    if capabilities is not None:
        source.capabilities = capabilities
    item = _item(status=Status.BLOCKED, due_date=TODAY)
    source.seed_items(PROJECT, [item])
    return source


def test_run_flag_clears_and_rewrites_every_item():
    source = _seeded_source()
    report = run_flag(source, PROJECT, _settings(), today=TODAY, dry_run=False, use_llm=False)

    assert report.write_result is not None
    # only the flag cell actually changed; next_action was already blank, so
    # write_annotations() treats it as a no-op and never touches that cell
    assert report.write_result.written == 1
    assert source.written_annotation("item-1", "flag") == "🔴 Blocked"
    assert source.written_annotation("item-1", "next_action") is None


def test_run_flag_dry_run_writes_nothing():
    source = _seeded_source()
    report = run_flag(source, PROJECT, _settings(), today=TODAY, dry_run=True, use_llm=False)

    assert report.write_result.dry_run
    assert source.written_annotation("item-1", "flag") is None


def test_run_flag_reuses_next_action_text_on_unchanged_rerun():
    import sqlite3

    source = _seeded_source()
    conn = sqlite3.connect(":memory:")
    conn.executescript(state.SCHEMA)
    stub = _StubLlm(NextActions(actions=[NextAction(item_id="item-1", next_action="First text")]))

    run_flag(
        source, PROJECT, _settings(), today=TODAY, dry_run=False, llm_call=stub, conn=conn
    )
    assert stub.calls == 1
    assert source.written_annotation("item-1", "next_action") == "First text"

    # Second run: nothing about the item changed, so the stored fingerprint
    # matches and the LLM should not be called again.
    stub2 = _StubLlm(NextActions(actions=[NextAction(item_id="item-1", next_action="New text")]))
    run_flag(
        source, PROJECT, _settings(), today=TODAY, dry_run=False, llm_call=stub2, conn=conn
    )
    assert stub2.calls == 0
    assert source.written_annotation("item-1", "next_action") == "First text"


def test_run_flag_dry_run_does_not_persist_fingerprint_state():
    import sqlite3

    source = _seeded_source()
    conn = sqlite3.connect(":memory:")
    conn.executescript(state.SCHEMA)
    stub = _StubLlm(NextActions(actions=[NextAction(item_id="item-1", next_action="First text")]))

    run_flag(source, PROJECT, _settings(), today=TODAY, dry_run=True, llm_call=stub, conn=conn)

    assert state.get_flag_states(conn, PROJECT) == {}


def test_run_flag_degrades_without_read_history():
    capabilities = Capability.READ_ITEMS | Capability.WRITE_ANNOTATIONS
    source = _seeded_source(capabilities=capabilities)

    report = run_flag(source, PROJECT, _settings(), today=TODAY, dry_run=True, use_llm=False)

    assert any("READ_HISTORY" in note for note in report.skipped)


def test_run_flag_degrades_without_write_annotations():
    capabilities = Capability.READ_ITEMS | Capability.READ_HISTORY
    source = _seeded_source(capabilities=capabilities)

    report = run_flag(source, PROJECT, _settings(), today=TODAY, dry_run=True, use_llm=False)

    assert report.write_result is None
    assert any("WRITE_ANNOTATIONS" in note for note in report.skipped)
    assert report.counts.get("blocked") == 1  # flags still computed, just not written


def test_run_flag_raises_when_source_unhealthy():
    source = _seeded_source()
    source.healthy = False

    with pytest.raises(RuntimeError):
        run_flag(source, PROJECT, _settings(), today=TODAY, dry_run=True, use_llm=False)
