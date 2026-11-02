"""Accept a cortical area name or id on every tool argument that names a cortical area.

One table (:data:`AREA_ARGS`) says which argument of which tool holds an area reference;
:func:`resolve_area_arguments` rewrites those arguments to wire ids before the tool runs
(applied once, in ``server._StudioAwareFastMCP.call_tool``). A value that is a valid cortical id
passes through unchanged; otherwise it must match one area's exact display name. An unknown or
ambiguous value raises ``ToolError`` listing close matches.
"""

from __future__ import annotations

import difflib
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from feagi_mcp.feagi_client import _looks_like_cortical_id

#: Scalar string arguments (``None`` allowed) per tool.
_SCALARS: dict[str, tuple[str, ...]] = {
    "monitor_activity": ("area_id",),
    "get_connectivity": ("src_area", "dst_area"),
    "get_memory_area_runtime_config": ("cortical_id",),
    "set_memory_mp_encoding": ("cortical_id",),
    "get_area_parameters": ("area_id",),
    "stimulate_area": ("area_id",),
    "stimulate_area_batch": ("area_id",),
    "hold_stimulus": ("area",),
    "set_area_modulators": ("cortical_id",),
    "unsubscribe_area_modulator": ("cortical_id",),
    "set_mapping_modulators": ("src_area", "dst_area"),
    "unsubscribe_mapping_modulator": ("src_area", "dst_area"),
    "trace_signal_path": ("from_area", "to_area"),
    "get_cortical_synapse_counts": ("area_id",),
    "get_area_semantic_info": ("area_id",),
    "update_cortical_area": ("cortical_id",),
    "delete_cortical_area": ("cortical_id",),
    "get_cortical_mapping": ("src_area", "dst_area"),
    "validate_magnitude_passthrough": ("src_area", "dst_area"),
    "wire_value_passthrough": ("src_area", "dst_area"),
    "expand_value_to_bins": ("src_area",),
    "decode_class_map": ("area_id",),
    "measure_audio_io_disparity": ("src_area", "dst_area"),
    "diagnose_memory_twin_mapping": ("src_area", "dst_area"),
    "diagnose_mapping_plasticity": ("src_area", "dst_area"),
    "update_cortical_mapping": ("src_area", "dst_area"),
    "recommend_connectivity_rules": ("src_area", "dst_area"),
    "propose_connectivity_rule": ("src_area", "dst_area"),
    "apply_connectivity_rule": ("src_area", "dst_area"),
    "delete_cortical_mapping": ("src_area", "dst_area"),
    "get_cortical_map_detailed": ("cortical_id",),
    "inspect_cortical_area": ("cortical_id",),
    "clone_cortical_area": ("source_area_id",),
    "get_motor_snapshot_last": ("cortical_id",),
    "get_sensor_snapshot_last": ("cortical_id",),
    "inspect_neuron_state_at": ("cortical_id",),
    "list_memory_neurons": ("cortical_id",),
    "get_voxel_neurons": ("cortical_id",),
    "list_area_synapses": ("cortical_area_id",),
    "list_area_neuron_states": ("area_id",),
    "build_stance_relative_mapping": ("src_area_id", "dst_area_id"),
    "build_reflex_mapping": ("src_area_id", "dst_area_id"),
    "probe_area_response": ("stimulus_area", "observe_area"),
    "watch_mapping_weights": ("src_area", "dst_area"),
    "freeze_mapping_plasticity": ("src_area", "dst_area"),
    "reset_mapping_weights": ("src_area", "dst_area"),
}

#: List-of-string arguments per tool.
_LISTS: dict[str, tuple[str, ...]] = {
    "inspect_cortical_areas_batch": ("cortical_ids",),
    "inspect_cortical_areas_minimal": ("cortical_ids",),
    "reset_cortical_neural_state": ("cortical_ids",),
    "reset_area_incoming_weights": ("cortical_ids",),
    "monitor_activity_batch": ("area_ids",),
    "record_aligned_trace": ("areas",),
    "run_stimulus_protocol": ("record_areas",),
}

#: Tools whose ``entries`` / ``steps`` hold ``stimuli: [{"area_id": ...}]``.
_STIMULI_ENTRIES: dict[str, str] = {
    "schedule_stimulus": "entries",
    "run_stimulus_protocol": "steps",
}

