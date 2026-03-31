"""Brain Visualizer placement constraints for MCP ``create_cortical_area``.

Enforces minimum separation from the world origin (axis gizmo) and between anchors so
labels stay readable. Suggested layouts follow BV viewing conventions (camera toward +Z).

Best practices (agent guidance)
--------------------------------

1. **Visibility (XY plane)** — The BV camera looks toward **+Z**. Lay out cortical anchors
   primarily in the **XY** plane (vary **X** and **Y**, keep **Z** stable within a circuit)
   so users see the circuit head-on. Avoid stacking depth along Z unless you intend a
   temporal / depth metaphor.

2. **Semantics by axis**
   - **Co-occurring inputs** (same time step): same **Y** and **Z**, spread along **+X**.
   - **Small circuits / hierarchy**: use **+Y** for steps deeper in a local hierarchy
     (layers “down” the page in map space).
   - **Deep / temporal networks**: use **+Z** so activity can be read as propagating
     forward in time (later stages at higher Z).

3. **Near origin, not cramped** — Prefer anchors **near the origin** so the whole circuit
   fits one comfortable view, but stay outside ``ORIGIN_EXCLUSION_RADIUS_VOXELS`` and keep
   at least ``MIN_ANCHOR_SEPARATION_VOXELS`` between anchors so labels do not collide.

Constants ``LAYOUT_*`` select how ``suggest_anchor_positions`` increments successive anchors.
"""

from __future__ import annotations

import math
from typing import Any

# Minimum Euclidean distance from (0,0,0) to area anchor; inside this sphere the
# BV axis helper tends to obscure areas.
ORIGIN_EXCLUSION_RADIUS_VOXELS = 20

# Minimum center-to-center distance between this new anchor and any existing area
# anchor (reduces overlapping display names in BV).
MIN_ANCHOR_SEPARATION_VOXELS = 32

# Default anchor when no parent hint: outside origin exclusion, close enough for one-screen
# visibility with typical circuits (see module docstring).
DEFAULT_LAYOUT_BASE: tuple[int, int, int] = (120, 120, 120)

# Layout modes for ``suggest_anchor_positions`` (BV camera faces +Z; XY emphasis default).
LAYOUT_XY_PLANE = "xy_plane"
LAYOUT_COOCCURRING_INPUTS = "co_occurring_inputs"
LAYOUT_HIERARCHY_Y = "hierarchy_y"
LAYOUT_TEMPORAL_Z = "temporal_z"


