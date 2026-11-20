"""Detect a registered agent whose sensor feed has stopped.

An agent can stay registered while its sensor data stops arriving. FEAGI exposes no
per-agent sensory frame counter on the paths used here, so attribution uses the agent's
device registration (which unit owns which IPU area) plus two sensor-snapshot reads taken
a short window apart. An agent that declares sensory capability is flagged ``feed_stalled``
when none of its IPU areas carries data in either read; ``feed_partial`` (a warning) lists the
silent IPUs of an agent whose other IPUs are live.

The one home of this logic: ``get_feagi_link_health`` and ``check_live_state_drift`` both
call :func:`gather_feed_stalled`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from feagi_mcp.registration_units import RegistrationError, match_unit

FEED_WINDOW_S = 2.0


def snapshot_active_areas(snapshot: Any) -> set[str]:
    """Cortical ids that carried data (samples or a neuron count) in one snapshot."""
    active: set[str] = set()
    areas = snapshot.get("areas") if isinstance(snapshot, dict) else None
    for area in areas if isinstance(areas, list) else []:
        if not isinstance(area, dict) or not isinstance(area.get("cortical_id"), str):
            continue
        samples = area.get("samples")
        count = area.get("neuron_count")
        if (isinstance(samples, list) and samples) or (
            isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0
        ):
            active.add(area["cortical_id"])
    return active


def _is_sensory(agent_data: dict[str, Any]) -> bool:
    caps = agent_data.get("capabilities")
    return isinstance(caps, dict) and bool(caps.get("sensory") or caps.get("send_sensor_data"))


def feed_stalled_findings(
    capabilities: dict[str, Any],
    live_areas: dict[str, dict[str, Any]],
    snapshots: list[Any],
) -> list[dict[str, Any]]:
    """``feed_stalled`` findings from already-fetched payloads (pure).

    ``capabilities`` is the ``/v1/agent/capabilities/all`` map with device registrations;
    ``snapshots`` are sensor snapshots read a short window apart.
    """
    from feagi_mcp.feagi_client import collect_device_registrations

    active: set[str] = set()
    for snap in snapshots:
        active |= snapshot_active_areas(snap)
    ipu_areas = [
        {**rec, "cortical_id": cid}
        for cid, rec in live_areas.items()
        if isinstance(rec, dict) and str(rec.get("cortical_group", "")).upper() == "IPU"
    ]
    findings: list[dict[str, Any]] = []
    for agent_id, agent_data in capabilities.items():
        if not isinstance(agent_data, dict) or not _is_sensory(agent_data):
            continue
        registrations = collect_device_registrations(agent_data)
        owned: list[dict[str, Any]] = []
        for area in ipu_areas:
            try:
                match_unit(registrations, area, coding_only=True)
            except RegistrationError:
                continue
            owned.append(area)
        if not owned:
            continue
        silent = [a for a in owned if a["cortical_id"] not in active]
        if not silent:
            continue
        if len(silent) < len(owned):
            findings.append(
                {
                    "check": "feed_partial",
                    "severity": "warning",
                    "agent_id": agent_id,
                    "agent_name": agent_data.get("agent_name"),
                    "silent_ipu_areas": [
                        {"cortical_id": a["cortical_id"], "cortical_name": a.get("cortical_name")}
                        for a in silent
                    ],
                    "live_ipu_count": len(owned) - len(silent),
                    "window_s": FEED_WINDOW_S,
                    "message": "Some IPU areas of this sensory agent carried no data in two "
                    "snapshot reads while its other IPUs did. A change-only IPU can be quiet "
                    "legitimately; otherwise its feed may have stopped.",
                    "restore": None,
                }
            )
            continue
        findings.append(
            {
                "check": "feed_stalled",
                "agent_id": agent_id,
                "agent_name": agent_data.get("agent_name"),
                "silent_ipu_areas": [
                    {"cortical_id": a["cortical_id"], "cortical_name": a.get("cortical_name")}
                    for a in owned
                ],
                "window_s": FEED_WINDOW_S,
                "message": "The agent is registered and declares sensory capability, but none "
                "of its IPU areas carried sensor data in two snapshot reads.",
                "restore": {
                    "tool": None,
                    "note": "Check the controller's sensor loop or restart it from Studio.",
                },
            }
        )
    return findings


async def gather_feed_stalled(
    client: Any,
    *,
    capabilities: dict[str, Any] | None = None,
    live_areas: dict[str, dict[str, Any]] | None = None,
    first_snapshot: dict[str, Any] | None = None,
    window_s: float = FEED_WINDOW_S,
) -> dict[str, Any]:
    """Fetch what is missing, read the snapshot twice ``window_s`` apart, return findings."""
    caps_task = (
        asyncio.sleep(0, result=capabilities)
        if capabilities is not None
        else client.list_agent_capabilities_all(include_device_registrations=True)
    )
    areas_task = (
        asyncio.sleep(0, result=live_areas)
        if live_areas is not None
        else client.list_cortical_areas_detailed()
    )
    first_task = (
        asyncio.sleep(0, result=first_snapshot)
        if first_snapshot is not None
        else client.get_sensor_snapshot_last(summary_only=False)
    )
    caps, areas, first = await asyncio.gather(caps_task, areas_task, first_task)
    if not isinstance(caps, dict) or caps.get("error") or not isinstance(areas, dict):
        return {"feed_stalled": [], "error": {"capabilities": caps, "areas": areas}}
    if not any(_is_sensory(a) for a in caps.values() if isinstance(a, dict)):
        return {"feed_stalled": []}
    await asyncio.sleep(window_s)
    second = await client.get_sensor_snapshot_last(summary_only=False)
    if any(isinstance(s, dict) and s.get("error") for s in (first, second)):
        return {"feed_stalled": [], "error": {"sensor_snapshot": [first, second]}}
    return {"feed_stalled": feed_stalled_findings(caps, areas, [first, second])}
