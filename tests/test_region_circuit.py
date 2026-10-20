"""Tests for the region-scoped circuit view (``get_region_circuit``)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.region_circuit import (
    area_role,
    collect_member_areas,
    mapping_edges,
    summarize_region_circuit,
)


def _cid(raw: bytes) -> str:
    """Base64 cortical id from 8 raw bytes."""
    assert len(raw) == 8
    return base64.b64encode(raw).decode("ascii")


IPU = _cid(b"isvi\x00\x00\x00\x00")
OPU = _cid(b"omot\x00\x00\x00\x00")
HIDDEN = _cid(b"chidden0")
NESTED = _cid(b"cnested0")
LONELY = _cid(b"clonely0")
OUTSIDE_SRC = _cid(b"coutsrc0")
OUTSIDE_DST = _cid(b"coutdst0")

RULE = [{"morphology_id": "projector", "postSynapticCurrent_multiplier": 1.0}]


def _regions() -> dict:
    return {
        "root": {"title": "Root", "areas": [OUTSIDE_SRC, OUTSIDE_DST], "regions": ["circ"]},
        "circ": {
            "title": "Detector",
            "parent_region_id": "root",
            "areas": [IPU, HIDDEN, OPU, LONELY],
            "regions": ["child"],
            "designated_inputs": [IPU],
            "designated_outputs": [],
        },
        "child": {"title": "Inner", "parent_region_id": "circ", "areas": [NESTED], "regions": []},
    }


def _cortical_map() -> dict:
    return {
        OUTSIDE_SRC: {HIDDEN: RULE},
        IPU: {HIDDEN: RULE},
        HIDDEN: {NESTED: RULE, OPU: RULE + RULE},
        NESTED: {OUTSIDE_DST: RULE},
        OPU: {HIDDEN: []},
    }


def _names() -> dict:
    return {IPU: "Vision", OPU: "Motor", HIDDEN: "Hidden", NESTED: "Nested"}


class TestPureHelpers:
    def test_area_role_from_byte_zero(self):
        assert area_role(IPU) == "sensory"
        assert area_role(OPU) == "motor"
        assert area_role(HIDDEN) == "internal"
        assert area_role("not-an-id") == "undecodable"

    def test_members_are_recursive_unless_disabled(self):
        members, visited = collect_member_areas(_regions(), "circ", True)
        assert members == sorted([IPU, HIDDEN, OPU, LONELY, NESTED])
        assert visited == ["child", "circ"]
        members, visited = collect_member_areas(_regions(), "circ", False)
        assert NESTED not in members
        assert visited == ["circ"]

    def test_region_cycles_terminate(self):
        regions = {"a": {"areas": ["x"], "regions": ["b"]}, "b": {"areas": ["y"], "regions": ["a"]}}
        members, visited = collect_member_areas(regions, "a", True)
        assert members == ["x", "y"]
        assert visited == ["a", "b"]

    def test_unknown_child_region_raises(self):
        regions = {"a": {"areas": [], "regions": ["ghost"]}}
        with pytest.raises(KeyError):
            collect_member_areas(regions, "a", True)

    def test_edges_are_distinct_and_skip_empty_rule_lists(self):
        edges = mapping_edges(_cortical_map())
        assert (HIDDEN, OPU) in edges
        assert edges.count((HIDDEN, OPU)) == 1
        assert (OPU, HIDDEN) not in edges
        assert edges == sorted(edges)


class TestSummarize:
    def test_boundary_edges_and_isolation(self):
        out = summarize_region_circuit(_regions(), _cortical_map(), _names(), " circ ")
        assert out["region_id"] == "circ"
        assert out["title"] == "Detector"
        assert out["member_count"] == 5
        assert out["edges"]["incoming"] == [[OUTSIDE_SRC, HIDDEN]]
        assert out["edges"]["outgoing"] == [[NESTED, OUTSIDE_DST]]
        assert sorted(out["edges"]["internal"]) == sorted(
            [[IPU, HIDDEN], [HIDDEN, NESTED], [HIDDEN, OPU]]
        )
        assert out["boundary"]["input_area_ids"] == sorted([IPU, HIDDEN])
        assert out["boundary"]["output_area_ids"] == sorted([OPU, NESTED])
        assert out["isolated_area_ids"] == [LONELY]
        assert out["designated"] == {"inputs": [IPU], "outputs": []}
        names = {m["cortical_id"]: (m["name"], m["role"]) for m in out["members"]}
        assert names[IPU] == ("Vision", "sensory")
        assert names[LONELY] == ("", "internal")

    def test_without_children_nested_area_becomes_outside(self):
        out = summarize_region_circuit(
            _regions(), _cortical_map(), _names(), "circ", include_child_regions=False
        )
        assert [HIDDEN, NESTED] in out["edges"]["outgoing"]
        assert HIDDEN in out["boundary"]["output_area_ids"]
        assert out["regions_included"] == ["circ"]

    def test_unknown_region_is_reported(self):
        out = summarize_region_circuit(_regions(), {}, {}, "nope")
        assert out["error"] == "unknown_region"
        assert out["region_id"] == "nope"

    def test_response_omits_mapping_rules(self):
        out = summarize_region_circuit(_regions(), _cortical_map(), _names(), "circ")
        assert "projector" not in repr(out)


def _response(payload: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.text = "boom"
    return response


@pytest.fixture
def client() -> FeagiClient:
    """FeagiClient whose HTTP transport (outside the unit under test) is mocked."""
    instance = FeagiClient()
    instance._client = AsyncMock()
    return instance


class TestClientIntegration:
    @pytest.mark.asyncio
    async def test_fetches_public_endpoints_and_summarizes(self, client):
        payloads = {
            "/v1/region/regions_members": _regions(),
            "/v1/cortical_area/cortical_map_detailed": _cortical_map(),
            "/v1/cortical_area/cortical_id_name_mapping": _names(),
        }

        async def get(url, **_kwargs):
            for path, payload in payloads.items():
                if url.endswith(path):
                    return _response(payload)
            raise AssertionError(f"unexpected url {url}")

        client._client.get.side_effect = get
        out = await client.get_region_circuit("circ")
        assert out["member_count"] == 5
        assert out["boundary"]["output_area_ids"] == sorted([OPU, NESTED])
        called = sorted(
            call.args[0].split("/v1/", 1)[1] for call in client._client.get.call_args_list
        )
        assert called == [
            "cortical_area/cortical_id_name_mapping",
            "cortical_area/cortical_map_detailed",
            "region/regions_members",
        ]

    @pytest.mark.asyncio
    async def test_upstream_failure_is_surfaced(self, client):
        async def get(url, **_kwargs):
            if url.endswith("cortical_map_detailed"):
                return _response({}, status=503)
            return _response(_regions())

        client._client.get.side_effect = get
        out = await client.get_region_circuit("circ")
        assert out["error"] == "cortical_map_detailed failed"
        assert out["detail"]["error"] == "HTTP 503"