def _euclidean(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(float((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def check_origin_exclusion(
    position: list[int],
    *,
    radius: int = ORIGIN_EXCLUSION_RADIUS_VOXELS,
) -> str | None:
    """Return an error message if ``position`` is too close to the origin, else None."""
    if len(position) != 3:
        return None
    x, y, z = int(position[0]), int(position[1]), int(position[2])
    d = math.sqrt(float(x * x + y * y + z * z))
    if d < float(radius):
        return (
            f"position {position} is within {radius} voxels of the origin; "
            "place the area outside this radius so it stays visible beside the BV axis "
            "(MCP placement policy)."
        )
    return None


def _coords_from_geometry_entry(entry: Any) -> tuple[int, int, int] | None:
    if not isinstance(entry, dict):
        return None
    c3 = entry.get("coordinates_3d")
    if isinstance(c3, list) and len(c3) == 3:
        try:
            return (int(c3[0]), int(c3[1]), int(c3[2]))
        except (TypeError, ValueError):
            pass
    pos = entry.get("position")
    if isinstance(pos, dict):
        try:
            return (int(pos["x"]), int(pos["y"]), int(pos["z"]))
        except (KeyError, TypeError, ValueError):
            pass
    return None


def parse_region_coordinate_3d(
    regions_members: dict[str, Any],
    region_id: str,
) -> tuple[int, int, int] | None:
    """Read ``coordinate_3d`` for a region from ``get_regions_members`` JSON."""
    entry = regions_members.get(region_id)
    if not isinstance(entry, dict):
        return None
    c3 = entry.get("coordinate_3d")
    if isinstance(c3, list) and len(c3) >= 3:
        try:
            return (int(c3[0]), int(c3[1]), int(c3[2]))
        except (TypeError, ValueError):
            pass
    return None


def parse_region_coordinate_2d(
    regions_members: dict[str, Any],
    region_id: str,
) -> tuple[int, int] | None:
    """Read ``coordinate_2d`` for a region from ``get_regions_members`` JSON."""
    entry = regions_members.get(region_id)
    if not isinstance(entry, dict):
        return None
    c2 = entry.get("coordinate_2d")
    if isinstance(c2, list) and len(c2) >= 2:
        try:
            return (int(c2[0]), int(c2[1]))
        except (TypeError, ValueError):
            pass
    return None


def _valid_anchor_candidate(
    position: list[int],
    geometry_by_area_id: dict[str, Any],
    already_placed: list[list[int]],
    *,
    min_separation: int = MIN_ANCHOR_SEPARATION_VOXELS,
) -> bool:
    if check_origin_exclusion(position) is not None:
        return False
    sep_err = check_min_separation_to_existing(
        position,
        geometry_by_area_id,
        min_separation=min_separation,
    )
    if sep_err:
        return False
    pt = (int(position[0]), int(position[1]), int(position[2]))
    for other in already_placed:
        if _euclidean(pt, (int(other[0]), int(other[1]), int(other[2]))) < float(min_separation):
            return False
    return True


def _resolve_layout_and_axis(
    layout: str | None,
    axis: str | None,
) -> tuple[str, int]:
    """Return (normalized layout name, primary axis index 0=x,1=y,2=z)."""
    if axis is not None:
        legacy = axis.lower()
        ai = {"x": 0, "y": 1, "z": 2}.get(legacy, 0)
        if legacy == "z":
            return (LAYOUT_TEMPORAL_Z, ai)
        if legacy == "y":
            return (LAYOUT_HIERARCHY_Y, ai)
        return (LAYOUT_XY_PLANE, ai)

    key = (layout or LAYOUT_XY_PLANE).lower().strip()
    if key == LAYOUT_COOCCURRING_INPUTS:
        key = LAYOUT_XY_PLANE
    if key == LAYOUT_XY_PLANE:
        return (LAYOUT_XY_PLANE, 0)
    if key == LAYOUT_HIERARCHY_Y:
        return (LAYOUT_HIERARCHY_Y, 1)
    if key == LAYOUT_TEMPORAL_Z:
        return (LAYOUT_TEMPORAL_Z, 2)
    return (LAYOUT_XY_PLANE, 0)


def _seed_position(
    index: int,
    spacing: int,
    sx: int,
    sy: int,
    sz: int,
    primary_axis: int,
) -> list[int]:
    """Unvalidated anchor for slot ``index`` along ``primary_axis`` from base."""
    p = [sx, sy, sz]
    p[primary_axis] += index * spacing
    return p


def suggest_anchor_positions(
    count: int,
    geometry_by_area_id: dict[str, Any],
    *,
    base_hint: tuple[int, int, int] | None = None,
    spacing: int = MIN_ANCHOR_SEPARATION_VOXELS,
    layout: str | None = None,
    axis: str | None = None,
) -> list[list[int]]:
    """Propose 3D anchors respecting origin exclusion, label spacing, and layout semantics.

    Default **layout** is ``xy_plane``: successive anchors step along **+X** with fixed **Y**
    and **Z** (good for BV camera toward +Z). Use ``hierarchy_y`` for shallow depth along **+Y**,
    ``temporal_z`` for stages along **+Z** (time / feedforward depth). ``co_occurring_inputs``
    is an alias for ``xy_plane`` (same Y, Z; spread X).

    Legacy: if ``axis`` is ``"x"``|``"y"``|``"z"``, stacking follows that axis only (deprecated;
    prefer ``layout``).

    Args:
        count: Number of positions (>= 1).
        geometry_by_area_id: Same shape as ``get_cortical_area_geometry()`` mapping.
        base_hint: Preferred first anchor (e.g. parent brain region ``coordinate_3d``); else
            ``DEFAULT_LAYOUT_BASE`` near origin.
        spacing: Step between consecutive anchors on the primary layout axis.
        layout: ``xy_plane`` | ``co_occurring_inputs`` | ``hierarchy_y`` | ``temporal_z``.
        axis: Optional legacy stacking axis.

    Returns:
        List of ``[x, y, z]`` anchors, length ``count``.
    """
    if count < 1:
        return []
    _layout_name, primary_ai = _resolve_layout_and_axis(layout, axis)
    sx, sy, sz = base_hint if base_hint is not None else DEFAULT_LAYOUT_BASE
    placed: list[list[int]] = []
    step = max(spacing // 4, 8)

    for i in range(count):
        p = _seed_position(i, spacing, sx, sy, sz, primary_ai)
        attempts = 0
        while attempts < 400:
            if _valid_anchor_candidate(p, geometry_by_area_id, placed):
                placed.append([p[0], p[1], p[2]])
                break
            p[primary_ai] += step
            attempts += 1
        else:
            placed.append([p[0], p[1], p[2]])

    return placed


def check_min_separation_to_existing(
    position: list[int],
    geometry_by_area_id: dict[str, Any],
    *,
    min_separation: int = MIN_ANCHOR_SEPARATION_VOXELS,
) -> str | None:
    """Return an error if ``position`` is too close to any area in ``geometry_by_area_id``."""
    if len(position) != 3:
        return None
    p = (int(position[0]), int(position[1]), int(position[2]))
    for aid, entry in geometry_by_area_id.items():
        if aid == "error" or not isinstance(aid, str):
            continue
        other = _coords_from_geometry_entry(entry)
        if other is None:
            continue
        if _euclidean(p, other) < float(min_separation):
            name = entry.get("cortical_name", aid) if isinstance(entry, dict) else aid
            return (
                f"position {list(p)} is within {min_separation} voxels of existing area "
                f"'{name}' at {list(other)}; increase spacing so BV labels do not overlap "
                "(MCP placement policy)."
            )
    return None
