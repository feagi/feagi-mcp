"""Registry rules shared by background tools (stimulus holds, spike recordings).

Each record is a dict with a ``state`` key. A pending or running record is never dropped,
because it carries the cancel handle; finished records are pruned oldest first.
"""

from __future__ import annotations

from typing import Any

ACTIVE_STATES = ("pending", "running")
MAX_FINISHED_RECORDS = 20


def prune_finished(records: dict[str, dict[str, Any]], limit: int) -> None:
    """Drop the oldest finished records until at most ``limit`` remain.

    The registry can exceed ``limit`` while more than ``limit`` records are active; every
    background task is bounded in time by its own tool's limits.
    """
    for key in list(records):
        if len(records) <= limit:
            return
        if records[key]["state"] not in ACTIVE_STATES:
            del records[key]


def public_view(state: dict[str, Any]) -> dict[str, Any]:
    """A record without its internal handles (keys starting with ``_``)."""
    return {k: v for k, v in state.items() if not k.startswith("_")}
