"""Burst-exact spike recording from FEAGI's fire history (Fire Ledger).

``GET /v1/burst_engine/fire_history`` returns one frame per burst per area (explicit empty
frames for silent bursts), so frames of different areas line up by burst number. The first
read of an area subscribes it to the Fire Ledger (window = the ``bursts`` asked for), so a
recording is: subscribe, wait, read, release. Reads are capped at ``READ_WINDOW`` bursts (the
service resolves coordinates under the NPU lock) and repeated before the window or the
server's idle TTL runs out, then merged by burst number.

:class:`LedgerCollector` is shared by ``record_spikes`` and the landing check of
``hold_stimulus``. It only needs a client with ``get_fire_history``, ``acquire_fire_history``,
``release_fire_history``, ``get_burst_counter`` and ``get_burst_engine_config``.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import logging
import time
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("feagi_mcp")

MAX_AREAS = 64
MAX_BURSTS = 20_000
# MCP clients cut a tool call that runs too long (one client was measured once cutting at
# about 60 s with "Request timed out"). A foreground recording longer than this is refused
# and pointed at ``background=True``, which returns at once.
FOREGROUND_BUDGET_S = 50.0
READ_WINDOW = 500
WINDOW_SLACK = 100
RE_READ_FRACTION = 0.8
MAX_GAPS_LISTED = 50
MAX_RUNS_LISTED = 20
TOP_VOXELS = 8
DEFAULT_TTL_S = 300.0
# Fire kinds as FEAGI reports them (``fire_kind_names`` in the fire_history payload overrides).
DEFAULT_FIRE_KIND_NAMES = {0: "stdp_eligible", 1: "episodic_memory"}


class LedgerClient(Protocol):
    """The client surface the collector uses."""

    async def get_fire_history(self, area_ids: list[str], bursts: int) -> dict[str, Any]: ...
    def acquire_fire_history(self, area_ids: list[str]) -> None: ...
    async def release_fire_history(self, area_ids: list[str]) -> None: ...
    async def get_burst_counter(self) -> dict[str, Any]: ...
    async def get_burst_engine_config(self) -> dict[str, Any]: ...


class LedgerCollector:
    """Subscribe areas, keep reading their frames, and merge them by burst number."""

    def __init__(self, client: LedgerClient, area_ids: list[str], window: int = READ_WINDOW):
        self.client = client
        self.area_ids = list(area_ids)
        self.window = max(1, min(int(window), READ_WINDOW))
        self.interval_s = 0.005
        self.ttl_s = DEFAULT_TTL_S
        self.start_burst: int | None = None
        self.last_read_burst: int | None = None
        self.names: dict[str, str] = {}
        # frames[area_id][burst] = (voxels, memory_neuron_ids, voxel_fire_kinds, memory_fire_kinds);
        # the kind lists are empty when the server does not report fire kinds.
        self.frames: dict[str, dict[int, tuple[Any, ...]]] = {a: {} for a in self.area_ids}
        self.fire_kind_names: dict[int, str] = dict(DEFAULT_FIRE_KIND_NAMES)
        self.error: dict[str, Any] | None = None
        self._acquired = False
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def reread_s(self) -> float:
        """Seconds between reads: before the window fills and before the TTL expires."""
        return max(0.05, min(RE_READ_FRACTION * self.window * self.interval_s, self.ttl_s / 2))

    async def start(self) -> dict[str, Any] | None:
        """Subscribe the areas. Returns an error payload, or None when subscribed."""
        cfg = await self.client.get_burst_engine_config()
        interval = cfg.get("burst_interval_seconds")
        if isinstance(interval, (int, float)) and interval > 0:
            self.interval_s = float(interval)
        self.client.acquire_fire_history(self.area_ids)
        self._acquired = True
        payload = await self.client.get_fire_history(self.area_ids, self.window)
        if not self._ingest(payload):
            await self.close()
            return self.error
        ttl = payload.get("subscription_ttl_s")
        if isinstance(ttl, (int, float)) and ttl > 0:
            self.ttl_s = float(ttl)
        self.start_burst = self.last_read_burst
        return None

    def _ingest(self, payload: dict[str, Any]) -> bool:
        areas = payload.get("areas")
        current = payload.get("current_burst")
        if payload.get("error") or not isinstance(areas, dict) or not isinstance(current, int):
            self.error = (
                payload
                if payload.get("error")
                else {
                    "error": "unexpected fire_history payload",
                    "keys": sorted(payload),
                }
            )
            return False
        names = payload.get("fire_kind_names")
        if isinstance(names, dict):
            for k, v in names.items():
                if isinstance(v, str) and str(k).lstrip("-").isdigit():
                    self.fire_kind_names[int(k)] = v
        for area_id, entry in areas.items():
            if area_id not in self.frames or not isinstance(entry, dict):
                continue
            if isinstance(entry.get("name"), str):
                self.names[area_id] = entry["name"]
            for frame in entry.get("frames") or []:
                if not isinstance(frame, dict) or not isinstance(frame.get("burst"), int):
                    continue
                voxels = [list(map(int, v)) for v in frame.get("voxels") or []]
                self.frames[area_id][frame["burst"]] = (
                    voxels,
                    [int(n) for n in frame.get("memory_neuron_ids") or []],
                    [int(k) for k in frame.get("voxel_fire_kinds") or []],
                    [int(k) for k in frame.get("memory_fire_kinds") or []],
                )
        self.last_read_burst = current
        return True

    async def read_once(self) -> bool:
        """Read the latest window and merge it. False (error kept) when the read failed."""
        payload = await self.client.get_fire_history(self.area_ids, self.window)
        return self._ingest(payload)

    def begin_pump(self) -> None:
        """Start the background re-reader (call after :meth:`start`)."""
        self._stop.clear()
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.reread_s)
            except asyncio.TimeoutError:
                if not await self.read_once():
                    logger.warning("fire_history re-read failed: %s", self.error)

    async def finish(self) -> None:
        """Stop the re-reader, take the final read, and release the subscription."""
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        try:
            await self.read_once()
        finally:
            await self.close()

    async def close(self) -> None:
        """Release the subscription (idempotent)."""
        if self._acquired:
            self._acquired = False
            try:
                await self.client.release_fire_history(self.area_ids)
            except Exception as e:  # noqa: BLE001 - a failed release must not mask the result
                logger.warning("fire_history release failed: %s", e)


def expand_region_refs(
    refs: list[str], regions: dict[str, Any]
) -> tuple[list[str], list[dict[str, Any]], str | None]:
    """Replace refs naming a brain region by its member area ids (child regions included).

    ``regions`` is the ``regions_members`` payload. A ref matches a region by id, or by an
    exact unique ``title``. Other refs pass through. Returns ``(refs, expanded, error)`` where
    ``expanded`` lists ``{region, areas}`` per expansion; the order is kept and duplicates drop.
    """
    from feagi_mcp.region_circuit import collect_member_areas

    by_title: dict[str, list[str]] = {}
    for rid, entry in regions.items():
        if isinstance(entry, dict) and isinstance(entry.get("title"), str):
            by_title.setdefault(entry["title"].strip(), []).append(rid)
    out: list[str] = []
    expanded: list[dict[str, Any]] = []
    for ref in refs:
        region_id = ref if ref in regions else None
        if region_id is None and len(by_title.get(ref, [])) == 1:
            region_id = by_title[ref][0]
        elif region_id is None and len(by_title.get(ref, [])) > 1:
            return refs, expanded, f"region title '{ref}' matches several regions; use a region id"
        if region_id is None:
            out.append(ref)
            continue
        members, _visited = collect_member_areas(regions, region_id, True)
        expanded.append({"region": region_id, "areas": len(members)})
        out.extend(members)
    return list(dict.fromkeys(out)), expanded, None


def fire_kind_name(collector: LedgerCollector, kind: int) -> str:
    """Name of a fire kind value (``kind_<n>`` when the server named none)."""
    return collector.fire_kind_names.get(kind, f"kind_{kind}")


def _kinds(frame: tuple[Any, ...], i: int, n: int) -> list[int | None]:
    """Fire kinds of a frame's voxel (i=2) or memory (i=3) spikes; None where unreported."""
    kinds = list(frame[i]) if len(frame) > i else []
    return [kinds[j] if j < len(kinds) else None for j in range(n)]


