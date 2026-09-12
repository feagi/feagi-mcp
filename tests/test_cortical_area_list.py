"""list_cortical_areas uses Rust connectome detailed endpoint + payload normalization."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import (
    FeagiClient,
    _cortical_area_name,
    _normalize_cortical_area_list_payload,
    filter_cortical_area_records,
    project_cortical_area_catalog_row,
    validate_cortical_list_type_filter,
)


def _sample_areas() -> list[dict]:
    return [
        {
            "cortical_id": "ptr_abs",
            "cortical_id_s": "SpatialPointer_2",
            "cortical_name": "Spatial Pointer Absolute",
            "cortical_type": "motor",
            "cortical_group": "OPU",
            "area_type": "Motor",
            "cortical_dimensions": [3, 1, 100],
            "neuron_leak_coefficient": 0.9,
        },
        {
            "cortical_id": "ptr_spd",
            "cortical_id_s": "SpatialPointer_3",
            "cortical_name": "Spatial Pointer Speed",
            "cortical_type": "motor",
            "cortical_group": "OPU",
            "area_type": "Motor",
            "cortical_dimensions": [3, 1, 100],
            "neuron_leak_coefficient": 0.9,
        },
        {
            "cortical_id": "pse_spd",
            "cortical_id_s": "PositionalServo_0-2",
            "name": "Positional Servo Speed",
            "cortical_type": "motor",
            "cortical_group": "OPU",
            "cortical_dimensions": [6, 1, 50],
        },
        {
            "cortical_id": "cam",
            "cortical_name": "Front Camera",
            "cortical_type": "sensory",
            "cortical_group": "IPU",
        },
    ]


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


def test_filter_cortical_area_records_by_name() -> None:
    matched = filter_cortical_area_records(_sample_areas(), name_contains="speed")
    names = {_cortical_area_name(area) for area in matched}
    assert names == {"Spatial Pointer Speed", "Positional Servo Speed"}


def test_filter_cortical_area_records_by_cortical_id() -> None:
    matched = filter_cortical_area_records(
        _sample_areas(),
        cortical_id_contains="SpatialPointer_3",
    )
    assert [area["cortical_id"] for area in matched] == ["ptr_spd"]


def test_filter_cortical_area_records_by_type() -> None:
    matched = filter_cortical_area_records(_sample_areas(), cortical_type="IPU")
    assert [area["cortical_id"] for area in matched] == ["cam"]


def test_filter_cortical_area_records_combines_and_limit() -> None:
    matched = filter_cortical_area_records(
        _sample_areas(),
        name_contains="Pointer",
        cortical_type="OPU",
        limit=1,
    )
    assert len(matched) == 1
    assert matched[0]["cortical_id"] == "ptr_abs"


def test_filter_rejects_unknown_cortical_type() -> None:
    with pytest.raises(ValueError, match="cortical_type must be one of"):
        filter_cortical_area_records(_sample_areas(), cortical_type="vision")


def test_filter_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be an integer"):
        filter_cortical_area_records(_sample_areas(), limit=0)


def test_validate_cortical_list_type_filter_accepts_known_aliases() -> None:
    assert validate_cortical_list_type_filter("opu") == "opu"
    assert validate_cortical_list_type_filter(None) == ""


def test_project_cortical_area_catalog_row_drops_neuron_params() -> None:
    row = project_cortical_area_catalog_row(_sample_areas()[1])
    assert row["name"] == "Spatial Pointer Speed"
    assert row["cortical_id"] == "ptr_spd"
    assert row["cortical_dimensions"] == [3, 1, 100]
    assert "neuron_leak_coefficient" not in row


@pytest.mark.asyncio
async def test_list_cortical_areas_applies_filters_locally() -> None:
    client = FeagiClient()
    client._client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ptr_spd": {
            "cortical_name": "Spatial Pointer Speed",
            "cortical_group": "OPU",
        },
        "cam": {
            "cortical_name": "Front Camera",
            "cortical_group": "IPU",
        },
    }
    client._client.get.return_value = mock_response

    result = await client.list_cortical_areas(name_contains="Speed")

    assert [area["cortical_id"] for area in result] == ["ptr_spd"]
    client._client.get.assert_called_once()


@pytest.mark.asyncio
async def test_list_cortical_area_names_filters_by_substring() -> None:
    client = FeagiClient()
    client._client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "cortical_area_name_list": [
            "Spatial Pointer Absolute",
            "Spatial Pointer Speed",
            "Front Camera",
        ]
    }
    client._client.get.return_value = mock_response

    result = await client.list_cortical_area_names(name_contains="pointer")

    assert result == ["Spatial Pointer Absolute", "Spatial Pointer Speed"]
