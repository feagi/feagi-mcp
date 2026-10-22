"""Balance outcome metrics from a controller's physics introspection endpoint.

The MuJoCo controller serves ``GET /v1/state`` with the simulator clock (``time``),
scalar joints, free joints (the trunk root carries ``position_m`` and
``quaternion_wxyz``) and actuator ``ctrl`` values. Sampling it at a fixed rate gives
the outcome metrics a balance task needs without any brain-side instrumentation:

* **episodes**: a drop of the simulator clock is a scene reset; the clock value just
  before the drop is that episode's length (the clock restarts at 0 on reset).
* **tilt**: angle between the trunk's up axis and world up, from the quaternion.
* **upright / recovery / fall**: thresholds in degrees on that tilt.

Everything here is numbers; interpretation is the caller's job. The sampling loop
takes its fetch, sleep and clock functions as arguments so tests can drive it with
a scripted controller and a fake clock.
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

MAX_WINDOW_S = 25.0
DEFAULT_RATE_HZ = 20.0
TILT_BIN_DEG = 10
# A clock that goes back by more than this is a reset; smaller jitter is ignored.
RESET_EPSILON_S = 1e-6


def quaternion_to_tilt(q: list[float] | tuple[float, ...]) -> dict[str, float]:
    """Pitch, roll (aerospace ZYX convention) and total tilt in degrees from ``[w, x, y, z]``."""
    w, x, y, z = (float(v) for v in q[:4])
    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.degrees(math.asin(sinp))
    roll = math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
    # World-z component of the body's up axis: R[2][2] of the rotation matrix.
    up_z = 1.0 - 2.0 * (x * x + y * y)
    up_z = max(-1.0, min(1.0, up_z))
    tilt = math.degrees(math.acos(up_z))
    return {"pitch_deg": pitch, "roll_deg": roll, "tilt_deg": tilt}


def pick_free_joint(state: dict[str, Any], free_joint: str | None = None) -> str | None:
    """Name of the trunk free joint: the requested one, else one named like a trunk/root/base."""
    joints = state.get("free_joints")
    if not isinstance(joints, dict) or not joints:
        return None
    if free_joint:
        return free_joint if free_joint in joints else None
    names = [str(name) for name in joints]
    for name in names:
        lowered = name.lower()
        if any(tag in lowered for tag in ("trunk", "root", "base", "torso", "body")):
            return name
    return names[0]


def physics_sample(state: dict[str, Any], free_joint: str | None = None) -> dict[str, Any] | None:
    """Reduce one ``/v1/state`` payload to clock, pitch, roll, tilt and trunk height."""
    clock = state.get("time")
    if not isinstance(clock, (int, float)) or isinstance(clock, bool):
        return None
    joint_name = pick_free_joint(state, free_joint)
    if joint_name is None:
        return None
    joint = state["free_joints"][joint_name]
    quat = joint.get("quaternion_wxyz") if isinstance(joint, dict) else None
    pos = joint.get("position_m") if isinstance(joint, dict) else None
    if not isinstance(quat, list) or len(quat) < 4:
        return None
    sample = {"clock": float(clock), "free_joint": joint_name, **quaternion_to_tilt(quat)}
    sample["z_m"] = float(pos[2]) if isinstance(pos, list) and len(pos) >= 3 else None
    return sample


def actuator_targets(state: dict[str, Any], names: list[str] | None) -> dict[str, float]:
    """``ctrl`` value of each requested actuator (all actuators when ``names`` is None)."""
    actuators = state.get("actuators")
    if not isinstance(actuators, dict):
        return {}
    wanted = names if names is not None else list(actuators)
    out: dict[str, float] = {}
    for name in wanted:
        entry = actuators.get(name)
        ctrl = entry.get("ctrl") if isinstance(entry, dict) else None
        if isinstance(ctrl, (int, float)) and not isinstance(ctrl, bool):
            out[name] = float(ctrl)
    return out


async def collect_samples(
    fetch: Callable[[], Awaitable[dict[str, Any]]],
    duration_s: float,
    *,
    rate_hz: float = DEFAULT_RATE_HZ,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[tuple[float, dict[str, Any]]], int]:
    """Poll ``fetch`` at ``rate_hz`` for ``duration_s``.

    Returns ``[(t_wall, payload)]`` and the number of failed fetches.
    """
    period = 1.0 / rate_hz
    start = clock()
    samples: list[tuple[float, dict[str, Any]]] = []
    errors = 0
    while True:
        t0 = clock()
        if t0 - start >= duration_s:
            break
        try:
            payload = await fetch()
        except Exception:  # noqa: BLE001 - a dropped sample is counted, not fatal
            payload = None
            errors += 1
        if isinstance(payload, dict) and "error" not in payload:
            samples.append((t0 - start, payload))
        elif payload is not None:
            errors += 1
        await sleep(max(0.0, period - (clock() - t0)))
    return samples, errors


def split_episodes(samples: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split samples at every drop of the simulator clock."""
    episodes: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous: float | None = None
    for sample in samples:
        clock = sample["clock"]
        if previous is not None and clock < previous - RESET_EPSILON_S and current:
            episodes.append(current)
            current = []
        current.append(sample)
        previous = clock
    if current:
        episodes.append(current)
    return episodes


