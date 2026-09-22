"""Contract suite: every TrackerSource must pass this, parametrized over
`source` (see conftest.py). Adding a new adapter means adding one entry
to SOURCE_BUILDERS and passing this file unmodified.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tracker_agent.core.capabilities import Capability, CapabilityError
from tracker_agent.core.models import Annotation, Answer, Brief

PROJECT = "demo-1"


def test_health_reports_ok(source):
    health = source.health()
    assert health.ok, health.detail


def test_items_returns_expected_items(source):
    result = source.items(PROJECT)

    titles = {item.title for item in result.items}
    assert "Rough framing" in titles
    assert "Rough plumbing" in titles


def test_items_have_stable_ids(source):
    result = source.items(PROJECT)

    ids = [item.id for item in result.items]
    assert len(ids) == len(set(ids)), "item ids must be unique within a project"
    for item_id in ids:
        assert item_id, "item id must not be blank"


def test_items_carry_project(source):
    result = source.items(PROJECT)

    for item in result.items:
        assert item.project == PROJECT


def test_history_returns_changes_when_capable(source):
    if Capability.READ_HISTORY not in source.capabilities:
        return
    changes = source.history(PROJECT)
    assert any(c.field == "status" for c in changes)


def test_history_references_known_item_ids(source):
    if Capability.READ_HISTORY not in source.capabilities:
        return
    item_ids = {item.id for item in source.items(PROJECT).items}
    for change in source.history(PROJECT):
        assert change.item_id in item_ids


def test_write_annotations_dry_run_returns_without_error(source):
    if Capability.WRITE_ANNOTATIONS not in source.capabilities:
        return
    framing = next(i for i in source.items(PROJECT).items if i.title == "Rough framing")

    annotations = [Annotation(item_id=framing.id, field="flag", value="dry-run-only")]
    result = source.write_annotations(PROJECT, annotations, dry_run=True)

    assert result.ok
    assert result.dry_run


def test_write_annotations_diff_reflects_old_and_new_values(source):
    if Capability.WRITE_ANNOTATIONS not in source.capabilities:
        return
    framing = next(i for i in source.items(PROJECT).items if i.title == "Rough framing")

    first = source.write_annotations(
        PROJECT, [Annotation(item_id=framing.id, field="flag", value="🔴 Overdue")], dry_run=False
    )
    assert [d.old for d in first.diff] == [""]
    assert [d.new for d in first.diff] == ["🔴 Overdue"]

    second = source.write_annotations(
        PROJECT, [Annotation(item_id=framing.id, field="flag", value="🟡 Stale")], dry_run=True
    )
    assert [d.old for d in second.diff] == ["🔴 Overdue"]
    assert [d.new for d in second.diff] == ["🟡 Stale"]


def test_write_annotations_is_a_noop_for_unchanged_values(source):
    if Capability.WRITE_ANNOTATIONS not in source.capabilities:
        return
    framing = next(i for i in source.items(PROJECT).items if i.title == "Rough framing")

    source.write_annotations(
        PROJECT, [Annotation(item_id=framing.id, field="flag", value="🔴 Overdue")], dry_run=False
    )
    result = source.write_annotations(
        PROJECT, [Annotation(item_id=framing.id, field="flag", value="🔴 Overdue")], dry_run=False
    )

    assert result.written == 0
    assert result.diff == []


def test_write_annotations_rejects_unknown_field(source):
    if Capability.WRITE_ANNOTATIONS not in source.capabilities:
        return
    framing = next(i for i in source.items(PROJECT).items if i.title == "Rough framing")

    annotations = [Annotation(item_id=framing.id, field="status", value="done")]
    try:
        source.write_annotations(PROJECT, annotations, dry_run=False)
    except ValueError:
        return
    raise AssertionError("expected write_annotations to refuse a non-agent field")


def test_undeclared_capabilities_raise_capability_error(source):
    """The capability flags are the source of truth, not a stack trace.

    For every capability-gated method the source declares it can't do,
    calling it must raise CapabilityError — never NotImplementedError,
    never silently succeed. A feature that only checks `capabilities`
    must never be surprised.
    """
    framing = None
    if Capability.READ_ITEMS in source.capabilities:
        framing = next((i for i in source.items(PROJECT).items if i.title == "Rough framing"), None)
    fake_item_id = framing.id if framing else "nonexistent"

    checks = {
        Capability.WRITE_BRIEF: lambda: source.write_brief(
            Brief(
                project=PROJECT,
                generated_at=dt.datetime.now(),
                snapshot="",
                by_group=[],
                waiting_on={},
                cycle_stats={},
            ),
            dry_run=True,
        ),
        Capability.QUESTIONS: lambda: source.questions(PROJECT),
        Capability.WRITE_ANNOTATIONS: lambda: source.write_annotations(
            PROJECT, [Annotation(item_id=fake_item_id, field="flag", value="x")], dry_run=True
        ),
    }

    for capability, call in checks.items():
        if capability in source.capabilities:
            continue
        with pytest.raises(CapabilityError):
            call()


def test_undeclared_answer_question_raises_capability_error(source):
    if Capability.QUESTIONS in source.capabilities:
        return
    with pytest.raises(CapabilityError):
        source.answer_question("nonexistent", Answer(text="x"), dry_run=True)
