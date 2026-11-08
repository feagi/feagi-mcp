"""Explain what drives one OPU channel, and lint every channel for ambiguous writers.

A channel of an OPU area is a block of voxels (``x`` = channel, ``z`` = bin). What a controller
reads is the decode of the channel's active voxels, so every source area with synapses onto the
channel's voxels is a *writer*. The route is per voxel: ``get_voxel_neurons`` (raw edges, one
``synapse_page`` at a time) for each voxel of the channel, then the incoming mappings of the
area for inhibitory (negative ``psc``) inputs. Nothing is stimulated and nothing is changed.

``burst=`` reads Fire Ledger frames that are *already recorded*: an area that is not tracked, or
a burst outside the tracked window, is an error, and the frames are requested with each area's
existing window so the read never resizes a subscription.

Voxel layout of a channel (from FEAGI's single-voxel decoder): a two-lobe variant keeps the
positive lobe in the even x columns of the channel and the negative lobe in the odd ones; every
other variant reads all columns as one lobe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from feagi_mcp.io_value_conversion import physical_fields, range_dict
from feagi_mcp.percentage_coding import UnitCoding
from feagi_mcp.registration_units import (
    ChannelRegistration,
    RegistrationError,
    channel_count,
    channel_depth,
    resolve_owner,
)
from feagi_mcp.spike_record import runs_of

#: Voxel reads in flight at once (the node serves them under its own lock).
VOXEL_CONCURRENCY = 16
#: Synapse pages read per voxel before the listing is reported truncated.
MAX_SYNAPSE_PAGES = 20
#: Decoded destination voxels listed per writer (the count and z runs are always complete).
MAX_VOXELS_LISTED = 12
#: Voxel reads one ``lint_motor_channels`` call may spend before it reports the rest unchecked.
LINT_VOXEL_BUDGET = 8000


class ExplainClient(Protocol):
    """The client surface the explainer uses (all read-only)."""

    async def get_voxel_neurons(
        self,
        cortical_id: str,
        x: int,
        y: int,
        z: int,
        synapse_page: int | None = None,
        view: str = "summary",
    ) -> dict[str, Any]: ...
    async def get_cortical_map_detailed(
        self, compact: bool = False, synapse_counts: bool = True, cortical_id: str | None = None
    ) -> dict[str, Any]: ...
    async def get_cortical_id_name_mapping(self) -> dict[str, Any]: ...
    async def get_fire_ledger_areas_window_config(self) -> dict[str, Any]: ...
    async def get_fire_history(self, area_ids: list[str], bursts: int) -> dict[str, Any]: ...


@dataclass
class Writer:
    """A source area with synapses onto the channel's voxels."""

    area_id: str
    name: str
    synapses: int = 0
    dst_voxels: set[tuple[int, int, int]] = field(default_factory=set)


@dataclass
class ChannelScan:
    """What the per-voxel route found for one channel."""

    voxels_read: int = 0
    read_errors: list[str] = field(default_factory=list)
    truncated_voxels: list[list[int]] = field(default_factory=list)
    writers: dict[str, Writer] = field(default_factory=dict)


def channel_voxels(area: dict[str, Any], channel: int) -> list[tuple[int, int, int]]:
    """Every voxel of one channel (the per-device x and y extents times the z depth)."""
    per_device = area.get("cortical_dimensions_per_device")
    depth = channel_depth(area)
    count = channel_count(area)
    if count is None or depth is None or not isinstance(per_device, list):
        raise ValueError("area dimensions do not state the channel count and extents")
    if channel < 0 or channel >= count:
        raise ValueError(f"channel {channel} out of range (area has {count} channels)")
    px, py = per_device[0], per_device[1]
    return [(channel * px + dx, y, z) for dx in range(px) for y in range(py) for z in range(depth)]


async def _read_voxel(
    client: ExplainClient, area_id: str, voxel: tuple[int, int, int], gate: asyncio.Semaphore
) -> tuple[tuple[int, int, int], list[dict[str, Any]], str | None, bool]:
    """Incoming synapses of one voxel (all pages up to the cap): synapses, error, truncated."""
    synapses: list[dict[str, Any]] = []
    page = 0
    async with gate:
        while True:
            payload = await client.get_voxel_neurons(
                area_id, *voxel, synapse_page=page, view="edges"
            )
            if payload.get("error"):
                return voxel, synapses, str(payload["error"]), False
            more = False
            for neuron in payload.get("neurons") or []:
                if isinstance(neuron, dict):
                    rows = neuron.get("incoming_synapses") or []
                    synapses.extend(r for r in rows if isinstance(r, dict))
                    more = more or bool(neuron.get("incoming_synapses_has_more"))
            if not more:
                return voxel, synapses, None, False
            page += 1
            if page >= MAX_SYNAPSE_PAGES:
                return voxel, synapses, None, True