def runs_of(bursts: list[int]) -> list[list[int]]:
    """Consecutive-burst runs ``[[start, end], ...]`` of a sorted burst list."""
    runs: list[list[int]] = []
    for b in bursts:
        if runs and b == runs[-1][1] + 1:
            runs[-1][1] = b
        else:
            runs.append([b, b])
    return runs


MAX_MODAL_VOXELS_LISTED = 32


def modal_pattern_summary(
    frames: dict[int, tuple[Any, ...]], observed: list[int], max_runs: int = MAX_RUNS_LISTED
) -> dict[str, Any]:
    """Modal firing pattern of one area over its ``observed`` bursts.

    A pattern is the set of voxels that fired in one burst (memory neurons have no voxel and
    are left out); a burst with no voxel is an empty burst, not a pattern. ``modal`` is the
    most common pattern (ties go to the earliest first burst) with its burst count and share
    of the non-empty bursts and of all observed bursts. Empty bursts are listed as runs of
    consecutive observed bursts (``empty_runs``, capped by ``max_runs``).
    """
    counts: dict[frozenset[tuple[int, int, int]], list[int]] = {}
    empty: list[int] = []
    for b in observed:
        pattern = frozenset((v[0], v[1], v[2]) for v in frames[b][0])
        if pattern:
            counts.setdefault(pattern, []).append(b)
        else:
            empty.append(b)
    fired = sum(len(v) for v in counts.values())
    runs = runs_of(empty)
    out: dict[str, Any] = {
        "distinct_patterns": len(counts),
        "empty_bursts": len(empty),
        "empty_run_count": len(runs),
        "longest_empty_run": max((r[1] - r[0] + 1 for r in runs), default=0),
        "empty_runs": runs[:max_runs],
        "empty_runs_truncated": len(runs) > max_runs,
        "modal": None,
    }
    if counts:
        pattern, bursts = max(counts.items(), key=lambda kv: (len(kv[1]), -kv[1][0]))
        voxels = sorted(pattern)
        out["modal"] = {
            "voxel_count": len(voxels),
            "voxels": [list(v) for v in voxels[:MAX_MODAL_VOXELS_LISTED]],
            "voxels_truncated": len(voxels) > MAX_MODAL_VOXELS_LISTED,
            "bursts": len(bursts),
            "share_of_fired": round(len(bursts) / fired, 4),
            "share_of_observed": round(len(bursts) / len(observed), 4),
            "first_burst": bursts[0],
            "last_burst": bursts[-1],
        }
    return out


