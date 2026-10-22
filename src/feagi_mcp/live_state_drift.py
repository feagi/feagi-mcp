"""Compare the live brain with its genome and the controller registration.

Live state silently reverts: an agent re-registration re-applies the controller's
IPU/OPU dimensions, a genome reload resets the burst rate, a controller restart
registers under a new agent id. Each check here names the subject, the two values
and the tool call that restores the live value, so a session can re-apply it
deliberately instead of discovering the revert through a silent circuit.

Pure functions take already-fetched payloads; :func:`gather_live_state_drift`
fetches them through a ``FeagiClient``.
"""

from __future__ import annotations

import asyncio
from typing import Any

BURST_RATE_TOLERANCE = 0.01  # relative

# Genome blueprint keys look like ``_____10c-<cortical_id>-cx-___bbx-i``.
_DIM_FIELDS = ("___bbx", "___bby", "___bbz")


def blueprint_dimensions(blueprint: dict[str, Any]) -> dict[str, list[int | None]]:
    """``{cortical_id: [x, y, z]}`` from the flat genome blueprint."""
    dims: dict[str, list[int | None]] = {}
    for key, value in blueprint.items():
        parts = key.split("-")
        if len(parts) < 5 or parts[2] != "cx":
            continue
        field = parts[3]
        if field not in _DIM_FIELDS:
            continue
        axis = _DIM_FIELDS.index(field)
        entry = dims.setdefault(parts[1], [None, None, None])
        entry[axis] = int(value) if isinstance(value, (int, float)) else None
    return dims


def _dims(record: dict[str, Any]) -> list[int] | None:
    raw = record.get("cortical_dimensions")
    if isinstance(raw, list) and len(raw) == 3:
        try:
            return [int(v) for v in raw]
        except (TypeError, ValueError):
            return None
    return None


def dimension_findings(
    live_areas: dict[str, dict[str, Any]], blueprint: dict[str, Any]
) -> list[dict[str, Any]]:
    """Areas whose live dimensions differ from the genome blueprint."""
    expected = blueprint_dimensions(blueprint)
    findings: list[dict[str, Any]] = []
    for cortical_id, record in live_areas.items():
        live = _dims(record)
        genome = expected.get(cortical_id)
        if live is None or genome is None or None in genome:
            continue
        if live != genome:
            findings.append(
                {
                    "check": "cortical_dimensions",
                    "cortical_id": cortical_id,
                    "cortical_name": record.get("cortical_name"),
                    "live": live,
                    "genome": genome,
                    "restore": {
                        "tool": "update_cortical_area",
                        "args": {
                            "cortical_id": cortical_id,
                            "updates": {"cortical_dimensions": live},
                        },
                        "note": "re-applies the live value to the genome blueprint",
                    },
                }
            )
    return findings


def sensor_columns(sensor_snapshot: dict[str, Any]) -> dict[str, int]:
    """``{cortical_id: columns}`` present in the last sensor snapshot (max x + 1)."""
    areas = sensor_snapshot.get("areas")
    columns: dict[str, int] = {}
    if not isinstance(areas, list):
        return columns
    for area in areas:
        if not isinstance(area, dict):
            continue
        cortical_id = area.get("cortical_id")
        samples = area.get("samples")
        if not isinstance(cortical_id, str) or not isinstance(samples, list):
            continue
        xs: list[int] = []
        for sample in samples:
            x = sample.get("x") if isinstance(sample, dict) else None
            if isinstance(x, int) and not isinstance(x, bool):
                xs.append(x)
        if xs:
            columns[cortical_id] = max(xs) + 1
    return columns