async def scan_channel(client: ExplainClient, area: dict[str, Any], channel: int) -> ChannelScan:
    """Read every voxel of the channel and group the incoming synapses by source area."""
    area_id = str(area["cortical_id"])
    voxels = channel_voxels(area, channel)
    gate = asyncio.Semaphore(VOXEL_CONCURRENCY)
    reads = await asyncio.gather(*(_read_voxel(client, area_id, v, gate) for v in voxels))
    scan = ChannelScan(voxels_read=len(voxels))
    for voxel, synapses, error, truncated in reads:
        if error:
            scan.read_errors.append(f"{list(voxel)}: {error}")
        if truncated:
            scan.truncated_voxels.append(list(voxel))
        for syn in synapses:
            src = syn.get("source_cortical_id")
            if not isinstance(src, str):
                continue
            name = syn.get("source_cortical_name")
            writer = scan.writers.setdefault(
                src, Writer(src, name if isinstance(name, str) else src)
            )
            writer.synapses += 1
            writer.dst_voxels.add(voxel)
    return scan


async def incoming_inhibition(
    client: ExplainClient, area_id: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], str | None]:
    """Incoming mapping rules with a negative ``psc``: ``(by source id, names, error)``."""
    mapping = await client.get_cortical_map_detailed(cortical_id=area_id)
    if mapping.get("error"):
        return {}, {}, str(mapping["error"])
    names = await client.get_cortical_id_name_mapping()
    name_by_id = (
        {k: v for k, v in names.items() if isinstance(v, str)} if "error" not in names else {}
    )
    found: dict[str, list[dict[str, Any]]] = {}
    for src_id, dst_map in mapping.items():
        rules = dst_map.get(area_id) if isinstance(dst_map, dict) else None
        for rule in rules if isinstance(rules, list) else []:
            psc = rule.get("postSynapticCurrent_multiplier") if isinstance(rule, dict) else None
            if isinstance(psc, (int, float)) and psc < 0:
                found.setdefault(src_id, []).append(
                    {"morphology": rule.get("morphology_id"), "psc": psc}
                )
    return found, name_by_id, None


def decode_voxel(coding: UnitCoding, x_offset: int, z: int) -> dict[str, Any]:
    """Fraction one active voxel decodes to (two-lobe variants: even x offset is positive)."""
    try:
        if coding.two_lobe and x_offset % 2 == 1:
            return {"fraction": coding.decode_fraction([], [z])}
        return {"fraction": coding.decode_fraction([z])}
    except ValueError as e:
        return {"error": str(e)}