def summarize_frames(
    collector: LedgerCollector,
    first: int,
    last: int,
    max_runs: int = MAX_RUNS_LISTED,
    modal: bool = False,
) -> dict[str, Any]:
    """Per-area summary of the frames in bursts ``first..last`` (inclusive).

    With ``modal`` each area also carries ``modal_pattern`` (see :func:`modal_pattern_summary`).
    """
    window = range(first, last + 1)
    seen_any: set[int] = set()
    areas: dict[str, Any] = {}
    for area_id in collector.area_ids:
        frames = collector.frames[area_id]
        observed = [b for b in window if b in frames]
        seen_any.update(observed)
        fired = [b for b in observed if frames[b][0] or frames[b][1]]
        voxel_counts: dict[tuple[int, int, int], int] = {}
        memory_counts: dict[int, int] = {}
        kind_counts: dict[int, int] = {}
        spikes = 0
        for b in fired:
            voxels, memory = frames[b][0], frames[b][1]
            spikes += len(voxels) + len(memory)
            for k in _kinds(frames[b], 2, len(voxels)) + _kinds(frames[b], 3, len(memory)):
                if k is not None:
                    kind_counts[k] = kind_counts.get(k, 0) + 1
            for n in memory:
                memory_counts[n] = memory_counts.get(n, 0) + 1
            for v in voxels:
                key = (v[0], v[1], v[2])
                voxel_counts[key] = voxel_counts.get(key, 0) + 1
        n_obs = len(observed)
        top = sorted(voxel_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_VOXELS]
        top_memory = sorted(memory_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_VOXELS]
        runs = runs_of(fired)
        areas[area_id] = {
            "name": collector.names.get(area_id, ""),
            "bursts_observed": n_obs,
            "fired_bursts": len(fired),
            "fire_fraction": round(len(fired) / n_obs, 4) if n_obs else None,
            "total_spikes": spikes,
            # dynamic memory neurons have no voxel: counted here and in total_spikes, not in
            # top_voxels
            "memory_spikes": sum(memory_counts.values()),
            # spikes per fire kind name (empty when the server reports no fire kinds)
            "fire_kind_counts": {
                fire_kind_name(collector, k): c for k, c in sorted(kind_counts.items())
            },
            "top_memory_neurons": [
                {
                    "neuron_id": nid,
                    "count": c,
                    "fraction": round(c / n_obs, 4) if n_obs else None,
                }
                for nid, c in top_memory
            ],
            "first_fire_burst": fired[0] if fired else None,
            "last_fire_burst": fired[-1] if fired else None,
            "run_count": len(runs),
            "runs": runs[:max_runs],
            "runs_truncated": len(runs) > max_runs,
            "top_voxels": [
                {
                    "voxel": list(k),
                    "count": c,
                    "fraction": round(c / n_obs, 4) if n_obs else None,
                }
                for k, c in top
            ],
        }
        if modal:
            areas[area_id]["modal_pattern"] = modal_pattern_summary(frames, observed, max_runs)
    gaps = [b for b in window if b not in seen_any]
    return {
        "areas": areas,
        "bursts_observed": len(seen_any),
        "gap_count": len(gaps),
        "gaps": gaps[:MAX_GAPS_LISTED],
    }


