"""Capability flags a TrackerSource declares.

Feature code checks capabilities before calling a method that needs
them, instead of assuming every source can do everything a Sheet can.
Sources degrade instead of crashing: without READ_HISTORY, staleness
falls back to snapshots in state.db and the brief drops its cycle
stats; without WRITE_ANNOTATIONS, flags go to the email and the brief
only. Every feature declares what it needs and says plainly what it's
skipping.
"""

from __future__ import annotations

from enum import Flag, auto


class Capability(Flag):
    READ_ITEMS = auto()
    READ_HISTORY = auto()
    WRITE_ANNOTATIONS = auto()  # can write the AI flag/next-action columns onto items
    WRITE_BRIEF = auto()  # can rewrite the fully agent-owned brief
    QUESTIONS = auto()  # supports the Ask-tab equivalent (questions()/answer_question())
    ATTACHMENTS = auto()  # can read/write file attachments on items
    WEBHOOKS = auto()  # can push changes instead of being polled

    NONE = 0


def requires(capabilities: Capability, required: Capability) -> None:
    """Raise if `capabilities` doesn't include everything in `required`."""
    missing = required & ~capabilities
    if missing:
        raise CapabilityError(f"missing required capabilities: {missing!r}")


class CapabilityError(ValueError):
    """Raised when a source is asked to do something it didn't declare it can."""
