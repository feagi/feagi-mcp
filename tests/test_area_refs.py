"""Area name-or-id resolution at the tool layer, and the per-area cortical map filter."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from feagi_mcp.area_refs import AREA_ARGS, resolve_area_arguments
from feagi_mcp.compact_views import filter_map_to_area


def _cid(n: int) -> str:
    return base64.b64encode(bytes([n]) * 8).decode()


A, B = _cid(1), _cid(2)
NAMES = {A: "Alpha", B: "Beta"}


async def _names() -> dict[str, Any]:
    return dict(NAMES)


def _run(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(resolve_area_arguments(tool, args, _names))


SCALAR_CASES = [
    ("get_cortical_synapse_counts", "area_id"),
    ("get_cortical_map_detailed", "cortical_id"),
    ("inspect_cortical_area", "cortical_id"),
    ("monitor_activity", "area_id"),
    ("stimulate_area", "area_id"),
    ("hold_stimulus", "area"),
    ("get_cortical_mapping", "src_area"),
    ("update_cortical_mapping", "dst_area"),
    ("probe_area_response", "observe_area"),
    ("build_reflex_mapping", "src_area_id"),
    ("list_area_synapses", "cortical_area_id"),
]


@pytest.mark.parametrize(("tool", "key"), SCALAR_CASES)
def test_scalar_name_and_id(tool: str, key: str) -> None:
    assert _run(tool, {key: "Alpha"})[key] == A
    assert _run(tool, {key: B})[key] == B
    with pytest.raises(ToolError, match=r"Alpha \("):
        _run(tool, {key: "Alpah"})
    with pytest.raises(ToolError, match="unknown cortical area"):
        _run(tool, {key: "zzzz"})


@pytest.mark.parametrize(
    ("tool", "key"),
    [
        ("inspect_cortical_areas_batch", "cortical_ids"),
        ("reset_cortical_neural_state", "cortical_ids"),
        ("monitor_activity_batch", "area_ids"),
        ("run_stimulus_protocol", "record_areas"),
    ],
)
def test_list_args(tool: str, key: str) -> None:
    assert _run(tool, {key: ["Alpha", B]})[key] == [A, B]


def test_nested_stimuli() -> None:
    sched = [{"burst_offset": 0, "stimuli": [{"area_id": "Beta", "coordinates": [[0, 0, 0]]}]}]
    assert _run("schedule_stimulus", {"entries": sched})["entries"][0]["stimuli"][0]["area_id"] == B
    steps = [{"bursts": 1, "stimuli": [{"area_id": "Alpha", "coordinates": [[0, 0, 0]]}]}]
    out = _run("run_stimulus_protocol", {"steps": steps, "record_areas": ["Alpha"]})
    assert out["steps"][0]["stimuli"][0]["area_id"] == A


def test_ambiguous_and_unreadable_and_untouched() -> None:
    async def dup() -> dict[str, Any]:
        return {A: "Same", B: "Same"}

    with pytest.raises(ToolError, match="matches 2 areas"):
        asyncio.run(resolve_area_arguments("monitor_activity", {"area_id": "Same"}, dup))

    async def down() -> dict[str, Any]:
        return {"error": "down"}

    args = {"area_id": "Alpha"}
    assert asyncio.run(resolve_area_arguments("monitor_activity", args, down)) == args
    assert _run("health_check", {"x": "Alpha"}) == {"x": "Alpha"}
    assert _run("get_cortical_map_detailed", {"cortical_id": None})["cortical_id"] is None


def test_no_lookup_when_all_ids() -> None:
    async def boom() -> dict[str, Any]:
        raise AssertionError("name list must not be fetched")

    args = {"src_area": A, "dst_area": B}
    assert asyncio.run(resolve_area_arguments("get_cortical_mapping", args, boom)) == args


def test_table_covers_tools_and_tools_exist() -> None:
    from feagi_mcp import server

    registered = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert set(AREA_ARGS) <= registered


def test_map_filter_keeps_source_or_destination() -> None:
    cmap = {A: {B: [1], "c": [2]}, B: {"c": [3]}, "c": {A: [4], "d": [5]}}
    assert filter_map_to_area(cmap, A) == {A: {B: [1], "c": [2]}, "c": {A: [4]}}
    assert filter_map_to_area(cmap, "d") == {"c": {"d": [5]}}


def test_client_map_detailed_filters_by_area() -> None:
    from feagi_mcp.feagi_client import FeagiClient

    class Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {A: {B: [1]}, B: {"c": [2]}, "c": {"d": [3]}}

    class Http:
        async def get(self, _url: str) -> Resp:
            return Resp()

    client = FeagiClient(host="localhost", port=1, timeout=1)
    client._client = Http()  # type: ignore[assignment]
    full = asyncio.run(client.get_cortical_map_detailed())
    assert len(full) == 3
    assert asyncio.run(client.get_cortical_map_detailed(cortical_id=B)) == {
        A: {B: [1]},
        B: {"c": [2]},
    }