def ipu_width_findings(
    live_areas: dict[str, dict[str, Any]], sensor_snapshot: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """IPUs whose last snapshot used more columns than the area is wide."""
    columns = sensor_columns(sensor_snapshot)
    findings: list[dict[str, Any]] = []
    table: dict[str, dict[str, int]] = {}
    for cortical_id, present in columns.items():
        record = live_areas.get(cortical_id)
        live = _dims(record) if isinstance(record, dict) else None
        if live is None:
            continue
        table[cortical_id] = {"width": live[0], "columns_in_snapshot": present}
        if present > live[0]:
            findings.append(
                {
                    "check": "ipu_width",
                    "cortical_id": cortical_id,
                    "cortical_name": record.get("cortical_name") if record else None,
                    "live": live[0],
                    "columns_in_snapshot": present,
                    "restore": {
                        "tool": "update_cortical_area",
                        "args": {
                            "cortical_id": cortical_id,
                            "updates": {"cortical_dimensions": [present, live[1], live[2]]},
                        },
                    },
                }
            )
    return findings, table


def burst_rate_finding(
    burst_config: dict[str, Any], simulation_timestep: Any
) -> dict[str, Any] | None:
    """Burst frequency that disagrees with the genome's simulation timestep."""
    rate = burst_config.get("burst_frequency_hz")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return None
    if not isinstance(simulation_timestep, (int, float)) or simulation_timestep <= 0:
        return None
    expected = 1.0 / float(simulation_timestep)
    if abs(float(rate) - expected) <= BURST_RATE_TOLERANCE * expected:
        return None
    return {
        "check": "burst_frequency",
        "live_hz": float(rate),
        "genome_hz": round(expected, 4),
        "simulation_timestep_s": float(simulation_timestep),
        "restore": {
            "tool": "set_burst_engine_frequency",
            "args": {"frequency_hz": round(expected, 4)},
        },
    }


def agent_finding(
    descriptor: dict[str, Any] | None, registered_agent_ids: list[str]
) -> dict[str, Any] | None:
    """Controller descriptor whose agent id is not registered with FEAGI."""
    if not descriptor or not descriptor.get("found"):
        return {
            "check": "agent_registration",
            "controller_id": (descriptor or {}).get("controller_id"),
            "descriptor_agent_id": None,
            "registered_agent_ids": registered_agent_ids,
            "message": "No controller introspection descriptor found.",
            "restore": None,
        }
    agent_id = descriptor.get("agent_id")
    if not agent_id:
        return {
            "check": "agent_registration",
            "controller_id": descriptor.get("controller_id"),
            "descriptor_agent_id": None,
            "registered_agent_ids": registered_agent_ids,
            "message": "Descriptor carries no agent_id; cannot verify registration.",
            "restore": None,
        }
    if agent_id in registered_agent_ids:
        return None
    return {
        "check": "agent_registration",
        "controller_id": descriptor.get("controller_id"),
        "descriptor_agent_id": agent_id,
        "registered_agent_ids": registered_agent_ids,
        "message": "The controller's agent id is not registered; IPU/OPU streams may be stale.",
        "restore": {
            "tool": None,
            "note": "Restart the controller (re-register the agent) from Studio; "
            "then re-run check_live_state_drift().",
        },
    }


def compare_live_state(
    *,
    live_areas: dict[str, dict[str, Any]],
    blueprint: dict[str, Any],
    burst_config: dict[str, Any],
    simulation_timestep: Any,
    descriptor: dict[str, Any] | None,
    registered_agent_ids: list[str],
    sensor_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """All drift findings from already-fetched payloads."""
    expected_dims = blueprint_dimensions(blueprint)
    findings = dimension_findings(live_areas, blueprint)
    width_findings, ipu_table = ipu_width_findings(live_areas, sensor_snapshot)
    findings.extend(width_findings)
    rate = burst_rate_finding(burst_config, simulation_timestep)
    if rate:
        findings.append(rate)
    agent = agent_finding(descriptor, registered_agent_ids)
    if agent:
        findings.append(agent)
    return {
        "finding_count": len(findings),
        "findings": findings,
        "checked": {
            "areas_compared": sum(
                1 for cid, rec in live_areas.items() if _dims(rec) and cid in expected_dims
            ),
            "ipu_columns": ipu_table,
            "burst_frequency_hz": burst_config.get("burst_frequency_hz"),
            "simulation_timestep_s": simulation_timestep,
            "registered_agent_count": len(registered_agent_ids),
        },
    }


async def gather_live_state_drift(client: Any, controller_id: str = "mujoco") -> dict[str, Any]:
    """Fetch genome, live areas, burst config, agents, descriptor and snapshot, then compare."""
    genome, areas, burst_config, health, agents, descriptor, snapshot = await asyncio.gather(
        client.download_genome(),
        client.list_cortical_areas_detailed(),
        client.get_burst_engine_config(),
        client.health_check(),
        client.get_registered_agents(),
        client.embodiment_discover_introspection_endpoint(controller_id),
        client.get_sensor_snapshot_last(summary_only=False),
    )
    errors: dict[str, Any] = {}
    for name, payload in (
        ("genome", genome),
        ("live_areas", areas),
        ("burst_config", burst_config),
        ("health", health),
        ("agents", agents),
        ("sensor_snapshot", snapshot),
    ):
        if not isinstance(payload, dict) or payload.get("error"):
            errors[name] = payload
    blueprint = genome.get("blueprint") if isinstance(genome, dict) else None
    live_areas = areas if isinstance(areas, dict) and "error" not in areas else {}
    agent_ids = agents.get("agent_ids") if isinstance(agents, dict) else None
    result = compare_live_state(
        live_areas=live_areas,
        blueprint=blueprint if isinstance(blueprint, dict) else {},
        burst_config=burst_config if isinstance(burst_config, dict) else {},
        simulation_timestep=health.get("simulation_timestep") if isinstance(health, dict) else None,
        descriptor=descriptor if isinstance(descriptor, dict) else None,
        registered_agent_ids=[a for a in (agent_ids or []) if isinstance(a, str)],
        sensor_snapshot=snapshot if isinstance(snapshot, dict) else {},
    )
    if errors:
        result["fetch_errors"] = errors
    return result
