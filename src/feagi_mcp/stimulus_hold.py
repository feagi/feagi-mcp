"""Hold a stimulus on voxels for a duration without polling per burst.

FEAGI merges a ``manual_stimulation`` post into the *next* burst's fire queue, and the pending
queue dedupes and drains every burst, so posting at twice the burst rate on a wall-clock
schedule lands the stimulus on every burst (a duplicate post inside one burst is harmless).
The loop therefore only posts; it never reads the burst counter or the fire queue per burst.
What landed is read back from the Fire Ledger (:mod:`feagi_mcp.spike_record`), which is
burst-aligned, over the window ``(first_post_burst, last_post_burst + 1]``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

from feagi_mcp.spike_record import MAX_GAPS_LISTED, LedgerCollector
from feagi_mcp.task_registry import public_view

# A foreground hold answers inside one tool call, so it stays below MCP clients' tool-call
# timeout; a background hold returns at once and may run for as long as a background
# ``record_spikes`` window it drives.
MAX_HOLD_S = 30.0
MAX_BACKGROUND_HOLD_S = 600.0
MAX_START_DELAY_S = 30.0
POSTS_PER_BURST = 2.0
SETTLE_BURSTS = 3


def validate_hold_args(
    voxels: Any, duration_s: Any, start_delay_s: Any, background: bool = False
) -> tuple[list[list[int]], float, float] | str:
    """Normalized ``(voxels, duration_s, start_delay_s)`` or an error message."""
    if not isinstance(voxels, list) or not voxels:
        return "voxels must be a non-empty list of [x, y, z]"
    clean: list[list[int]] = []
    for v in voxels:
        if not isinstance(v, (list, tuple)) or len(v) != 3:
            return f"voxel {v!r} is not [x, y, z]"
        clean.append([int(v[0]), int(v[1]), int(v[2])])
    try:
        duration = float(duration_s)
        delay = float(start_delay_s)
    except (TypeError, ValueError):
        return "duration_s and start_delay_s must be numbers"
    cap = MAX_BACKGROUND_HOLD_S if background else MAX_HOLD_S
    if not 0 < duration <= cap:
        mode = "background" if background else "foreground (use background=True for longer)"
        return f"duration_s must be in (0, {cap:g}] for a {mode} hold"
    if not 0 <= delay <= MAX_START_DELAY_S:
        return f"start_delay_s must be in [0, {MAX_START_DELAY_S:g}]"
    return clean, duration, delay


def landing_report(
    frames: dict[int, tuple[list[list[int]], list[int]]],
    voxels: list[list[int]],
    first_post_burst: int,
    last_post_burst: int,
) -> dict[str, Any]:
    """Which bursts in ``(first_post_burst, last_post_burst + 1]`` fired every held voxel."""
    wanted = {tuple(v) for v in voxels}
    window = range(first_post_burst + 1, last_post_burst + 2)
    landed = 0
    no_frame: list[int] = []
    missed: list[int] = []
    for b in window:
        frame = frames.get(b)
        if frame is None:
            no_frame.append(b)
        elif wanted <= {tuple(v) for v in frame[0]}:
            landed += 1
        else:
            missed.append(b)
    return {
        "window": [first_post_burst + 1, last_post_burst + 1],
        "checked": len(window),
        "landed": landed,
        "missed_count": len(missed),
        "missed": missed[:MAX_GAPS_LISTED],
        "no_ledger_frame_count": len(no_frame),
        "no_ledger_frame": no_frame[:MAX_GAPS_LISTED],
    }


def hold_summary(state: dict[str, Any]) -> dict[str, Any]:
    """The public view of a hold record (no internal handles)."""
    return public_view(state)


async def run_hold(
    client: Any,
    state: dict[str, Any],
    area_id: str,
    voxels: list[list[int]],
    duration_s: float,
    start_delay_s: float,
    verify: bool,
) -> dict[str, Any]:
    """Run one hold, updating ``state`` in place; returns the final summary."""
    cancel: asyncio.Event = state["_cancel"]
    collector: LedgerCollector | None = None
    try:
        cfg = await client.get_burst_engine_config()
        interval = cfg.get("burst_interval_seconds")
        if not isinstance(interval, (int, float)) or interval <= 0:
            raise RuntimeError("burst_interval_seconds unavailable from /v1/burst_engine/config")
        state["burst_interval_s"] = float(interval)
        if start_delay_s > 0:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(cancel.wait(), timeout=start_delay_s)
        if cancel.is_set():
            state["state"] = "cancelled"
            return hold_summary(state)
        if verify:
            collector = LedgerCollector(client, [area_id])
            err = await collector.start()
            if err is not None:
                state["verify_error"] = err
                collector = None
            else:
                collector.begin_pump()
        payload = {area_id: voxels}
        first_counter = (await client.get_burst_counter()).get("burst_counter")
        period = interval / POSTS_PER_BURST
        state["state"] = "running"
        started = time.monotonic()
        next_at = started
        posts = failures = late = 0
        while time.monotonic() - started < duration_s and not cancel.is_set():
            res = await client._post_stimulation(payload, "force_fire")
            posts += 1
            if not res.get("success"):
                failures += 1
                state["first_failure"] = state.get("first_failure") or res.get("error")
            next_at += period
            wait = next_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            else:
                late += 1
        last_counter = (await client.get_burst_counter()).get("burst_counter")
        state.update(
            posts_sent=posts,
            post_failures=failures,
            late_posts=late,
            elapsed_s=round(time.monotonic() - started, 3),
            first_post_burst=first_counter,
            last_post_burst=last_counter,
        )
        if (
            collector is not None
            and isinstance(first_counter, int)
            and isinstance(last_counter, int)
        ):
            await asyncio.sleep(SETTLE_BURSTS * interval)
            await collector.finish()
            state["landed"] = landing_report(
                collector.frames[area_id], voxels, first_counter, last_counter
            )
            collector = None
        state["state"] = "cancelled" if cancel.is_set() else "done"
    except Exception as e:  # noqa: BLE001 - reported in the hold record
        state["state"] = "failed"
        state["error"] = str(e)
    finally:
        if collector is not None:
            await collector.close()
    return hold_summary(state)


def new_hold_state(area_id: str, voxels: list[list[int]], duration_s: float) -> dict[str, Any]:
    """A fresh hold record."""
    return {
        "hold_id": uuid.uuid4().hex[:12],
        "state": "pending",
        "area_id": area_id,
        "voxels": voxels,
        "duration_s": duration_s,
        "_cancel": asyncio.Event(),
    }