def write_spikes_csv(collector: LedgerCollector, first: int, last: int, path: str) -> int:
    """Write one row per spike to ``path``; returns the row count."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "burst",
                "area_id",
                "area_name",
                "x",
                "y",
                "z",
                "memory_neuron_id",
                "fire_kind",
                "fire_kind_name",
            ]
        )
        for burst in range(first, last + 1):
            for area_id in collector.area_ids:
                frame = collector.frames[area_id].get(burst)
                if not frame:
                    continue
                name = collector.names.get(area_id, "")
                vk = _kinds(frame, 2, len(frame[0]))
                mk = _kinds(frame, 3, len(frame[1]))

                def kind_cols(k: int | None) -> list[Any]:
                    return ["", ""] if k is None else [k, fire_kind_name(collector, k)]

                for (x, y, z), k in zip(frame[0], vk, strict=True):
                    writer.writerow([burst, area_id, name, x, y, z, "", *kind_cols(k)])
                    rows += 1
                for neuron_id, k in zip(frame[1], mk, strict=True):
                    writer.writerow([burst, area_id, name, "", "", "", neuron_id, *kind_cols(k)])
                    rows += 1
    return rows


def validate_record_args(area_ids: list[str], bursts: Any, max_runs: Any) -> str | None:
    """Error message for bad ``record_spikes`` arguments, or None."""
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs < 0:
        return "max_runs must be an int >= 0"
    if not area_ids:
        return "areas must be non-empty"
    if len(area_ids) > MAX_AREAS:
        return f"at most {MAX_AREAS} areas per recording"
    if not isinstance(bursts, int) or isinstance(bursts, bool) or not 1 <= bursts <= MAX_BURSTS:
        return f"bursts must be an int in 1..{MAX_BURSTS}"
    return None


def budget_error(bursts: int, interval_s: float, budget_s: float) -> str:
    """Why a foreground recording of ``bursts`` is refused at ``interval_s`` per burst."""
    return (
        f"{bursts} bursts at {interval_s:g} s per burst take about {bursts * interval_s:.0f} s, "
        f"longer than one tool call may wait (~{budget_s:g} s); pass background=True and read "
        "the result with get_spike_recording"
    )


async def record_spikes_window(
    client: Any,
    area_ids: list[str],
    bursts: int,
    csv_path: str | None = None,
    max_runs: int = MAX_RUNS_LISTED,
    cancel: asyncio.Event | None = None,
    budget_s: float | None = None,
    modal: bool = False,
) -> dict[str, Any]:
    """Record ``bursts`` bursts of ``area_ids`` and return the compact summary.

    ``cancel`` (optional) ends the wait early; the summary then covers the bursts recorded so
    far and reports ``cancelled``. ``budget_s`` (optional) refuses a window that would take
    longer than that many seconds at the current burst rate. The subscription is always
    released. ``modal`` adds each area's ``modal_pattern`` summary.
    """
    problem = validate_record_args(area_ids, bursts, max_runs)
    if problem:
        return {"success": False, "error": problem}
    # slack: the last read happens a little after the target burst and must still reach c0 + 1
    collector = LedgerCollector(client, area_ids, window=min(bursts + WINDOW_SLACK, READ_WINDOW))
    err = await collector.start()
    if err is not None:
        return {"success": False, "error": "fire_history subscription failed", "detail": err}
    if budget_s is not None and bursts * collector.interval_s > budget_s:
        await collector.close()
        return {"success": False, "error": budget_error(bursts, collector.interval_s, budget_s)}
    c0 = collector.start_burst or 0
    target = c0 + bursts
    timed_out = cancelled = False
    try:
        collector.begin_pump()
        deadline = time.monotonic() + bursts * collector.interval_s * 2 + 5.0
        while True:
            counter = (await client.get_burst_counter()).get("burst_counter")
            if not isinstance(counter, int):
                return {"success": False, "error": "burst_counter unavailable"}
            if counter >= target:
                break
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            remaining_s = (target - counter) * collector.interval_s
            pause = min(max(remaining_s, 0.002), 0.1)
            if cancel is None:
                await asyncio.sleep(pause)
            else:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(cancel.wait(), timeout=pause)
    finally:
        await collector.finish()
    last_seen = max((b for frames in collector.frames.values() for b in frames), default=c0)
    first, last = c0 + 1, min(target, last_seen)
    summary = summarize_frames(collector, first, last, max_runs, modal)
    result: dict[str, Any] = {
        "success": not timed_out and not cancelled and summary["gap_count"] == 0,
        "first_burst": first,
        "last_burst": last,
        "bursts_requested": bursts,
        "timed_out": timed_out,
        "cancelled": cancelled,
        **summary,
        "csv_path": None,
    }
    if csv_path:
        write_spikes_csv(collector, first, last, csv_path)
        result["csv_path"] = str(Path(csv_path).expanduser().resolve())
    return result
