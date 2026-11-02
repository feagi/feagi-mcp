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
import csv
import logging
import time
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("feagi_mcp")

MAX_AREAS = 64
MAX_BURSTS = 20_000
READ_WINDOW = 500
WINDOW_SLACK = 100
RE_READ_FRACTION = 0.8
MAX_GAPS_LISTED = 50
MAX_RUNS_LISTED = 20
TOP_VOXELS = 8
DEFAULT_TTL_S = 300.0


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
        # frames[area_id][burst] = (voxels, memory_neuron_ids)
        self.frames: dict[str, dict[int, tuple[list[list[int]], list[int]]]] = {
            a: {} for a in self.area_ids
        }
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


def runs_of(bursts: list[int]) -> list[list[int]]:
    """Consecutive-burst runs ``[[start, end], ...]`` of a sorted burst list."""
    runs: list[list[int]] = []
    for b in bursts:
        if runs and b == runs[-1][1] + 1:
            runs[-1][1] = b
        else:
            runs.append([b, b])
    return runs


def summarize_frames(
    collector: LedgerCollector, first: int, last: int, max_runs: int = MAX_RUNS_LISTED
) -> dict[str, Any]:
    """Per-area summary of the frames in bursts ``first..last`` (inclusive)."""
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
        spikes = 0
        for b in fired:
            voxels, memory = frames[b]
            spikes += len(voxels) + len(memory)
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
        writer.writerow(["burst", "area_id", "area_name", "x", "y", "z", "memory_neuron_id"])
        for burst in range(first, last + 1):
            for area_id in collector.area_ids:
                frame = collector.frames[area_id].get(burst)
                if not frame:
                    continue
                name = collector.names.get(area_id, "")
                for x, y, z in frame[0]:
                    writer.writerow([burst, area_id, name, x, y, z, ""])
                    rows += 1
                for neuron_id in frame[1]:
                    writer.writerow([burst, area_id, name, "", "", "", neuron_id])
                    rows += 1
    return rows


async def record_spikes_window(
    client: Any,
    area_ids: list[str],
    bursts: int,
    csv_path: str | None = None,
    max_runs: int = MAX_RUNS_LISTED,
) -> dict[str, Any]:
    """Record ``bursts`` bursts of ``area_ids`` and return the compact summary."""
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs < 0:
        return {"success": False, "error": "max_runs must be an int >= 0"}
    if not area_ids:
        return {"success": False, "error": "areas must be non-empty"}
    if len(area_ids) > MAX_AREAS:
        return {"success": False, "error": f"at most {MAX_AREAS} areas per recording"}
    if not isinstance(bursts, int) or isinstance(bursts, bool) or not 1 <= bursts <= MAX_BURSTS:
        return {"success": False, "error": f"bursts must be an int in 1..{MAX_BURSTS}"}
    # slack: the last read happens a little after the target burst and must still reach c0 + 1
    collector = LedgerCollector(client, area_ids, window=min(bursts + WINDOW_SLACK, READ_WINDOW))
    err = await collector.start()
    if err is not None:
        return {"success": False, "error": "fire_history subscription failed", "detail": err}
    c0 = collector.start_burst or 0
    target = c0 + bursts
    timed_out = False
    try:
        collector.begin_pump()
        deadline = time.monotonic() + bursts * collector.interval_s * 2 + 5.0
        while True:
            counter = (await client.get_burst_counter()).get("burst_counter")
            if not isinstance(counter, int):
                return {"success": False, "error": "burst_counter unavailable"}
            if counter >= target:
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            remaining_s = (target - counter) * collector.interval_s
            await asyncio.sleep(min(max(remaining_s, 0.002), 0.1))
    finally:
        await collector.finish()
    last_seen = max((b for frames in collector.frames.values() for b in frames), default=c0)
    first, last = c0 + 1, min(target, last_seen)
    summary = summarize_frames(collector, first, last, max_runs)
    result: dict[str, Any] = {
        "success": not timed_out and summary["gap_count"] == 0,
        "first_burst": first,
        "last_burst": last,
        "bursts_requested": bursts,
        "timed_out": timed_out,
        **summary,
        "csv_path": None,
    }
    if csv_path:
        write_spikes_csv(collector, first, last, csv_path)
        result["csv_path"] = str(Path(csv_path).expanduser().resolve())
    return result
