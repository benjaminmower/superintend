"""Contract suite: every TrackerSource must pass this, parametrized over
`source` (see conftest.py). Adding a new adapter means adding one entry
to SOURCE_BUILDERS and passing this file unmodified.
"""

from __future__ import annotations

from tracker_agent.core.capabilities import Capability
from tracker_agent.core.models import Annotation

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
    assert any(c.field == "STATUS" for c in changes)


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