#: Tools with an area argument that is deliberately not resolved here (name -> reason).
SKIPPED: dict[str, str] = {
    "record_spikes": "areas may be region refs; the client already resolves names and regions",
    "explain_cortical_area_naming": "explains the id text itself; a name has nothing to explain",
    "interpret_cortical_id": "decodes the id text itself",
    "create_cortical_area": "cortical_id is a new id to assign, not an existing area",
    "get_connectivity_summary": "src_filter/dst_filter are substring filters, not area refs",
    "list_cortical_areas": "cortical_id_contains is a substring filter",
}

AREA_ARGS: dict[str, tuple[str, ...]] = {
    name: tuple(
        _SCALARS.get(name, ())
        + _LISTS.get(name, ())
        + (("<stimuli>.area_id",) if name in _STIMULI_ENTRIES else ())
    )
    for name in sorted({*_SCALARS, *_LISTS, *_STIMULI_ENTRIES})
}

NameMap = Callable[[], Awaitable[dict[str, Any]]]


def _close_matches(ref: str, names: dict[str, str]) -> list[str]:
    lowered = {n.lower(): n for n in names.values()}
    close = difflib.get_close_matches(ref.lower(), list(lowered), n=5, cutoff=0.5)
    subs = [k for k in lowered if ref.lower() in k or k in ref.lower()]
    ordered = list(dict.fromkeys(close + subs))[:5]
    return [
        f"{lowered[k]} ({next(i for i, n in names.items() if n == lowered[k])})" for k in ordered
    ]


def _resolve_one(ref: Any, mapping: dict[str, str]) -> Any:
    if not isinstance(ref, str) or not ref.strip():
        return ref
    ref = ref.strip()
    if ref in mapping or _looks_like_cortical_id(ref):
        return ref
    hits = [cid for cid, name in mapping.items() if name.strip() == ref]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ToolError(
            f"area name '{ref}' matches {len(hits)} areas ({', '.join(hits)}); use an id"
        )
    close = _close_matches(ref, mapping)
    hint = f"; close matches: {', '.join(close)}" if close else ""
    raise ToolError(f"unknown cortical area '{ref}': pass an area id or its exact name{hint}")


async def resolve_area_arguments(
    tool: str, arguments: dict[str, Any], name_map: NameMap
) -> dict[str, Any]:
    """Return ``arguments`` with every area reference of ``tool`` rewritten to a cortical id.

    ``name_map`` is awaited at most once, and only when some reference is not already a valid
    id. If the id/name list cannot be read the arguments are returned unchanged so FEAGI
    reports the problem itself.
    """
    if tool not in AREA_ARGS:
        return arguments
    out = dict(arguments)
    refs: list[Any] = []
    for key in _SCALARS.get(tool, ()):
        if isinstance(out.get(key), str):
            refs.append(out[key])
    for key in _LISTS.get(tool, ()):
        if isinstance(out.get(key), list):
            refs.extend(out[key])
    stim_key = _STIMULI_ENTRIES.get(tool)
    stim_items: list[dict[str, Any]] = []
    if stim_key and isinstance(out.get(stim_key), list):
        for entry in out[stim_key]:
            if isinstance(entry, dict) and isinstance(entry.get("stimuli"), list):
                stim_items.extend(s for s in entry["stimuli"] if isinstance(s, dict))
        refs.extend(s.get("area_id") for s in stim_items)
    if all(not isinstance(r, str) or _looks_like_cortical_id(r.strip()) for r in refs):
        return out
    raw = await name_map()
    if not isinstance(raw, dict) or "error" in raw:
        return out
    mapping = {k: v for k, v in raw.items() if isinstance(v, str)}
    for key in _SCALARS.get(tool, ()):
        if isinstance(out.get(key), str):
            out[key] = _resolve_one(out[key], mapping)
    for key in _LISTS.get(tool, ()):
        if isinstance(out.get(key), list):
            out[key] = [_resolve_one(r, mapping) for r in out[key]]
    if stim_key and isinstance(out.get(stim_key), list):
        fixed = []
        for entry in out[stim_key]:
            if isinstance(entry, dict) and isinstance(entry.get("stimuli"), list):
                entry = {
                    **entry,
                    "stimuli": [
                        {**s, "area_id": _resolve_one(s.get("area_id"), mapping)}
                        if isinstance(s, dict) and "area_id" in s
                        else s
                        for s in entry["stimuli"]
                    ],
                }
            fixed.append(entry)
        out[stim_key] = fixed
    return out
