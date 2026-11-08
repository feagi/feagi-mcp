"""Compile stance-relative motor targets into ``patterns`` voxel rows (local, no HTTP).

A PositionalServo absolute OPU channel decodes the *mean* of the active z voxels of the
channel into one absolute target. This module turns "reference value + gain * source bin"
into the dst z voxel that holds that target, using the caller's joint range for the unit
conversion and the OPU's :class:`~feagi_mcp.percentage_coding.UnitCoding` (the registered
unit bound to ``feagi_rust_py_libs``) for the bin rule. The rule itself is never computed here.
"""

from __future__ import annotations

import json
import math
from typing import Any

from feagi_mcp.percentage_coding import UnitCoding

CHANNEL_KEYS = frozenset(
    {"channel", "reference", "range", "src_fixed", "gain", "max_offset", "deadband"}
)


def range_fraction(value: float, range_min: float, range_max: float) -> float:
    """Fraction of ``[range_min, range_max]`` at which ``value`` sits (clamped to the range).

    This is the unit conversion of a joint range (``physical_range`` semantics: ``range_min``
    at fraction 0, ``range_max`` at fraction 1); the z bin for the fraction comes from the
    binding.
    """
    if not range_max > range_min:
        raise ValueError("range max must be greater than range min")
    return (min(max(value, range_min), range_max) - range_min) / (range_max - range_min)


def value_at_fraction(fraction: float, range_min: float, range_max: float) -> float:
    """Joint-unit value at ``fraction`` of ``[range_min, range_max]``."""
    return range_min + (range_max - range_min) * fraction


def _coactive_z_by_channel(
    coactive_z: int | dict[Any, Any] | str | None,
) -> tuple[int | None, dict[int, int]]:
    """Normalize ``coactive_z`` to ``(default for every channel, per-channel overrides)``."""
    if coactive_z is None:
        return None, {}
    if isinstance(coactive_z, str):
        text = coactive_z.strip()
        try:
            coactive_z = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"coactive_z must be an integer or a JSON object: {e}") from e
    if isinstance(coactive_z, bool) or not isinstance(coactive_z, (int, dict)):
        raise ValueError("coactive_z must be an integer or a mapping of channel -> integer")
    if isinstance(coactive_z, int):
        return coactive_z, {}
    per: dict[int, int] = {}
    for key, val in coactive_z.items():
        if isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(f"coactive_z for channel {key} must be an integer")
        per[int(key)] = val
    return None, per


def compile_stance_offset_rows(
    *,
    src_axis: str,
    src_bins: int,
    src_fixed: list[Any],
    channels: list[dict[str, Any]],
    coding: UnitCoding,
    gain: float,
    deadband: float = 0.0,
    max_offset: float | None = None,
    src_center: float | None = None,
    joint_range: list[float] | None = None,
    n_stance_voxels: int = 0,
    coactive_z: int | dict[Any, Any] | str | None = None,
) -> dict[str, Any]:
    """Compile ``voxel_mappings`` rows for stance-relative offsets.

    ``coding`` is the destination OPU area's registered unit coding (see
    :mod:`feagi_mcp.registration_units`); its depth is the dst z extent and its variant decides
    which bin holds a target. Joint ranges only convert joint units to a 0..1 fraction.

    Source bin ``i`` has signed distance ``d = i - src_center`` (default: middle bin). Bins
    with ``abs(d) <= deadband`` map to nothing. Otherwise the offset is ``gain * d`` joint
    units, clamped to ``+-max_offset``, added to the channel reference and clamped to the
    joint range. ``src_fixed`` is the ``[x, y, z]`` source triple whose ``src_axis`` entry
    is replaced by the bin index. Each channel dict: ``{"channel": int, "reference": float,
    "range": [min, max] (optional), "src_fixed": [x, y, z] (optional), "gain": float
    (optional), "max_offset": float (optional), "deadband": float (optional)}``. A channel's
    ``gain``, ``max_offset`` and ``deadband`` override the top-level values for that channel
    only; any other channel key is rejected with ``ValueError``. When ``abs(gain)`` is
    smaller than one dst z bin in joint units (``(max - min) / (depth - 1)``, depth from
    ``coding``) the offsets quantize (neighbouring source bins share a z bin, small ones
    round to the stance) and a warning is added.

    ``n_stance_voxels`` is how many stance voxels are active on the same channel in the
    same burst; the decoder averages all active z, so the reflex voxel is placed at
    ``(n+1)*z_target - n*z_stance`` to land the mean on the target (clamped to the strip).

    ``coactive_z`` is the z of the one other voxel active on the channel while this source
    fires (e.g. a second source's rest voxel), as one integer for every channel or a mapping
    ``channel -> int`` (a JSON object string is also accepted). For a channel it replaces the
    ``n_stance_voxels * z_ref`` term: the reflex voxel is ``2*z_target - coactive_z`` and the
    decoded mean is ``(coactive_z + z_w) / 2``. Passing it together with ``n_stance_voxels``
    is an error; channels missing from a mapping keep the ``n_stance_voxels`` behaviour.
    """
    depth = coding.depth
    if depth < 2:
        raise ValueError("OPU depth must be >= 2")
    axis = {"x": 0, "y": 1, "z": 2}.get(str(src_axis).lower())
    if axis is None:
        raise ValueError("src_axis must be 'x', 'y' or 'z'")
    if src_bins < 1:
        raise ValueError("src_bins must be >= 1")
    if not channels:
        raise ValueError("channels must be non-empty")
    if n_stance_voxels < 0:
        raise ValueError("n_stance_voxels must be >= 0")
    co_default, co_per_channel = _coactive_z_by_channel(coactive_z)
    if n_stance_voxels and coactive_z is not None:
        raise ValueError(
            "pass either n_stance_voxels or coactive_z, not both (coactive_z replaces "
            "the n_stance_voxels * stance term)"
        )
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
        z_ref = coding.bin_for_fraction(range_fraction(ref, lo, hi))
        stance.append(
            {
                "channel": channel,
                "reference": ref,
                "stance_dst": [channel, 0, z_ref],
                "stance_value": value_at_fraction(coding.decode_fraction([z_ref]), lo, hi),
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
            z_t = coding.bin_for_fraction(range_fraction(tgt, lo, hi))
            z_w = z_t
            co_z = co_per_channel.get(channel, co_default)
            if co_z is not None:
                z_w = 2 * z_t - co_z
                if z_w < 0 or z_w > depth - 1:
                    warnings.append(
                        f"channel {channel} src {i}: mean-compensated z={z_w} (against coactive "
                        f"voxel z={co_z}) outside 0..{depth - 1}; clamped (offset is smaller "
                        "than requested)"
                    )
                    z_w = min(max(z_w, 0), depth - 1)
                active = [co_z, z_w]
            else:
                if n_stance_voxels:
                    z_w = (n_stance_voxels + 1) * z_t - n_stance_voxels * z_ref
                    if z_w < 0 or z_w > depth - 1:
                        warnings.append(
                            f"channel {channel} src {i}: mean-compensated z={z_w} outside "
                            f"0..{depth - 1}; clamped (offset is smaller than requested)"
                        )
                        z_w = min(max(z_w, 0), depth - 1)
                active = [z_ref] * n_stance_voxels + [z_w]
            achieved = value_at_fraction(coding.decode_fraction(active), lo, hi)
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
