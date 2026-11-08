"""Neutral fixtures for I/O channel tests: registrations, area records and a fake FEAGI HTTP.

Only the HTTP transport is faked (``httpx.MockTransport``); everything above it is the real
client. Payload shapes follow recorded FEAGI responses (area records from
``/v1/connectome/cortical_areas/list/detailed``, registrations from
``/v1/agent/capabilities/all``, raw voxel edges from ``/v1/cortical_area/voxel_neurons``).
Names and numbers are neutral.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.percentage_coding import OUTPUT_SECTION, UnitCoding

OPU_ID = "AAAAAAAAAAA="
OTHER_ID = "BBBBBBBBBBB="
SRC_A = "SRCA0000001="
SRC_B = "SRCB0000001="
AGENT_A = "agent-a"
AGENT_B = "agent-b"
DEPTH = 101
RANGE = {"value_at_0": -90.0, "value_at_1": 90.0, "unit": "deg"}

ABSOLUTE_LINEAR = {
    "frame_change_handling": "Absolute",
    "percentage_neuron_positioning": "Linear",
}


def unit_definition(
    *,
    index: int = 0,
    channels: int = 3,
    ranges: dict[int, dict[str, Any]] | None = None,
    flags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """A registration unit definition with ``channels`` device-grouping entries."""
    grouping = []
    for channel in range(channels):
        entry: dict[str, Any] = {"friendly_name": f"joint_{channel}"}
        if ranges and channel in ranges:
            entry["physical_range"] = ranges[channel]
        grouping.append(entry)
    return {
        "cortical_unit_index": index,
        "io_configuration_flags": flags or ABSOLUTE_LINEAR,
        "device_grouping": grouping,
    }


def registration(
    unit_key: str = "PositionalServo", **kwargs: Any
) -> dict[str, dict[str, list[list[Any]]]]:
    """``device_registrations`` with one motor unit, as ``[definition, properties]``."""
    return {OUTPUT_SECTION: {unit_key: [[unit_definition(**kwargs), {}]]}}


def opu_area(**over: Any) -> dict[str, Any]:
    """A 3-channel absolute OPU area record (one z column per channel)."""
    area = {
        "cortical_id": OPU_ID,
        "cortical_name": "servo-0",
        "cortical_group": "OPU",
        "cortical_subtype": "opse",
        "coding_behavior": "Absolute",
        "cortical_dimensions": [3, 1, DEPTH],
        "cortical_dimensions_per_device": [1, 1, DEPTH],
        "dev_count": 3,
        "unit_id": 0,
        "subunit_id": 0,
    }
    return {**area, **over}


def servo_coding(depth: int = DEPTH, *, unit_key: str = "PositionalServo") -> UnitCoding:
    """The absolute linear servo coding at ``depth`` (the binding decides its variant)."""
    return UnitCoding.build(OUTPUT_SECTION, unit_key, unit_definition(), 0, depth)


class FakeFeagi:
    """A scripted FEAGI /v1 surface. Set the attributes, then use :meth:`client`."""

    def __init__(self) -> None:
        self.areas: list[dict[str, Any]] = [opu_area()]
        self.agents: dict[str, dict[str, Any]] = {}
        self.voxels: dict[tuple[str, int, int, int], list[dict[str, Any]]] = {}
        self.page_size = 1000
        self.mappings: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.ledger_windows: dict[str, int] = {}
        self.ledger_frames: dict[str, dict[int, list[list[int]]]] = {}
        self.current_burst = 100
        self.stimulations: list[dict[str, Any]] = []
        self.fail_voxel: set[tuple[int, int, int]] = set()
        self.seen: list[str] = []
        self.voxel_calls = 0
        self.ledger_reads: list[tuple[list[str], int]] = []

    def add_agent(
        self,
        agent_id: str,
        device_registrations: dict[str, Any],
        *,
        motor: bool = True,
        sensory: bool = False,
    ) -> None:
        """Register an agent with its device registrations (recorded sibling shape)."""
        self.agents[agent_id] = {
            "agent_name": agent_id,
            "capabilities": {"motor": motor, "sensory": sensory},
            "device_registrations": device_registrations,
        }

    def add_incoming(
        self,
        area_id: str,
        voxel: tuple[int, int, int],
        source_id: str,
        source_name: str,
        n: int = 1,
    ) -> None:
        """Give a voxel ``n`` incoming synapses from ``source_id``."""
        rows = self.voxels.setdefault((area_id, *voxel), [])
        for i in range(n):
            rows.append(
                {
                    "source_cortical_id": source_id,
                    "source_cortical_name": source_name,
                    "source_x": 0,
                    "source_y": 0,
                    "source_z": i,
                    "postsynaptic_potential": 1.0,
                    "weight": 1.0,
                }
            )

    def _voxel_response(self, request: httpx.Request) -> httpx.Response:
        self.voxel_calls += 1
        q = request.url.params
        key = (q["cortical_id"], int(q["x"]), int(q["y"]), int(q["z"]))
        if key[1:] in self.fail_voxel:
            return httpx.Response(500, text="voxel boom")
        page = int(q.get("synapse_page", "0"))
        rows = self.voxels.get(key, [])
        chunk = rows[page * self.page_size : (page + 1) * self.page_size]
        more = len(rows) > (page + 1) * self.page_size
        neuron = {
            "neuron_id": 1,
            "incoming_synapse_count": len(rows),
            "incoming_synapses": chunk,
            "incoming_synapses_has_more": more,
        }
        return httpx.Response(200, json={"cortical_id": key[0], "neurons": [neuron]})

    def _fire_history(self, request: httpx.Request) -> httpx.Response:
        q = request.url.params
        ids = q["areas"].split(",")
        bursts = int(q["bursts"])
        self.ledger_reads.append((ids, bursts))
        areas: dict[str, Any] = {}
        for area_id in ids:
            frames = self.ledger_frames.get(area_id, {})
            lo = self.current_burst - bursts + 1
            areas[area_id] = {
                "name": area_id,
                "window": bursts,
                "frames": [
                    {"burst": b, "voxels": frames.get(b, []), "memory_neuron_ids": []}
                    for b in range(lo, self.current_burst + 1)
                ],
            }
        return httpx.Response(200, json={"current_burst": self.current_burst, "areas": areas})

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Route one request to the scripted response."""
        path = request.url.path
        self.seen.append(path)
        if path == "/v1/cortical_area/cortical_id_name_mapping":
            return httpx.Response(
                200, json={a["cortical_id"]: a["cortical_name"] for a in self.areas}
            )
        if path == "/v1/connectome/cortical_areas/list/detailed":
            return httpx.Response(200, json={a["cortical_id"]: a for a in self.areas})
        if path == "/v1/agent/list":
            return httpx.Response(200, json=list(self.agents))
        if path == "/v1/agent/capabilities/all":
            return httpx.Response(200, json=self.agents)
        if path == "/v1/cortical_area/voxel_neurons":
            return self._voxel_response(request)
        if path == "/v1/cortical_area/cortical_map_detailed":
            return httpx.Response(200, json=self.mappings)
        if path == "/v1/burst_engine/fire_ledger/areas_window_config":
            return httpx.Response(
                200, json={"default_window_size": 20, "areas": self.ledger_windows}
            )
        if path == "/v1/burst_engine/fire_history":
            return self._fire_history(request)
        if path == "/v1/agent/manual_stimulation":
            self.stimulations.append(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "neuron_count": 1})
        return httpx.Response(404, text=f"unexpected {path}")

    def client(self) -> FeagiClient:
        """A real client whose transport is this fake."""
        client = FeagiClient()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return client
