"""Base64 cortical ids contain ``/`` and ``=``; path-embedded ids must be percent-encoded."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.bv_operations import resolve_path
from feagi_mcp.feagi_client import FeagiClient, _path_id

SLASH_ID = "Y01vdG9yX/A="
ENCODED = "Y01vdG9yX%2FA%3D"


def _ok(payload: Any) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.text = ""
    return response


@pytest.fixture
def client() -> FeagiClient:
    c = FeagiClient()
    c._client = AsyncMock()
    return c


def test_path_id_encodes_slash_and_equals() -> None:
    assert _path_id(SLASH_ID) == ENCODED
    assert _path_id("plain") == "plain"


def test_bv_resolve_path_encodes_params() -> None:
    assert resolve_path("/v1/agent/{agent_id}/x", {"agent_id": "a/b=c"}) == "/v1/agent/a%2Fb%3Dc/x"


async def test_list_area_synapses_incoming_encodes_id(client: FeagiClient) -> None:
    client._client.get.return_value = _ok(
        [{"source_neuron_id": 1, "target_neuron_id": 2, "weight": 5.0}]
    )
    result = await client.list_area_synapses(SLASH_ID, direction="incoming", view="summary")
    url = client._client.get.await_args.args[0]
    assert url.endswith(f"/v1/connectome/{ENCODED}/synapses/incoming")
    assert "/" + SLASH_ID not in url
    assert result["synapse_count"] == 1


async def test_list_area_synapses_both_encodes_id(client: FeagiClient) -> None:
    client._client.get.return_value = _ok([])
    await client.list_area_synapses(SLASH_ID, direction="both")
    urls = [call.args[0] for call in client._client.get.await_args_list]
    assert all(ENCODED in u and "/" + SLASH_ID not in u for u in urls)


async def test_modulator_paths_encode_ids(client: FeagiClient) -> None:
    client._client.request = AsyncMock(return_value=_ok({}))
    await client.get_modulator("mod/1=")
    url = client._client.request.await_args.args[1]
    assert url.endswith("/v1/modulator/modulator/mod%2F1%3D")


async def test_inspect_minimal_falls_back_to_incoming_listing(client: FeagiClient) -> None:
    client._client.post.return_value = _ok(
        {
            SLASH_ID: {
                "cortical_name": "Motor_LegR",
                "cortical_dimensions": [5, 1, 2],
                "incoming_synapse_count": 0,
                "outgoing_synapse_count": 0,
            },
            "ok": {"cortical_name": "fine", "incoming_synapse_count": 7},
        }
    )
    client._client.get.return_value = _ok(
        [{"source_neuron_id": i, "target_neuron_id": 9, "weight": 5.0} for i in range(3)]
    )
    result = await client.inspect_cortical_areas_minimal([SLASH_ID, "ok"])
    assert result[SLASH_ID]["incoming_synapse_count"] == 3
    assert result[SLASH_ID]["incoming_synapse_count_source"] == "synapse_listing"
    assert result["ok"]["incoming_synapse_count"] == 7
    assert "incoming_synapse_count_source" not in result["ok"]
    client._client.get.assert_awaited_once()
    assert ENCODED in client._client.get.await_args.args[0]
