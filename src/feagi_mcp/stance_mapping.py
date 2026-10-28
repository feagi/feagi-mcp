"""Compile stance-relative motor targets into ``patterns`` voxel rows (local, no HTTP).

A PositionalServo absolute OPU channel decodes the *mean* of the active z voxels of the
channel into one absolute target (z=0 is the range maximum, z=depth-1 the minimum).
This module turns "reference value + gain * source bin" into the dst z voxel that holds
that target, using the caller's joint range and the OPU depth and direction.
"""

from __future__ import annotations

import math
from typing import Any

CHANNEL_KEYS = frozenset(
    {"channel", "reference", "range", "src_fixed", "gain", "max_offset", "deadband"}
)


def value_to_z_bin(
    value: float, range_min: float, range_max: float, depth: int, z0_is_max: bool = True
) -> int:
    """Convert a joint-unit value to the OPU z bin that decodes to it (clamped to the range)."""
    if depth < 2:
        raise ValueError("OPU depth must be >= 2")
    if not range_max > range_min:
        raise ValueError("range max must be greater than range min")
    pos01 = (min(max(value, range_min), range_max) - range_min) / (range_max - range_min)
    frac = 1.0 - pos01 if z0_is_max else pos01
    return int(round(frac * (depth - 1)))


def z_bin_to_value(
    z: int, range_min: float, range_max: float, depth: int, z0_is_max: bool = True
) -> float:
    """Inverse of :func:`value_to_z_bin` (the target the decoder yields for one active z)."""
    frac = z / (depth - 1)
    pos01 = 1.0 - frac if z0_is_max else frac
    return range_min + (range_max - range_min) * pos01


