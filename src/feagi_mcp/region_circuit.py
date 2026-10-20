"""Region-scoped circuit view: members, boundary, and edges (pure; no I/O).

Built from three public FEAGI payloads that the client fetches once:
``GET /v1/region/regions_members``, ``GET /v1/cortical_area/cortical_map_detailed``
and ``GET /v1/cortical_area/cortical_id_name_mapping``.

Boundary rule (same as ``feagi_evolutionary::circuit::resolve_boundary``):
a member is an input when it is sensory (IPU) or receives a mapping from a
non-member, and an output when it is motor (OPU) or sends a mapping to a
non-member. Edges are ``[src, dst]`` pairs with mapping rules dropped, so the
response stays small; use ``get_connectivity_summary`` for rule details.
"""

from __future__ import annotations

from typing import Any

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation

# @cursor:ffi-safe - stable role vocabulary shared with feagi-evolutionary AreaRole.
_ROLE_BY_IO_KIND = {"sensory": "sensory", "motor_output": "motor", "non_io": "internal"}


def area_role(cortical_id: str) -> str:
    """Role from cortical id byte 0: ``sensory``, ``motor``, ``internal`` or ``undecodable``."""
    decoded = decode_cortical_id_interpretation(cortical_id)
    if not decoded.get("ok"):
        return "undecodable"
    return _ROLE_BY_IO_KIND[decoded["io_kind"]]


def _string_list(entry: dict[str, Any], key: str) -> list[str]:
    """Strings under ``key``; non-list or missing values are treated as empty."""
    value = entry.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def collect_member_areas(
    regions: dict[str, Any], region_id: str, include_child_regions: bool
) -> tuple[list[str], list[str]]:
    """Member area ids of ``region_id`` and the region ids visited.

    Raises:
        KeyError: ``region_id`` or a listed child region is not in ``regions``.
    """
    members: set[str] = set()
    visited: list[str] = []
    pending = [region_id]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        entry = regions.get(current)
        if not isinstance(entry, dict):
            raise KeyError(current)
        visited.append(current)
        members.update(_string_list(entry, "areas"))
        if include_child_regions:
            pending.extend(_string_list(entry, "regions"))
    return sorted(members), sorted(visited)


def mapping_edges(cortical_map: dict[str, Any]) -> list[tuple[str, str]]:
    """Distinct ``(src, dst)`` pairs that carry at least one mapping rule, sorted."""
    edges: set[tuple[str, str]] = set()
    for src_id, dst_map in cortical_map.items():
        if not isinstance(dst_map, dict):
            continue
        for dst_id, rules in dst_map.items():
            if isinstance(rules, list) and rules:
                edges.add((src_id, dst_id))
    return sorted(edges)


def summarize_region_circuit(
    regions: dict[str, Any],
    cortical_map: dict[str, Any],
    names: dict[str, Any],
    region_id: str,
    include_child_regions: bool = True,
) -> dict[str, Any]:
    """Compact circuit view of one region; ``{"error": ...}`` for an unknown region."""
    rid = region_id.strip()
    try:
        member_ids, visited = collect_member_areas(regions, rid, include_child_regions)
    except KeyError as missing:
        return {
            "error": "unknown_region",
            "region_id": missing.args[0],
            "hint": "list region ids with get_brain_regions",
        }
    member_set = set(member_ids)
    roles = {cid: area_role(cid) for cid in member_ids}

    internal: list[list[str]] = []
    incoming: list[list[str]] = []
    outgoing: list[list[str]] = []
    for src, dst in mapping_edges(cortical_map):
        src_in, dst_in = src in member_set, dst in member_set
        if src_in and dst_in:
            internal.append([src, dst])
        elif dst_in:
            incoming.append([src, dst])
        elif src_in:
            outgoing.append([src, dst])

    fed_from_outside = {dst for _, dst in incoming}
    feeds_outside = {src for src, _ in outgoing}
    inputs = [c for c in member_ids if roles[c] == "sensory" or c in fed_from_outside]
    outputs = [c for c in member_ids if roles[c] == "motor" or c in feeds_outside]

    touched = {c for edge in internal + incoming + outgoing for c in edge}
    entry = regions[rid]
    return {
        "region_id": rid,
        "title": entry.get("title", ""),
        "include_child_regions": include_child_regions,
        "regions_included": visited,
        "member_count": len(member_ids),
        "members": [
            {"cortical_id": c, "name": names.get(c, ""), "role": roles[c]} for c in member_ids
        ],
        "boundary": {"input_area_ids": inputs, "output_area_ids": outputs},
        "designated": {
            "inputs": _string_list(entry, "designated_inputs"),
            "outputs": _string_list(entry, "designated_outputs"),
        },
        "edges": {"internal": internal, "incoming": incoming, "outgoing": outgoing},
        "isolated_area_ids": [c for c in member_ids if c not in touched],
    }