def _episode_metrics(
    episode: list[dict[str, Any]], upright_deg: float, fall_deg: float
) -> dict[str, Any]:
    """Length, recoveries, fall crossings and first fall clock for one episode."""
    recoveries = 0
    falls = 0
    above_upright = False
    fallen = False
    first_fall_clock: float | None = None
    for sample in episode:
        tilt = sample["tilt_deg"]
        if tilt > upright_deg:
            above_upright = True
        elif above_upright:
            above_upright = False
            recoveries += 1
        if tilt > fall_deg:
            if not fallen:
                falls += 1
            fallen = True
            if first_fall_clock is None:
                first_fall_clock = sample["clock"]
        else:
            fallen = False
    return {
        "length_s": episode[-1]["clock"],
        "samples": len(episode),
        "recoveries": recoveries,
        "falls": falls,
        "first_fall_clock": first_fall_clock,
    }


def analyze_window(
    samples: list[dict[str, Any]],
    *,
    upright_deg: float = 11.0,
    fall_deg: float = 50.0,
) -> dict[str, Any]:
    """Episode, upright, tilt-histogram, recovery and fall statistics for one window."""
    if not samples:
        return {"sample_count": 0, "episodes": 0, "reset_count": 0}
    episodes = split_episodes(samples)
    per_episode = [_episode_metrics(ep, upright_deg, fall_deg) for ep in episodes]
    ended = per_episode[:-1]
    ended_lengths = [ep["length_s"] for ep in ended]
    upright = sum(1 for s in samples if s["tilt_deg"] <= upright_deg)
    tilts = [s["tilt_deg"] for s in samples]
    histogram: dict[str, int] = {}
    for tilt in tilts:
        lo = int(tilt // TILT_BIN_DEG) * TILT_BIN_DEG
        key = f"{lo}-{lo + TILT_BIN_DEG}"
        histogram[key] = histogram.get(key, 0) + 1
    histogram = dict(sorted(histogram.items(), key=lambda kv: int(kv[0].split("-")[0])))
    latencies = [
        ep["length_s"] - ep["first_fall_clock"]
        for ep in ended
        if ep["first_fall_clock"] is not None
    ]
    return {
        "sample_count": len(samples),
        "clock_start": samples[0]["clock"],
        "clock_end": samples[-1]["clock"],
        "episodes": len(episodes),
        "reset_count": len(ended),
        "episode_length_s": {
            "ended": [round(v, 3) for v in ended_lengths],
            "mean": round(statistics.fmean(ended_lengths), 3) if ended_lengths else None,
            "median": round(statistics.median(ended_lengths), 3) if ended_lengths else None,
            "max": round(max(ended_lengths), 3) if ended_lengths else None,
            "ongoing": round(per_episode[-1]["length_s"], 3),
        },
        "upright_fraction": round(upright / len(samples), 4),
        "tilt_deg": {
            "mean": round(statistics.fmean(tilts), 2),
            "max": round(max(tilts), 2),
            "histogram": histogram,
        },
        "recoveries": sum(ep["recoveries"] for ep in per_episode),
        "falls": sum(ep["falls"] for ep in per_episode),
        "fall_confirmation_latency_s": {
            "values": [round(v, 3) for v in latencies],
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "falls_in_ongoing_episode": per_episode[-1]["falls"],
        },
    }


async def measure_balance_window(
    fetch: Callable[[], Awaitable[dict[str, Any]]],
    duration_s: float,
    *,
    upright_deg: float = 11.0,
    fall_deg: float = 50.0,
    free_joint: str | None = None,
    rate_hz: float = DEFAULT_RATE_HZ,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    window_id: str | None = None,
) -> dict[str, Any]:
    """Sample the controller for one window and return balance statistics."""
    duration = max(0.0, min(float(duration_s), MAX_WINDOW_S))
    raw, errors = await collect_samples(fetch, duration, rate_hz=rate_hz, sleep=sleep, clock=clock)
    samples: list[dict[str, Any]] = []
    unusable = 0
    for t_wall, payload in raw:
        reduced = physics_sample(payload, free_joint)
        if reduced is None:
            unusable += 1
            continue
        reduced["t_wall"] = round(t_wall, 4)
        samples.append(reduced)
    result = {
        "window_id": window_id or uuid.uuid4().hex[:12],
        "requested_duration_s": float(duration_s),
        "window_s": duration,
        "capped": float(duration_s) > MAX_WINDOW_S,
        "sample_rate_hz": rate_hz,
        "actual_rate_hz": round(len(samples) / duration, 2) if duration > 0 else None,
        "fetch_errors": errors,
        "unusable_samples": unusable,
        "thresholds": {"upright_deg": upright_deg, "fall_deg": fall_deg},
        "free_joint": samples[0]["free_joint"] if samples else None,
        **analyze_window(samples, upright_deg=upright_deg, fall_deg=fall_deg),
    }
    if not samples and raw:
        result["error"] = "no_trunk_quaternion"
        result["message"] = (
            "The controller state has no free joint with quaternion_wxyz; "
            "pass free_joint=<name> from embodiment_get_physics_state()."
        )
    elif not raw:
        result["error"] = "no_samples"
    return result
