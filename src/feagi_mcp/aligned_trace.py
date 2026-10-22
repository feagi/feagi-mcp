"""One timeline that pairs FEAGI bursts with controller physics samples.

``GET /v1/burst_engine/fire_queue/detailed`` returns the fire queue of the last
*sampled* burst with its burst number in ``timestep`` (the FCL sampler runs at
about 30 Hz, so most bursts of a 40 Hz engine are seen). Fetching it together
with the controller's ``GET /v1/state`` gives, per burst, which voxels of the
watched areas fired and what the body was doing at that moment.

The full trace goes to ``var/traces/<trace_id>.jsonl`` (one row per burst). The
returned summary run-length encodes, per area, the bursts on which it fired, with
the physics values at the start of each run, so "tilt bin fired at burst N, nudge
voxel at N+2, pitch changed at N+6" can be read from one small payload.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from feagi_mcp.balance_measurement import actuator_targets, physics_sample

MAX_TRACE_S = 20.0
MAX_AREAS = 16
DEFAULT_POLL_HZ = 40.0
MAX_VOXELS_PER_EVENT = 32
TRACE_DIR = Path("var") / "traces"


def fired_voxels(fire_queue: dict[str, Any], area_ids: list[str]) -> dict[str, dict[str, Any]]:
    """``{area_id: {"count": n, "voxels": [[x, y, z], ...]}}`` for areas that fired."""
    areas = fire_queue.get("cortical_areas")
    if not isinstance(areas, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for area_id in area_ids:
        entry = areas.get(area_id)
        if not isinstance(entry, dict):
            continue
        xs = entry.get("coordinates_x") or []
        ys = entry.get("coordinates_y") or []
        zs = entry.get("coordinates_z") or []
        voxels = [[x, y, z] for x, y, z in zip(xs, ys, zs, strict=False)]
        count = entry.get("fired_count")
        if not isinstance(count, int):
            count = len(voxels)
        if count == 0 and not voxels:
            continue
        out[area_id] = {"count": count, "voxels": voxels[:MAX_VOXELS_PER_EVENT]}
    return out


async def collect_aligned_rows(
    fetch_fire_queue: Callable[[], Awaitable[dict[str, Any]]],
    fetch_physics: Callable[[], Awaitable[dict[str, Any]]],
    duration_s: float,
    area_ids: list[str],
    *,
    signals: list[str] | None = None,
    free_joint: str | None = None,
    poll_hz: float = DEFAULT_POLL_HZ,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Poll both endpoints together; one row per distinct burst number."""
    period = 1.0 / poll_hz
    start = clock()
    rows: list[dict[str, Any]] = []
    stats = {"polls": 0, "fire_queue_errors": 0, "physics_errors": 0, "duplicate_bursts": 0}
    last_burst: int | None = None
    while True:
        t0 = clock()
        if t0 - start >= duration_s:
            break
        stats["polls"] += 1
        results: list[Any] = list(
            await asyncio.gather(fetch_fire_queue(), fetch_physics(), return_exceptions=True)
        )
        fq_raw, phys_raw = results
        fq: dict[str, Any] | None = None
        phys: dict[str, Any] | None = None
        if isinstance(fq_raw, dict) and "error" not in fq_raw:
            fq = fq_raw
        else:
            stats["fire_queue_errors"] += 1
        if isinstance(phys_raw, dict) and "error" not in phys_raw:
            phys = phys_raw
        else:
            stats["physics_errors"] += 1
        burst = fq.get("timestep") if fq is not None else None
        if fq is not None and isinstance(burst, int) and not isinstance(burst, bool):
            if burst == last_burst:
                stats["duplicate_bursts"] += 1
            else:
                last_burst = burst
                row: dict[str, Any] = {
                    "burst": burst,
                    "t_wall": round(t0 - start, 4),
                    "fired": fired_voxels(fq, area_ids),
                }
                if phys is not None:
                    reduced = physics_sample(phys, free_joint)
                    if reduced is not None:
                        row["physics"] = {
                            "clock": reduced["clock"],
                            "pitch_deg": round(reduced["pitch_deg"], 3),
                            "roll_deg": round(reduced["roll_deg"], 3),
                            "tilt_deg": round(reduced["tilt_deg"], 3),
                            "z_m": reduced["z_m"],
                        }
                    row["targets"] = actuator_targets(phys, signals)
                rows.append(row)
        await sleep(max(0.0, period - (clock() - t0)))
    return rows, stats


