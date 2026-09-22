"""Phase 1: deterministic flag rules + one LLM-written next action per item.

Feature code only — imports core.*, llm, state, config. Never imports a
source adapter (guardrail 0); the CLI resolves the source and passes in
Items/Changes already read through TrackerSource.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
from pydantic import BaseModel, Field

from tracker_agent import state
from tracker_agent.config import Settings
from tracker_agent.core.capabilities import Capability
from tracker_agent.core.models import Annotation, Ball, Change, Item, Status, WriteResult
from tracker_agent.llm import LlmOutputError, call_llm
from tracker_agent.sources.base import TrackerSource

# Worst flag wins; earlier entries are worse. Each maps to (emoji, label).
RULE_ORDER = [
    "overdue",
    "blocked",
    "our_move",
    "chase",
    "due_soon",
    "stale",
    "needs_date",
    "inconsistent",
]
RULE_TEXT = {
    "overdue": ("🔴", "Overdue"),
    "blocked": ("🔴", "Blocked"),
    "our_move": ("🟠", "Our move"),
    "chase": ("🟡", "Chase"),
    "due_soon": ("🟡", "Due soon"),
    "stale": ("🟡", "Stale"),
    "needs_date": ("⚪", "Needs date"),
    "inconsistent": ("⚪", "Inconsistent"),
}

_DONE_STATUSES = (Status.DONE, Status.CANCELLED)


@dataclass
class ItemFlags:
    item: Item
    triggered: list[str] = field(default_factory=list)  # rule names, in RULE_ORDER order

    @property
    def chosen(self) -> str | None:
        return self.triggered[0] if self.triggered else None

    @property
    def cell_text(self) -> str:
        if self.chosen is None:
            return ""
        emoji, label = RULE_TEXT[self.chosen]
        return f"{emoji} {label}"


def _last_field_change(
    changes_by_item: dict[str, list[Change]], item_id: str, field_name: str
) -> Change | None:
    matches = [c for c in changes_by_item.get(item_id, []) if c.field == field_name]
    if not matches:
        return None
    return max(matches, key=lambda c: c.timestamp or dt.datetime.min)


def _last_change(changes_by_item: dict[str, list[Change]], item_id: str) -> Change | None:
    changes = changes_by_item.get(item_id, [])
    if not changes:
        return None
    return max(changes, key=lambda c: c.timestamp or dt.datetime.min)


def _earliest_timestamp(
    changes_by_item: dict[str, list[Change]], item_id: str
) -> dt.datetime | None:
    timestamps = [c.timestamp for c in changes_by_item.get(item_id, []) if c.timestamp]
    return min(timestamps, default=None)


def _ball_holding_since(
    changes_by_item: dict[str, list[Change]], item_id: str
) -> dt.datetime | None:
    """When the item's current ball holder started holding it: the last "ball"
    field change if there is one, else the item's earliest known change (a
    reasonable floor when the ball has never explicitly changed on record).
    """
    ball_change = _last_field_change(changes_by_item, item_id, "ball")
    if ball_change is not None:
        return ball_change.timestamp
    return _earliest_timestamp(changes_by_item, item_id)


def _days_since(moment: dt.datetime | None, today: dt.date) -> int | None:
    if moment is None:
        return None
    return (today - moment.date()).days


def _index_changes(changes: list[Change]) -> dict[str, list[Change]]:
    index: dict[str, list[Change]] = {}
    for change in changes:
        index.setdefault(change.item_id, []).append(change)
    return index


def _evaluate_one(
    item: Item,
    changes_by_item: dict[str, list[Change]],
    settings: Settings,
    today: dt.date,
    *,
    have_history: bool,
) -> ItemFlags:
    triggered: list[str] = []
    is_done = item.status in _DONE_STATUSES

    if item.due_date is not None and item.due_date < today and not is_done:
        triggered.append("overdue")
    if item.status == Status.BLOCKED:
        triggered.append("blocked")

    if have_history:
        days_on_ball = _days_since(_ball_holding_since(changes_by_item, item.id), today)

        if (
            item.ball == Ball.US
            and days_on_ball is not None
            and days_on_ball > settings.flags.our_move_days
        ):
            triggered.append("our_move")
        if (
            item.ball == Ball.THEM
            and days_on_ball is not None
            and days_on_ball > settings.flags.chase_days
        ):
            triggered.append("chase")

    if (
        item.due_date is not None
        and not is_done
        and item.status == Status.NOT_STARTED
        and 0 <= (item.due_date - today).days <= settings.flags.due_soon_days
    ):
        triggered.append("due_soon")

    if have_history and not is_done:
        last = _last_change(changes_by_item, item.id)
        days_stale = _days_since(last.timestamp, today) if last else None
        if days_stale is not None and days_stale > settings.flags.stale_days:
            triggered.append("stale")

    if not is_done and item.due_date is None:
        triggered.append("needs_date")

    ball_says_done = item.ball == Ball.NONE
    if is_done and not ball_says_done:
        triggered.append("inconsistent")
    elif not is_done and ball_says_done:
        triggered.append("inconsistent")

    triggered.sort(key=RULE_ORDER.index)
    return ItemFlags(item=item, triggered=triggered)


def evaluate(
    items: list[Item],
    changes: list[Change],
    settings: Settings,
    today: dt.date,
    *,
    have_history: bool = True,
) -> list[ItemFlags]:
    """Pure: no I/O. `have_history` should be False when the source lacks
    READ_HISTORY, which drops the change-log-dependent rules (our_move,
    chase, stale) rather than crashing on an empty change list.
    """
    changes_by_item = _index_changes(changes)
    return [
        _evaluate_one(item, changes_by_item, settings, today, have_history=have_history)
        for item in items
    ]


class NextAction(BaseModel):
    item_id: str
    next_action: str = Field(max_length=100)


class NextActions(BaseModel):
    actions: list[NextAction]


class LlmCall(Protocol):
    def __call__(
        self, *, system: str, prompt: str, output_schema: type[NextActions], command: str
    ) -> NextActions: ...


def _format_recent_changes(changes_by_item: dict[str, list[Change]], item_id: str) -> str:
    changes = sorted(
        changes_by_item.get(item_id, []), key=lambda c: c.timestamp or dt.datetime.min
    )[-3:]
    if not changes:
        return "(no recorded changes)"
    lines = []
    for c in changes:
        when = c.timestamp.date().isoformat() if c.timestamp else "unknown date"
        lines.append(f"- {when}: {c.field} {c.old_value!r} -> {c.new_value!r}")
    return "\n".join(lines)


def _batches(flagged: list[ItemFlags], size: int = 20) -> list[list[ItemFlags]]:
    return [flagged[i : i + size] for i in range(0, len(flagged), size)]


def fingerprint(item_flags: ItemFlags) -> str:
    """Identifies "has anything about this item's situation changed" between
    runs, so write_next_actions() only re-asks the LLM (and risks different
    wording for an identical situation) when something actually moved.
    """
    item = item_flags.item
    parts = [
        item_flags.chosen or "",
        item.status.value,
        item.ball.value,
        item.due_date.isoformat() if item.due_date else "",
        item.notes,
    ]
    return "|".join(parts)


def write_next_actions(
    flagged: list[ItemFlags],
    changes: list[Change],
    llm_call: LlmCall,
    *,
    previous: dict[str, tuple[str, str]] | None = None,
) -> dict[str, str]:
    """Returns item_id -> next_action for every flagged, non-done item.

    `llm_call(system, prompt, output_schema, command) -> NextActions` — normally
    a thin wrapper around llm.call_llm(); tests pass a stub. Ids the model
    doesn't recognize or invents are dropped. A batch that fails validation
    twice (LlmOutputError) leaves that batch's items with a blank next action
    rather than failing the whole run.

    `previous` is item_id -> (fingerprint, next_action) from the last run
    (state.get_flag_states()). An item whose fingerprint() is unchanged
    reuses its stored next_action verbatim instead of calling the LLM again,
    so a rerun with nothing changed produces byte-identical output.
    """
    previous = previous or {}
    changes_by_item = _index_changes(changes)
    candidates = [
        f for f in flagged if f.chosen is not None and f.item.status not in _DONE_STATUSES
    ]

    results: dict[str, str] = {}
    to_write: list[ItemFlags] = []
    for f in candidates:
        prev = previous.get(f.item.id)
        if prev is not None and prev[0] == fingerprint(f):
            results[f.item.id] = prev[1]
        else:
            to_write.append(f)

    for batch in _batches(to_write):
        valid_ids = {f.item.id for f in batch}
        lines = []
        for f in batch:
            _, label = RULE_TEXT[f.chosen]
            lines.append(
                f"id: {f.item.id}\n"
                f"group: {f.item.group}\n"
                f"title: {f.item.title}\n"
                f"status: {f.item.status.value}\n"
                f"ball: {f.item.ball.value}\n"
                f"notes: {f.item.notes}\n"
                f"flag: {label} (triggered: {', '.join(f.triggered)})\n"
                f"recent changes:\n{_format_recent_changes(changes_by_item, f.item.id)}\n"
            )
        prompt = (
            "For each item below, write one next action a superintendent should "
            "take, under 100 characters, specific and actionable "
            "(e.g. \"Text the framer for the sewer connection answer; waiting 6 days.\"). "
            "Return one entry per item id.\n\n" + "\n---\n".join(lines)
        )
        system = (
            "You write short, specific next actions for a construction tracker. "
            "Respond with ONLY a single JSON object matching this schema, no prose, "
            'no markdown fences: {"actions": [{"item_id": "<id>", "next_action": '
            '"<string, max 100 chars>"}, ...]}'
        )
        try:
            parsed = llm_call(
                system=system,
                prompt=prompt,
                output_schema=NextActions,
                command="flag",
            )
        except LlmOutputError:
            continue
        for action in parsed.actions:
            if action.item_id in valid_ids:
                results[action.item_id] = action.next_action

    return results


@dataclass
class FlagReport:
    flagged: list[ItemFlags]
    counts: dict[str, int]
    write_result: WriteResult | None
    skipped: list[str] = field(default_factory=list)  # human-readable reasons for degradation


def run_flag(
    source: TrackerSource,
    project: str,
    settings: Settings,
    *,
    today: dt.date,
    dry_run: bool,
    use_llm: bool = True,
    anthropic_client: anthropic.Anthropic | None = None,
    llm_call: LlmCall | None = None,
    conn: sqlite3.Connection | None = None,
) -> FlagReport:
    """`llm_call` overrides the default `call_llm`-backed wrapper — tests pass
    a stub instead of faking an `anthropic.Anthropic` client. Ignored if
    `use_llm` is False.
    """
    health = source.health()
    if not health.ok:
        raise RuntimeError(f"source not healthy, refusing to write: {health.detail}")

    if Capability.READ_ITEMS not in source.capabilities:
        raise RuntimeError("source lacks READ_ITEMS; can't run flag")

    result = source.items(project)
    items = result.items

    have_history = Capability.READ_HISTORY in source.capabilities
    changes: list[Change] = source.history(project) if have_history else []

    skipped = []
    if not have_history:
        skipped.append("no READ_HISTORY: skipping our_move, chase, and stale rules")

    flagged = evaluate(items, changes, settings, today, have_history=have_history)

    next_actions: dict[str, str] = {}
    new_states: dict[str, tuple[str, str]] = {}
    if use_llm:
        conn = conn or state.connect()
        previous = state.get_flag_states(conn, project)

        if llm_call is None:
            client = anthropic_client or anthropic.Anthropic()

            def llm_call(*, system: str, prompt: str, output_schema: type, command: str):
                return call_llm(
                    client=client,
                    model=settings.model,
                    system=system,
                    prompt=prompt,
                    output_schema=output_schema,
                    command=command,
                    conn=conn,
                )

        next_actions = write_next_actions(flagged, changes, llm_call, previous=previous)
        for f in flagged:
            action = next_actions.get(f.item.id)
            if action is not None:
                new_states[f.item.id] = (fingerprint(f), action)
    else:
        skipped.append("--no-llm: next actions left blank")

    # Clear-and-rewrite: every item gets an annotation (blank if unflagged/done),
    # so text carried over on a duplicated tab never survives a run.
    annotations = []
    for f in flagged:
        annotations.append(Annotation(item_id=f.item.id, field="flag", value=f.cell_text))
        annotations.append(
            Annotation(
                item_id=f.item.id, field="next_action", value=next_actions.get(f.item.id, "")
            )
        )

    write_result = None
    if Capability.WRITE_ANNOTATIONS not in source.capabilities:
        skipped.append("no WRITE_ANNOTATIONS: flags computed but not written")
    else:
        write_result = source.write_annotations(project, annotations, dry_run=dry_run)

    # Only persist fingerprints for a real write — a --dry-run must have no
    # side effects, and a skipped/failed write shouldn't poison future reuse.
    if use_llm and new_states and not dry_run and write_result is not None:
        conn = conn or state.connect()
        state.set_flag_states(conn, project, new_states)

    counts: dict[str, int] = {}
    for f in flagged:
        if f.chosen:
            counts[f.chosen] = counts.get(f.chosen, 0) + 1

    return FlagReport(flagged=flagged, counts=counts, write_result=write_result, skipped=skipped)
