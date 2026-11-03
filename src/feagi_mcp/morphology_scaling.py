"""Pure planning for ``scale_morphology_rows``: scale one destination axis of a pattern morphology.

Rows are ``[[sx, sy, sz], [dx, dy, dz]]`` with exact integers. One source coordinate varies
(the source bin axis); rows group by destination ``(dx, dy)``; within a group the destination
``z`` is scaled about a base: ``z' = half_up(base + gain * (z - base))``. Exact rational
arithmetic keeps ``.5`` ties deterministic (half-up, not banker's rounding).
"""

from __future__ import annotations

from fractions import Fraction
from math import floor
from typing import Any


class ScaleRowsError(ValueError):
    """The request or the stored rows cannot be scaled; the message says why."""


def half_up(value: Fraction) -> int:
    """Round to the nearest integer, ties toward +infinity (``2.5 -> 3``, ``-2.5 -> -2``)."""
    return floor(value + Fraction(1, 2))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_rows(patterns: Any) -> list[tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """Validate rows: exact integer source and destination coordinates, no wildcards."""
    if not isinstance(patterns, list) or not patterns:
        raise ScaleRowsError("morphology has no pattern rows")
    parsed: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for i, row in enumerate(patterns):
        ok = (
            isinstance(row, list)
            and len(row) == 2
            and all(isinstance(side, list) and len(side) == 3 for side in row)
        )
        if not ok:
            raise ScaleRowsError(f"row {i} is not [[sx,sy,sz],[dx,dy,dz]]")
        if not all(_is_int(c) for side in row for c in side):
            raise ScaleRowsError(
                f"row {i} has a wildcard or non-integer coordinate (only exact integers scale)"
            )
        parsed.append((tuple(row[0]), tuple(row[1])))
    return parsed


def detect_src_axis(
    rows: list[tuple[tuple[int, int, int], tuple[int, int, int]]], src_axis: int | None
) -> int:
    varying = [a for a in range(3) if len({r[0][a] for r in rows}) > 1]
    if src_axis is not None:
        if src_axis not in (0, 1, 2):
            raise ScaleRowsError("src_axis must be 0, 1 or 2")
        extra = [a for a in varying if a != src_axis]
        if extra:
            raise ScaleRowsError(f"source axes {extra} also vary besides src_axis={src_axis}")
        return src_axis
    if len(varying) > 1:
        raise ScaleRowsError(
            f"more than one source coordinate varies (axes {varying}); pass src_axis "
            "only if the others are constant"
        )
    if not varying:
        raise ScaleRowsError("no source coordinate varies; pass src_axis")
    return varying[0]


def _scaled(base: int, z: int, gain: Fraction) -> int:
    return half_up(Fraction(base) + gain * (z - base))


def _max_no_clamp_gain(pairs: list[tuple[int, int]], depth: int) -> float | None:
    """Largest gain (3 decimals) keeping every ``(base, z)`` inside the strip after rounding."""
    bound: Fraction | None = None
    for base, z in pairs:
        d = z - base
        if d == 0:
            continue
        # half-up result <= depth-1 iff value < depth-0.5 ; result >= 0 iff value >= -0.5
        limit = (
            (Fraction(2 * (depth - 1) + 1, 2) - base) / d
            if d > 0
            else (Fraction(2 * base + 1, 2) / -d)
        )
        bound = limit if bound is None or limit < bound else bound
    if bound is None:
        return None
    gain = Fraction(floor(bound * 1000), 1000)
    while gain > 0 and any(not 0 <= _scaled(b, z, gain) <= depth - 1 for b, z in pairs):
        gain -= Fraction(1, 1000)
    return float(gain)


def plan_scaled_rows(
    patterns: Any,
    *,
    gain: float,
    depth: int,
    used_src_bins: list[int],
    base_z: int | None = None,
    src_axis: int | None = None,
) -> dict[str, Any]:
    """Return ``{"table", "rows", "largest_no_clamp_gain", "src_axis"}`` or raise ScaleRowsError."""
    if not isinstance(gain, (int, float)) or isinstance(gain, bool) or not gain > 0:
        raise ScaleRowsError("gain must be a positive number")
    if not _is_int(depth) or depth < 1:
        raise ScaleRowsError("destination depth must be a positive integer")
    if base_z is not None and not _is_int(base_z):
        raise ScaleRowsError("base_z must be an integer")
    if not used_src_bins or not all(_is_int(b) for b in used_src_bins):
        raise ScaleRowsError("used_src_bins must be a non-empty list of integers")
    rows = parse_rows(patterns)
    axis = detect_src_axis(rows, src_axis)
    g = Fraction(str(gain))
    used = set(used_src_bins)

    groups: dict[tuple[int, int], dict[int, int]] = {}
    for src, dst in rows:
        bins = groups.setdefault((dst[0], dst[1]), {})
        if src[axis] in bins:
            raise ScaleRowsError(f"destination {dst[:2]} lists source bin {src[axis]} twice")
        bins[src[axis]] = dst[2]
    present = {src[axis] for src, _ in rows}
    missing = sorted(used - present)
    if missing:
        raise ScaleRowsError(f"used_src_bins {missing} are not source bins of this morphology")

    base_of: dict[tuple[int, int], int] = {}
    for key, bins in groups.items():
        if base_z is not None:
            base_of[key] = base_z
        elif 0 in bins:
            base_of[key] = bins[0]
        else:
            raise ScaleRowsError(f"destination {list(key)} has no source bin 0; pass base_z")

    table: list[dict[str, Any]] = []
    new_rows: list[Any] = []
    refused: list[dict[str, Any]] = []
    for src, dst in rows:
        key = (dst[0], dst[1])
        old_z = dst[2]
        new_z = _scaled(base_of[key], old_z, g)
        in_strip = 0 <= new_z <= depth - 1
        stored = min(max(new_z, 0), depth - 1)
        is_used = src[axis] in used
        entry = {
            "dst_xy": list(key),
            "src_bin": src[axis],
            "old_z": old_z,
            "new_z": new_z,
            "stored_z": stored,
            "status": "in-strip" if in_strip else "clamped",
            "used": is_used,
        }
        table.append(entry)
        if is_used and not in_strip:
            refused.append(entry)
        new_rows.append([list(src), [dst[0], dst[1], stored]])
    if refused:
        listing = ", ".join(
            f"dst{e['dst_xy']} bin {e['src_bin']}: {e['old_z']}->{e['new_z']}" for e in refused
        )
        raise ScaleRowsError(
            f"gain {gain} puts used bins outside the strip 0..{depth - 1}: {listing}"
        )
    pairs = [(base_of[(dst[0], dst[1])], dst[2]) for src, dst in rows if src[axis] in used]
    return {
        "table": table,
        "rows": new_rows,
        "largest_no_clamp_gain": _max_no_clamp_gain(pairs, depth),
        "src_axis": axis,
    }