def writer_row(
    writer: Writer,
    area: dict[str, Any],
    channel: int,
    reg: ChannelRegistration | None,
    inhibitory: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compact row of one writer: synapses, destination z runs and decoded voxels."""
    per_device = area["cortical_dimensions_per_device"]
    voxels = sorted(writer.dst_voxels, key=lambda v: (v[2], v[0], v[1]))
    row: dict[str, Any] = {
        "area": writer.name,
        "area_id": writer.area_id,
        "synapses": writer.synapses,
        "dst_voxel_count": len(voxels),
        "dst_z_runs": runs_of(sorted({v[2] for v in voxels})),
    }
    if writer.area_id in inhibitory:
        row["also_inhibits_area"] = inhibitory[writer.area_id]
    if reg is None:
        row["dst_voxels"] = [list(v) for v in voxels[:MAX_VOXELS_LISTED]]
        return row
    listed = []
    for x, y, z in voxels[:MAX_VOXELS_LISTED]:
        decoded = decode_voxel(reg.coding, x - channel * per_device[0], z)
        entry: dict[str, Any] = {"voxel": [x, y, z], **decoded}
        if "fraction" in decoded:
            entry.update(physical_fields(reg, decoded["fraction"]))
        listed.append(entry)
    row["dst_decoded"] = listed
    if len(voxels) > MAX_VOXELS_LISTED:
        row["dst_decoded_truncated"] = len(voxels) - MAX_VOXELS_LISTED
    return row


async def _tracked_frames(
    client: ExplainClient, area_ids: list[str], burst: int
) -> tuple[dict[str, dict[int, list[list[int]]]], str | None]:
    """Recorded fire frames covering ``burst`` per area; an error when untracked or outside."""
    config = await client.get_fire_ledger_areas_window_config()
    tracked = config.get("areas")
    if config.get("error") or not isinstance(tracked, dict):
        return {}, f"fire ledger window config unavailable: {config.get('error', config)}"
    untracked = [a for a in area_ids if a not in tracked]
    if untracked:
        return {}, f"areas not tracked by the fire ledger (no frames recorded): {untracked}"
    by_window: dict[int, list[str]] = {}
    for area_id in area_ids:
        by_window.setdefault(int(tracked[area_id]), []).append(area_id)
    frames: dict[str, dict[int, list[list[int]]]] = {}
    for window, ids in by_window.items():
        payload = await client.get_fire_history(ids, window)
        areas = payload.get("areas")
        current = payload.get("current_burst")
        if payload.get("error") or not isinstance(areas, dict) or not isinstance(current, int):
            return {}, f"fire_history read failed: {payload.get('error', sorted(payload))}"
        if not current - window + 1 <= burst <= current:
            return {}, (
                f"burst {burst} is outside the recorded window {current - window + 1}..{current} "
                f"(window {window})"
            )
        for area_id in ids:
            entry = areas.get(area_id)
            rows = entry.get("frames") if isinstance(entry, dict) else None
            frames[area_id] = {
                f["burst"]: [list(map(int, v)) for v in f.get("voxels") or []]
                for f in rows or []
                if isinstance(f, dict) and isinstance(f.get("burst"), int)
            }
            if burst not in frames[area_id]:
                return {}, f"no frame for burst {burst} in area {area_id} (window {window})"
    return frames, None


async def burst_view(
    client: ExplainClient,
    area: dict[str, Any],
    channel: int,
    reg: ChannelRegistration | None,
    writer_ids: list[str],
    burst: int,
) -> dict[str, Any]:
    """What fired in one already-recorded burst: the channel's command and the active writers."""
    area_id = str(area["cortical_id"])
    frames, problem = await _tracked_frames(client, [area_id, *writer_ids], burst)
    if problem:
        return {"burst": burst, "error": problem}
    px = area["cortical_dimensions_per_device"][0]
    fired = [v for v in frames[area_id][burst] if channel * px <= v[0] < (channel + 1) * px]
    view: dict[str, Any] = {
        "burst": burst,
        "channel_fired_voxels": fired,
        "writers_fired": {w: len(frames[w][burst]) for w in writer_ids if frames[w][burst]},
    }
    if not fired:
        view["command"] = None
        view["note"] = "no voxel of the channel fired in this burst"
    elif reg is None:
        view["command"] = {"error": "no registration: the decode needs the registered unit"}
    else:
        base = channel * px
        pos = [v[2] for v in fired if not reg.coding.two_lobe or (v[0] - base) % 2 == 0]
        neg = [v[2] for v in fired if reg.coding.two_lobe and (v[0] - base) % 2 == 1]
        try:
            fraction = reg.coding.decode_fraction(pos, neg)
            view["command"] = {"fraction": fraction, **physical_fields(reg, fraction)}
        except ValueError as e:
            view["command"] = {"error": str(e)}
    return view


def _truncation(scan: ChannelScan) -> dict[str, Any] | None:
    """Explicit truncation / read-failure report of a scan, or ``None`` when complete."""
    out: dict[str, Any] = {}
    if scan.truncated_voxels:
        out["synapse_pages_capped_at"] = MAX_SYNAPSE_PAGES
        out["voxels_with_more_synapses"] = scan.truncated_voxels[:MAX_VOXELS_LISTED]
        out["voxels_with_more_synapses_count"] = len(scan.truncated_voxels)
    if scan.read_errors:
        out["voxel_read_errors"] = scan.read_errors[:MAX_VOXELS_LISTED]
        out["voxel_read_error_count"] = len(scan.read_errors)
    return out or None


async def explain_channel(
    client: ExplainClient,
    area: dict[str, Any],
    channel: int,
    agents: dict[str, dict[str, Any]],
    burst: int | None = None,
    inhibition: tuple[dict[str, list[dict[str, Any]]], dict[str, str], str | None] | None = None,
) -> dict[str, Any]:
    """Writers, inhibitory inputs and (with ``burst``) the recorded command of one channel.

    ``inhibition`` is the :func:`incoming_inhibition` result when the caller already read it
    for the area (the lint reads it once per area).
    """
    area_id = str(area["cortical_id"])
    out: dict[str, Any] = {
        "area": area.get("cortical_name"),
        "area_id": area_id,
        "channel": channel,
        "depth": channel_depth(area),
    }
    reg: ChannelRegistration | None = None
    try:
        agent_id, _, reg = resolve_owner(agents, area, channel)
        out["agent_id"] = agent_id
    except RegistrationError as e:
        out["registration"] = {"error": str(e), "decode": "unavailable"}
    if reg is not None:
        out["variant"] = reg.coding.variant
        out["physical_range"] = range_dict(reg)
        if reg.friendly_name:
            out["channel_name"] = reg.friendly_name
    scan = await scan_channel(client, area, channel)
    inhibitory, names, inhibition_error = inhibition or await incoming_inhibition(client, area_id)
    out["voxels_read"] = scan.voxels_read
    writers = sorted(scan.writers.values(), key=lambda w: (-w.synapses, w.name))
    out["writers"] = [writer_row(w, area, channel, reg, inhibitory) for w in writers]
    out["inhibitory_inputs"] = [
        {
            "area": names.get(src, src),
            "area_id": src,
            "rules": rules,
            "writes_channel": src in scan.writers,
        }
        for src, rules in sorted(inhibitory.items())
    ]
    if inhibition_error:
        out["inhibitory_inputs_error"] = inhibition_error
    truncation = _truncation(scan)
    if truncation:
        out["truncated"] = truncation
    if burst is not None:
        out["at_burst"] = await burst_view(
            client, area, channel, reg, [w.area_id for w in writers], burst
        )
    return out


def lint_channel(explained: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence-backed warnings for one explained channel (never a verdict)."""
    warnings: list[dict[str, Any]] = []
    writers = explained["writers"]
    where = {"area": explained["area"], "channel": explained["channel"]}
    if not writers:
        warnings.append(
            {
                **where,
                "code": "no_writer_found",
                "detail": "no source area has synapses onto this channel's voxels",
            }
        )
    elif len(writers) > 1:
        inhibitory = explained["inhibitory_inputs"]
        warnings.append(
            {
                **where,
                "code": "multiple_writers",
                "detail": (
                    f"{len(writers)} source areas write this channel's voxels; the command is "
                    "the decode of all active voxels together"
                    + (
                        f"; {len(inhibitory)} inhibitory input area(s) found"
                        if inhibitory
                        else "; no inhibitory input found"
                    )
                ),
                "evidence": {
                    "writers": [
                        {"area": w["area"], "dst_z_runs": w["dst_z_runs"]} for w in writers
                    ],
                    "inhibitory_inputs": [i["area"] for i in inhibitory],
                },
            }
        )
    return warnings


async def lint_areas(
    client: ExplainClient, areas: list[dict[str, Any]], agents: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Lint every channel of the given OPU areas; compact warnings with their evidence.

    A warning is evidence ("these writers and inhibitory inputs were found"), never a verdict
    that a channel is wrong. Voxel reads are bounded by :data:`LINT_VOXEL_BUDGET`; channels
    left unread are listed, and so are channels whose scan was cut short (``truncated``).
    """
    used = 0
    checked = 0
    warnings: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []
    truncated: list[dict[str, Any]] = []
    for area in areas:
        label = area.get("cortical_name") or area.get("cortical_id")
        count = channel_count(area)
        if count is None or channel_depth(area) is None:
            skipped.append({"area": label, "reason": "dimensions do not state channels and depth"})
            continue
        inhibition = await incoming_inhibition(client, str(area["cortical_id"]))
        for channel in range(count):
            cost = len(channel_voxels(area, channel))
            if used + cost > LINT_VOXEL_BUDGET:
                unchecked.append({"area": label, "channel": channel})
                continue
            used += cost
            explained = await explain_channel(client, area, channel, agents, inhibition=inhibition)
            checked += 1
            warnings.extend(lint_channel(explained))
            if "truncated" in explained:
                truncated.append(
                    {"area": label, "channel": channel, "detail": explained["truncated"]}
                )
    result: dict[str, Any] = {
        "areas_checked": len(areas) - len(skipped),
        "channels_checked": checked,
        "voxel_reads": used,
        "warnings": warnings,
    }
    if skipped:
        result["skipped"] = skipped
    if unchecked:
        result["not_checked"] = {
            "reason": f"voxel read budget of {LINT_VOXEL_BUDGET} reached",
            "channels": unchecked[:MAX_VOXELS_LISTED],
            "count": len(unchecked),
        }
    if truncated:
        result["truncated"] = truncated
    return result
