"""Tests for measure_balance: episode, tilt, recovery and fall statistics from a fake controller."""

from __future__ import annotations

import math
from typing import Any

import pytest

from feagi_mcp.balance_measurement import (
    MAX_WINDOW_S,
    analyze_window,
    collect_samples,
    measure_balance_window,
    physics_sample,
    quaternion_to_tilt,
    split_episodes,
)


def _quat_pitch(deg: float) -> list[float]:
    half = math.radians(deg) / 2.0
    return [math.cos(half), 0.0, math.sin(half), 0.0]


def _quat_roll(deg: float) -> list[float]:
    half = math.radians(deg) / 2.0
    return [math.cos(half), math.sin(half), 0.0, 0.0]


def _state(clock: float, quat: list[float], z: float = 0.11) -> dict[str, Any]:
    return {
        "time": clock,
        "free_joints": {
            "trunk_base_freejoint": {"position_m": [0.0, 0.0, z], "quaternion_wxyz": quat}
        },
        "actuators": {"left_hip_pitch": {"ctrl": -0.5}},
    }


class FakeClock:
    """Monotonic clock that only advances through sleep()."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds


class ScriptedController:
    """Serves one scripted state per fetch; the simulator clock is scripted too."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        self.states = states
        self.calls = 0

    async def fetch(self) -> dict[str, Any]:
        state = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        if isinstance(state, Exception):
            raise state
        return state


def test_quaternion_tilt_matches_pitch_and_roll() -> None:
    pitch = quaternion_to_tilt(_quat_pitch(30.0))
    assert pitch["pitch_deg"] == pytest.approx(30.0, abs=1e-6)
    assert pitch["roll_deg"] == pytest.approx(0.0, abs=1e-6)
    assert pitch["tilt_deg"] == pytest.approx(30.0, abs=1e-6)
    roll = quaternion_to_tilt(_quat_roll(-20.0))
    assert roll["roll_deg"] == pytest.approx(-20.0, abs=1e-6)
    assert roll["tilt_deg"] == pytest.approx(20.0, abs=1e-6)
    assert quaternion_to_tilt([1, 0, 0, 0])["tilt_deg"] == pytest.approx(0.0)


def test_physics_sample_picks_trunk_joint_and_height() -> None:
    sample = physics_sample(_state(1.5, _quat_pitch(5.0), z=0.12))
    assert sample is not None
    assert sample["clock"] == 1.5
    assert sample["free_joint"] == "trunk_base_freejoint"
    assert sample["z_m"] == 0.12
    assert physics_sample({"time": 1.0}) is None
    assert physics_sample({"time": 1.0, "free_joints": {}}) is None


def test_split_episodes_on_clock_drop() -> None:
    samples = [{"clock": c, "tilt_deg": 0.0} for c in (0.5, 1.0, 1.5, 0.05, 0.55, 1.05, 0.02)]
    episodes = split_episodes(samples)
    assert [len(e) for e in episodes] == [3, 3, 1]


def test_analyze_window_counts_episodes_recoveries_falls_and_latency() -> None:
    # Episode 1: upright, wobble above 11 and back (recovery), fall past 50 at 2.0, reset at 2.5.
    ep1 = [(0.5, 2.0), (1.0, 15.0), (1.5, 5.0), (2.0, 55.0), (2.5, 70.0)]
    # Episode 2: ongoing, upright the whole time.
    ep2 = [(0.1, 1.0), (0.6, 3.0), (1.1, 4.0)]
    samples = [
        {"clock": c, "tilt_deg": t, "pitch_deg": t, "roll_deg": 0.0, "z_m": 0.1}
        for c, t in ep1 + ep2
    ]
    stats = analyze_window(samples, upright_deg=11.0, fall_deg=50.0)
    assert stats["episodes"] == 2
    assert stats["reset_count"] == 1
    assert stats["episode_length_s"]["ended"] == [2.5]
    assert stats["episode_length_s"]["mean"] == 2.5
    assert stats["episode_length_s"]["ongoing"] == 1.1
    assert stats["upright_fraction"] == pytest.approx(5 / 8)
    assert stats["recoveries"] == 1
    assert stats["falls"] == 1
    assert stats["fall_confirmation_latency_s"]["values"] == [0.5]
    assert stats["fall_confirmation_latency_s"]["falls_in_ongoing_episode"] == 0
    assert stats["tilt_deg"]["histogram"] == {"0-10": 5, "10-20": 1, "50-60": 1, "70-80": 1}
    assert stats["tilt_deg"]["max"] == 70.0


def test_analyze_window_empty() -> None:
    assert analyze_window([])["sample_count"] == 0


async def test_collect_samples_runs_at_rate_and_counts_errors() -> None:
    clock = FakeClock()
    states: list[Any] = [_state(0.1 * i, _quat_pitch(0.0)) for i in range(10)]
    states[3] = {"error": "HTTP 500"}
    states[4] = RuntimeError("boom")
    controller = ScriptedController(states)
    samples, errors = await collect_samples(
        controller.fetch, 0.49, rate_hz=20.0, sleep=clock.sleep, clock=clock
    )
    assert controller.calls == 10
    assert errors == 2
    assert len(samples) == 8
    assert samples[1][0] == pytest.approx(0.05)


async def test_measure_balance_window_end_to_end_with_reset() -> None:
    clock = FakeClock()
    states = [_state(0.05 * i, _quat_pitch(2.0)) for i in range(1, 11)]
    states += [_state(0.05 * i, _quat_pitch(60.0)) for i in range(11, 15)]
    states += [_state(0.05 * i, _quat_pitch(1.0)) for i in range(1, 7)]
    controller = ScriptedController(states)
    result = await measure_balance_window(
        controller.fetch,
        1.0,
        upright_deg=11.0,
        fall_deg=50.0,
        sleep=clock.sleep,
        clock=clock,
        window_id="w1",
    )
    assert result["window_id"] == "w1"
    assert result["sample_count"] == 20
    assert result["reset_count"] == 1
    assert result["falls"] == 1
    assert result["episode_length_s"]["ended"] == [0.7]
    assert result["fall_confirmation_latency_s"]["values"] == [pytest.approx(0.15)]
    assert result["actual_rate_hz"] == 20.0
    assert result["free_joint"] == "trunk_base_freejoint"
    assert "error" not in result


async def test_measure_balance_window_caps_duration_and_reports_missing_trunk() -> None:
    clock = FakeClock()
    controller = ScriptedController([{"time": 1.0, "joints": {}}])
    result = await measure_balance_window(controller.fetch, 100.0, sleep=clock.sleep, clock=clock)
    assert result["capped"] is True
    assert result["window_s"] == MAX_WINDOW_S
    assert result["error"] == "no_trunk_quaternion"
    assert result["unusable_samples"] > 0
