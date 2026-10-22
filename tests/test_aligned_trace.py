"""Tests for record_aligned_trace: bursts paired with physics, written and run-length encoded."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from feagi_mcp.aligned_trace import (
    MAX_AREAS,
    MAX_TRACE_S,
    collect_aligned_rows,
    fired_voxels,
    record_aligned_trace_window,
    run_length_events,
)

TILT = "Y1RpbHRfXwE="
NUDGE = "Y051ZGdlX18="


def _quat_pitch(deg: float) -> list[float]:
    half = math.radians(deg) / 2.0
    return [math.cos(half), 0.0, math.sin(half), 0.0]


def _fire_queue(burst: int, fired: dict[str, list[list[int]]]) -> dict[str, Any]:
    areas = {}
    for area_id, voxels in fired.items():
        areas[area_id] = {
            "coordinates_x": [v[0] for v in voxels],
            "coordinates_y": [v[1] for v in voxels],
            "coordinates_z": [v[2] for v in voxels],
            "fired_count": len(voxels),
            "neuron_ids": list(range(len(voxels))),
        }
    return {
        "total_fired": sum(len(v) for v in fired.values()),
        "timestep": burst,
        "cortical_areas": areas,
    }


def _state(clock: float, pitch_deg: float) -> dict[str, Any]:
    return {
        "time": clock,
        "free_joints": {
            "trunk_base_freejoint": {
                "position_m": [0.0, 0.0, 0.11],
                "quaternion_wxyz": _quat_pitch(pitch_deg),
            }
        },
        "actuators": {
            "left_hip_pitch": {"ctrl": -0.5},
            "right_hip_pitch": {"ctrl": 0.5},
        },
    }


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


class Scripted:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.calls = 0

    async def fetch(self) -> Any:
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def test_fired_voxels_filters_to_requested_areas() -> None:
    fq = _fire_queue(5, {TILT: [[0, 0, 3]], "other": [[1, 1, 1]]})
    fired = fired_voxels(fq, [TILT, NUDGE])
    assert fired == {TILT: {"count": 1, "voxels": [[0, 0, 3]]}}


async def test_collect_rows_dedupes_bursts_and_pairs_physics() -> None:
    clock = FakeClock()
    queues = [
        _fire_queue(100, {TILT: [[0, 0, 3]]}),
        _fire_queue(100, {TILT: [[0, 0, 3]]}),  # sampler has not advanced
        _fire_queue(102, {TILT: [[0, 0, 3]], NUDGE: [[2, 0, 0]]}),
        {"error": "HTTP 503"},
        _fire_queue(103, {}),
    ]
    states = [
        _state(1.0, 2.0),
        _state(1.02, 2.0),
        _state(1.05, 2.5),
        _state(1.07, 3.0),
        RuntimeError("x"),
    ]
    fq, phys = Scripted(queues), Scripted(states)
    rows, stats = await collect_aligned_rows(
        fq.fetch,
        phys.fetch,
        0.125,
        [TILT, NUDGE],
        signals=["left_hip_pitch"],
        poll_hz=40.0,
        sleep=clock.sleep,
        clock=clock,
    )
    assert stats["polls"] == 5
    assert stats["duplicate_bursts"] == 1
    assert stats["fire_queue_errors"] == 1
    assert stats["physics_errors"] == 1
    assert [r["burst"] for r in rows] == [100, 102, 103]
    assert rows[1]["fired"][NUDGE]["voxels"] == [[2, 0, 0]]
    assert rows[1]["physics"]["clock"] == 1.05
    assert rows[1]["targets"] == {"left_hip_pitch": -0.5}
    assert "physics" not in rows[2]  # physics fetch failed on that poll


def test_run_length_events_groups_consecutive_sampled_bursts() -> None:
    rows = [
        {
            "burst": 1,
            "fired": {TILT: {"count": 1, "voxels": [[0, 0, 3]]}},
            "physics": {"clock": 1.0},
        },
        {
            "burst": 2,
            "fired": {TILT: {"count": 1, "voxels": [[0, 0, 3]]}},
            "physics": {"clock": 1.02},
        },
        {"burst": 3, "fired": {NUDGE: {"count": 2, "voxels": [[2, 0, 0], [3, 0, 0]]}}},
        {"burst": 5, "fired": {TILT: {"count": 1, "voxels": [[0, 0, 4]]}}},
    ]
    events = run_length_events(rows, [TILT, NUDGE])
    assert events[TILT]["bursts_fired"] == 3
    assert [(r["from"], r["to"], r["bursts"]) for r in events[TILT]["runs"]] == [
        (1, 2, 2),
        (5, 5, 1),
    ]
    assert events[TILT]["runs"][0]["physics_at_start"] == {"clock": 1.0}
    assert events[NUDGE]["runs"] == [
        {
            "from": 3,
            "to": 3,
            "bursts": 1,
            "fired_total": 2,
            "voxels_at_start": [[2, 0, 0], [3, 0, 0]],
            "physics_at_start": None,
            "targets_at_start": None,
        }
    ]


async def test_record_window_writes_jsonl_and_reports_missed_bursts(tmp_path: Path) -> None:
    clock = FakeClock()
    queues = [_fire_queue(b, {TILT: [[0, 0, 3]]} if b % 2 else {}) for b in (10, 11, 13, 14)]
    states = [_state(0.5 + 0.025 * i, 1.0) for i in range(4)]
    result = await record_aligned_trace_window(
        Scripted(queues).fetch,
        Scripted(states).fetch,
        0.1,
        [TILT],
        trace_dir=tmp_path,
        trace_id="t1",
        poll_hz=40.0,
        sleep=clock.sleep,
        clock=clock,
    )
    assert result["trace_id"] == "t1"
    assert result["bursts_recorded"] == 4
    assert result["burst_range"] == [10, 14]
    assert result["bursts_missed_by_sampler"] == 1
    assert result["resets_in_window"] == 0
    assert result["events"][TILT]["bursts_fired"] == 2
    lines = (tmp_path / "t1.jsonl").read_text().splitlines()
    assert len(lines) == 4
    assert json.loads(lines[0])["burst"] == 10
    assert "left_hip_pitch" in json.loads(lines[0])["targets"]


async def test_record_window_rejects_bad_area_lists(tmp_path: Path) -> None:
    async def never() -> dict[str, Any]:
        raise AssertionError("should not fetch")

    assert "error" in await record_aligned_trace_window(never, never, 1.0, [], trace_dir=tmp_path)
    too_many = [f"a{i}" for i in range(MAX_AREAS + 1)]
    assert "error" in await record_aligned_trace_window(
        never, never, 1.0, too_many, trace_dir=tmp_path
    )


async def test_record_window_caps_duration(tmp_path: Path) -> None:
    clock = FakeClock()
    result = await record_aligned_trace_window(
        Scripted([_fire_queue(1, {})]).fetch,
        Scripted([_state(1.0, 0.0)]).fetch,
        500.0,
        [TILT],
        trace_dir=tmp_path,
        sleep=clock.sleep,
        clock=clock,
    )
    assert result["capped"] is True
    assert result["window_s"] == MAX_TRACE_S
