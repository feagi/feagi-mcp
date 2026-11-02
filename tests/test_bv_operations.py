"""Tests for Brain Visualizer operation registry and path resolution."""

import json

import httpx
import pytest

from feagi_mcp.bv_operations import (
    BV_OPERATION_BY_ID,
    BV_OPERATIONS,
    list_operation_summaries,
    resolve_path,
)
from feagi_mcp.feagi_client import FeagiClient

REGION_BODY_OPS = (
    "put_region_region",
    "delete_region_region",
    "delete_region_region_and_members",
)


def _client_with_transport(requests: list[httpx.Request]) -> FeagiClient:
    """FeagiClient whose HTTP transport records requests and returns an empty JSON object."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = FeagiClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def test_all_operation_ids_unique():
    ids = [op.operation_id for op in BV_OPERATIONS]
    assert len(ids) == len(set(ids))


def test_resolve_path_with_region_id():
    p = resolve_path("/v1/region/region/{region_id}", {"region_id": "root"})
    assert p == "/v1/region/region/root"


def test_resolve_path_missing_placeholder_raises():
    with pytest.raises(ValueError):
        resolve_path("/v1/region/region/{region_id}", None)


def test_list_operation_summaries_shape():
    rows = list_operation_summaries()
    assert len(rows) == len(BV_OPERATIONS)
    assert all("operation_id" in r and "method" in r and "path" in r for r in rows)


def test_brain_visualizer_operation_unknown():
    assert "nonexistent" not in BV_OPERATION_BY_ID


def test_classifier_and_modulator_routes_match_brain_visualizer():
    """Every live classifier and modulator path BV calls is in the MCP registry."""
    import re
    from pathlib import Path

    address_list = (
        Path(__file__).resolve().parents[2]
        / "brain-visualizer/godot_source/addons/FeagiCoreIntegration/FeagiCore/Networking/API"
        / "FEAGIHTTPAddressList.gd"
    )
    if not address_list.exists():
        pytest.skip("brain-visualizer checkout not present")
    bv = set()
    for method, path in re.findall(
        r"var (GET|POST|PUT|DELETE)_\w+: StringName = "
        r'"(/v1/(?:modulator/|cortical_area/classifier)[^"]*)"',
        address_list.read_text("utf-8"),
    ):
        if path.endswith("/field"):  # retired: the server rejects field attach/detach
            continue
        bv.add((method, path))
    mcp = {(op.method, op.path_template) for op in BV_OPERATIONS}
    assert bv, "no classifier/modulator paths parsed from FEAGIHTTPAddressList.gd"
    assert bv <= mcp, f"missing from bv_operations: {sorted(bv - mcp)}"


def test_region_ops_declare_region_id_body():
    for op_id in REGION_BODY_OPS:
        assert BV_OPERATION_BY_ID[op_id].required_body_fields == ("region_id",)


def test_only_verified_ops_declare_required_body_fields():
    declared = {op.operation_id for op in BV_OPERATIONS if op.required_body_fields}
    assert declared == set(REGION_BODY_OPS)


@pytest.mark.parametrize("op_id", REGION_BODY_OPS)
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"query": {"region_id": "x"}},
        {"json_body": {}},
        {"json_body": ["x"]},
    ],
)
async def test_missing_required_body_returns_invalid_body_without_http(op_id, kwargs):
    requests: list[httpx.Request] = []
    client = _client_with_transport(requests)
    try:
        result = await client.brain_visualizer_operation(op_id, **kwargs)
    finally:
        await client.close()
    assert result["error"] == "invalid_body"
    assert result["operation_id"] == op_id
    assert result["required_body_fields"] == ["region_id"]
    assert result["message"] == f"{op_id} needs a JSON body with: region_id"
    assert requests == []


async def test_delete_region_sends_json_body():
    requests: list[httpx.Request] = []
    client = _client_with_transport(requests)
    try:
        result = await client.brain_visualizer_operation(
            "delete_region_region", json_body={"region_id": "x"}
        )
    finally:
        await client.close()
    assert result == {}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "DELETE"
    assert req.url.path == "/v1/region/region"
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {"region_id": "x"}


def test_list_operation_summaries_exposes_required_body_fields():
    rows = {r["operation_id"]: r for r in list_operation_summaries()}
    for op_id in REGION_BODY_OPS:
        assert rows[op_id]["required_body_fields"] == ["region_id"]
    assert "required_body_fields" not in rows["get_genome_file_name"]