def run_length_events(rows: list[dict[str, Any]], area_ids: list[str]) -> dict[str, Any]:
    """Per area, runs of consecutive sampled bursts on which it fired, with physics at run start."""
    events: dict[str, Any] = {}
    for area_id in area_ids:
        runs: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for index, row in enumerate(rows):
            fired = row["fired"].get(area_id)
            contiguous = current is not None and index > 0 and rows[index - 1]["fired"].get(area_id)
            if fired:
                if contiguous and current is not None:
                    current["to"] = row["burst"]
                    current["bursts"] += 1
                    current["fired_total"] += fired["count"]
                else:
                    if current is not None:
                        runs.append(current)
                    current = {
                        "from": row["burst"],
                        "to": row["burst"],
                        "bursts": 1,
                        "fired_total": fired["count"],
                        "voxels_at_start": fired["voxels"][:8],
                        "physics_at_start": row.get("physics"),
                        "targets_at_start": row.get("targets"),
                    }
            elif current is not None:
                runs.append(current)
                current = None
        if current is not None:
            runs.append(current)
        events[area_id] = {
            "bursts_fired": sum(r["bursts"] for r in runs),
            "runs": runs,
        }
    return events


def write_trace(rows: list[dict[str, Any]], trace_dir: Path, trace_id: str) -> Path:
    """Write one JSON object per burst to ``<trace_dir>/<trace_id>.jsonl``."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{trace_id}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return path


async def record_aligned_trace_window(
    fetch_fire_queue: Callable[[], Awaitable[dict[str, Any]]],
    fetch_physics: Callable[[], Awaitable[dict[str, Any]]],
    duration_s: float,
    area_ids: list[str],
    *,
    signals: list[str] | None = None,
    free_joint: str | None = None,
    trace_dir: Path = TRACE_DIR,
    trace_id: str | None = None,
    poll_hz: float = DEFAULT_POLL_HZ,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Record, write and summarize one aligned trace."""
    if not area_ids:
        return {"error": "areas must list at least one cortical id"}
    if len(area_ids) > MAX_AREAS:
        return {"error": f"at most {MAX_AREAS} areas per trace", "requested": len(area_ids)}
    duration = max(0.0, min(float(duration_s), MAX_TRACE_S))
    rows, stats = await collect_aligned_rows(
        fetch_fire_queue,
        fetch_physics,
        duration,
        area_ids,
        signals=signals,
        free_joint=free_joint,
        poll_hz=poll_hz,
        sleep=sleep,
        clock=clock,
    )
    identifier = trace_id or uuid.uuid4().hex[:12]
    path = write_trace(rows, trace_dir, identifier)
    bursts = [row["burst"] for row in rows]
    missed = (bursts[-1] - bursts[0] + 1 - len(bursts)) if len(bursts) > 1 else 0
    clocks = [row["physics"]["clock"] for row in rows if row.get("physics")]
    return {
        "trace_id": identifier,
        "trace_path": str(path),
        "window_s": duration,
        "capped": float(duration_s) > MAX_TRACE_S,
        "areas": area_ids,
        "signals": signals,
        "bursts_recorded": len(bursts),
        "burst_range": [bursts[0], bursts[-1]] if bursts else None,
        "bursts_missed_by_sampler": max(0, missed),
        "clock_range": [min(clocks), max(clocks)] if clocks else None,
        "resets_in_window": sum(1 for a, b in zip(clocks, clocks[1:], strict=False) if b < a),
        **stats,
        "events": run_length_events(rows, area_ids),
    }
