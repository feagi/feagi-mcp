"""Compact circuit views: names, dimensions, mapping rules and synapse counts only (pure).

Built from ``cortical_map_detailed`` (``{src_id: {dst_id: [rule, ...]}}``), the area geometry
(``{cortical_id: {cortical_name, cortical_dimensions, ...}}``) and optional per-edge synapse
counts from :mod:`feagi_mcp.synapse_counts`. Ids are replaced by area names.
"""

from __future__ import annotations

from typing import Any

from feagi_mcp.region_circuit import collect_member_areas, mapping_edges


def compact_rule(rule: Any) -> dict[str, Any]:
    """One mapping rule as ``{rule, psc, delay, plastic}`` (plus ``scalar`` when not 1,1,1)."""
    if not isinstance(rule, dict):
        return {"rule": str(rule)}
    out: dict[str, Any] = {
        "rule": rule.get("morphology_id"),
        "psc": rule.get("postSynapticCurrent_multiplier"),
        "delay": rule.get("synaptic_delay_bursts"),
        "plastic": bool(rule.get("plasticity_flag")),
    }
    scalar = rule.get("morphology_scalar")
    if isinstance(scalar, list) and scalar != [1, 1, 1]:
        out["scalar"] = scalar
    return out


def area_name(geometry: dict[str, Any], cortical_id: str) -> str:
    """Display name of an area, or its id when the geometry does not list it."""
    entry = geometry.get(cortical_id)
    name = entry.get("cortical_name") if isinstance(entry, dict) else None
    return name if isinstance(name, str) else cortical_id


def area_row(geometry: dict[str, Any], cortical_id: str) -> dict[str, Any]:
    """``{name, dimensions}`` for one area."""
    entry = geometry.get(cortical_id)
    dims = entry.get("cortical_dimensions") if isinstance(entry, dict) else None
    return {"name": area_name(geometry, cortical_id), "dimensions": dims}


def _edge_row(
    src: str,
    dst: str,
    cortical_map: dict[str, Any],
    geometry: dict[str, Any],
    counts: dict[tuple[str, str], int | None] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "src": area_name(geometry, src),
        "dst": area_name(geometry, dst),
        "rules": [compact_rule(r) for r in cortical_map[src][dst]],
    }
    if counts is not None:
        row["synapses"] = counts.get((src, dst))
    return row


def compact_edge_pairs(cortical_map: dict[str, Any]) -> list[tuple[str, str]]:
    """Edges that carry at least one rule, as sorted ``(src_id, dst_id)`` pairs."""
    return mapping_edges(cortical_map)


def filter_map_to_area(cortical_map: dict[str, Any], area_id: str) -> dict[str, Any]:
    """Keep only the mappings where ``area_id`` is the source or the destination."""
    out: dict[str, Any] = {}
    for src_id, dst_map in cortical_map.items():
        if not isinstance(dst_map, dict):
            continue
        kept = {d: r for d, r in dst_map.items() if src_id == area_id or d == area_id}
        if kept:
            out[src_id] = kept
    return out


def compact_map(
    cortical_map: dict[str, Any],
    geometry: dict[str, Any],
    counts: dict[tuple[str, str], int | None] | None = None,
) -> dict[str, Any]:
    """Whole-brain compact view: areas (name, dimensions) and edges (name, rules, synapses)."""
    pairs = compact_edge_pairs(cortical_map)
    touched = sorted({c for pair in pairs for c in pair}, key=lambda c: area_name(geometry, c))
    return {
        "area_count": len(touched),
        "edge_count": len(pairs),
        "areas": [area_row(geometry, c) for c in touched],
        "edges": [_edge_row(s, d, cortical_map, geometry, counts) for s, d in pairs],
    }


def region_member_ids(
    regions: dict[str, Any], region_id: str, include_child_regions: bool
) -> list[str]:
    """Member area ids of a region; raises ``KeyError`` for an unknown region id."""
    members, _ = collect_member_areas(regions, region_id.strip(), include_child_regions)
    return members


def compact_region(
    regions: dict[str, Any],
    cortical_map: dict[str, Any],
    geometry: dict[str, Any],
    region_id: str,
    include_child_regions: bool = True,
    counts: dict[tuple[str, str], int | None] | None = None,
) -> dict[str, Any]:
    """Compact region view; ``{"error": "unknown_region", ...}`` for an unknown id."""
    rid = region_id.strip()
    try:
        members = region_member_ids(regions, rid, include_child_regions)
    except KeyError as missing:
        return {
            "error": "unknown_region",
            "region_id": missing.args[0],
            "hint": "list region ids with get_brain_regions",
        }
    member_set = set(members)
    edges: list[dict[str, Any]] = []
    for src, dst in region_edge_pairs(cortical_map, member_set):
        row = _edge_row(src, dst, cortical_map, geometry, counts)
        row["scope"] = (
            "internal"
            if src in member_set and dst in member_set
            else "incoming"
            if dst in member_set
            else "outgoing"
        )
        edges.append(row)
    entry = regions[rid]
    return {
        "title": entry.get("title", ""),
        "member_count": len(members),
        "members": [area_row(geometry, c) for c in members],
        "edges": edges,
    }


def region_edge_pairs(cortical_map: dict[str, Any], member_set: set[str]) -> list[tuple[str, str]]:
    """Edges with at least one end inside the region."""
    return [
        (s, d) for s, d in compact_edge_pairs(cortical_map) if s in member_set or d in member_set
    ]
