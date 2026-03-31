"""list_cortical_areas uses Rust connectome detailed endpoint + payload normalization."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import FeagiClient, _normalize_cortical_area_list_payload


def test_normalize_detailed_map() -> None:
    data = {
        "area_a": {"cortical_type": "CUSTOM", "neuron_count": 10},
        "area_b": {"cortical_type": "IPU"},
    }
    out = _normalize_cortical_area_list_payload(data)
    assert len(out) == 2
    ids = {d.get("cortical_id") for d in out}
    assert ids == {"area_a", "area_b"}


def test_normalize_legacy_list() -> None:
    data = [{"cortical_id": "x", "cortical_type": "CUSTOM"}]
    assert _normalize_cortical_area_list_payload(data) == data


@pytest.mark.asyncio
async def test_list_cortical_areas_uses_connectome_detailed() -> None:
    client = FeagiClient()
    client._client = AsyncMock()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"n1": {"cortical_type": "CUSTOM"}}

    client._client.get.return_value = mock_response

    result = await client.list_cortical_areas()

    assert len(result) == 1
    assert result[0]["cortical_id"] == "n1"
    client._client.get.assert_called_once()
    call_url = client._client.get.call_args[0][0]
    assert "/v1/connectome/cortical_areas/list/detailed" in call_url


@pytest.mark.asyncio
async def test_list_cortical_areas_falls_back_to_legacy() -> None:
    client = FeagiClient()
    client._client = AsyncMock()

    fail = MagicMock()
    fail.status_code = 404
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = [{"cortical_id": "legacy", "cortical_type": "CUSTOM"}]

    client._client.get.side_effect = [fail, ok]

    result = await client.list_cortical_areas()

    assert len(result) == 1
    assert result[0]["cortical_id"] == "legacy"
    assert client._client.get.call_count == 2