def compile_stance_offset_rows(
    *,
    src_axis: str,
    src_bins: int,
    src_fixed: list[Any],
    channels: list[dict[str, Any]],
    depth: int,
    gain: float,
    deadband: float = 0.0,
    max_offset: float | None = None,
    src_center: float | None = None,
    joint_range: list[float] | None = None,
    z0_is_max: bool = True,
    n_stance_voxels: int = 0,
) -> dict[str, Any]:
    """Compile ``voxel_mappings`` rows for stance-relative offsets.

    Source bin ``i`` has signed distance ``d = i - src_center`` (default: middle bin). Bins
    with ``abs(d) <= deadband`` map to nothing. Otherwise the offset is ``gain * d`` joint
    units, clamped to ``+-max_offset``, added to the channel reference and clamped to the
    joint range. ``src_fixed`` is the ``[x, y, z]`` source triple whose ``src_axis`` entry
    is replaced by the bin index. Each channel dict: ``{"channel": int, "reference": float,
    "range": [min, max] (optional), "src_fixed": [x, y, z] (optional), "gain": float
    (optional), "max_offset": float (optional), "deadband": float (optional)}``. A channel's
    ``gain``, ``max_offset`` and ``deadband`` override the top-level values for that channel
    only; any other channel key is rejected with ``ValueError``. When ``abs(gain)`` is
    smaller than one dst z bin in joint units (``(max - min) / (depth - 1)``) the offsets
    quantize (neighbouring source bins share a z bin, small ones round to the stance) and a
    warning is added.

    ``n_stance_voxels`` is how many stance voxels are active on the same channel in the
    same burst; the decoder averages all active z, so the reflex voxel is placed at
    ``(n+1)*z_target - n*z_stance`` to land the mean on the target (clamped to the strip).
    """
    axis = {"x": 0, "y": 1, "z": 2}.get(str(src_axis).lower())
    if axis is None:
        raise ValueError("src_axis must be 'x', 'y' or 'z'")
    if src_bins < 1:
        raise ValueError("src_bins must be >= 1")
    if not channels:
        raise ValueError("channels must be non-empty")
    if n_stance_voxels < 0:
        raise ValueError("n_stance_voxels must be >= 0")
    if not all(math.isfinite(float(r)) for r in (gain, deadband)):
        raise ValueError("gain and deadband must be finite")
    center = (src_bins - 1) / 2.0 if src_center is None else float(src_center)
    rows: list[dict[str, Any]] = []
    table: list[dict[str, Any]] = []
    stance: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines: list[str] = []
    for ch in channels:
        unknown = sorted(set(ch) - CHANNEL_KEYS)
        if unknown:
            raise ValueError(
                f"channel {ch.get('channel')}: unknown channel key(s) {unknown}; "
                f"allowed: {sorted(CHANNEL_KEYS)}"
            )
        channel = int(ch["channel"])
        ch_gain = float(ch["gain"]) if ch.get("gain") is not None else gain
        ch_deadband = float(ch["deadband"]) if ch.get("deadband") is not None else deadband
        ch_max = ch["max_offset"] if ch.get("max_offset") is not None else max_offset
        if not all(math.isfinite(r) for r in (ch_gain, ch_deadband)):
            raise ValueError(f"channel {channel}: gain and deadband must be finite")
        rng = ch.get("range") or joint_range
        if not rng or len(rng) != 2:
            raise ValueError(f"channel {channel}: joint range [min, max] is required")
        lo, hi = float(rng[0]), float(rng[1])
        ref = float(ch["reference"])
        z_step = (hi - lo) / (depth - 1)
        if ch_gain != 0 and abs(ch_gain) < z_step:
            warnings.append(
                f"channel {channel}: offset per bin {abs(ch_gain):.4g} is smaller than one dst z "
                f"bin ({z_step:.4g}); offsets quantize (some neighbouring bins share a z)"
            )
        z_ref = value_to_z_bin(ref, lo, hi, depth, z0_is_max)
        stance.append(
            {
                "channel": channel,
                "reference": ref,
                "stance_dst": [channel, 0, z_ref],
                "stance_value": z_bin_to_value(z_ref, lo, hi, depth, z0_is_max),
            }
        )
        fixed = list(ch.get("src_fixed") or src_fixed)
        if len(fixed) != 3:
            raise ValueError(f"channel {channel}: src_fixed must have 3 entries")
        lines.append(f"channel {channel} (range {lo}..{hi}, reference {ref}, stance z={z_ref})")
        for i in range(src_bins):
            d = i - center
            if abs(d) <= ch_deadband:
                table.append({"channel": channel, "src_bin": i, "dst_z": None})
                lines.append(f"  src {i:>3} -> none (deadband)")
                continue
            off = ch_gain * d
            if ch_max is not None:
                off = max(-abs(float(ch_max)), min(abs(float(ch_max)), off))
            tgt = min(max(ref + off, lo), hi)
            z_t = value_to_z_bin(tgt, lo, hi, depth, z0_is_max)
            z_w = z_t
            if n_stance_voxels:
                z_w = (n_stance_voxels + 1) * z_t - n_stance_voxels * z_ref
                if z_w < 0 or z_w > depth - 1:
                    warnings.append(
                        f"channel {channel} src {i}: mean-compensated z={z_w} outside "
                        f"0..{depth - 1}; clamped (offset is smaller than requested)"
                    )
                    z_w = min(max(z_w, 0), depth - 1)
            mean_z = (n_stance_voxels * z_ref + z_w) / (n_stance_voxels + 1)
            achieved = z_bin_to_value(mean_z, lo, hi, depth, z0_is_max)
            src = list(fixed)
            src[axis] = i
            rows.append({"src": src, "dst": [channel, 0, int(z_w)]})
            table.append(
                {
                    "channel": channel,
                    "src_bin": i,
                    "offset": round(off, 6),
                    "target_value": round(achieved, 6),
                    "dst_z": int(z_w),
                }
            )
            lines.append(f"  src {i:>3} -> {achieved:.4g} (offset {off:+.4g}, dst z={int(z_w)})")
    return {
        "voxel_mappings": rows,
        "table": table,
        "table_text": "\n".join(lines),
        "stance": stance,
        "warnings": warnings,
    }
