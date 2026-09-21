"""Tests for compact IPU/OPU catalog projection."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.feagi_client import FeagiClient, project_cortical_area_catalog_row
from feagi_mcp.io_area_catalog import (
    build_io_areas_compact_payload,
    dimension_dev_count_mismatch,
    project_io_area_compact_row,
    validate_io_kind,
)

# Live-genome IDs from encoder-strip debugging (imis / ipro / isvi / opse).
_IMIS_ID = "aW1pcwoAAAA="
_IPRO_ID = "aXBybwEAAQA="
_ISVI_ID = "aXN2aQkAAAA="
_OPSE_ID = "b3BzZQEAAAA="
_OPSE_SPEED_ID = "b3BzZSEAAAA="


def _imis_collapsed() -> dict:
    return {
        "cortical_id": _IMIS_ID,
        "cortical_name": "actuator_force_ANC",
        "cortical_group": "IPU",
        "cortical_type": "sensory",
        "cortical_subtype": "imis",
        "cortical_dimensions": [1, 1, 1],
        "cortical_dimensions_per_device": [1, 1, 1],
        "dev_count": 416,
        "neuron_count": 1,
        "neuron_leak_coefficient": 0.0,
    }


def _opse_expanded() -> dict:
    return {
        "cortical_id": _OPSE_ID,
        "cortical_name": "ungrouped-0",
        "cortical_group": "OPU",
        "cortical_type": "motor",
        "cortical_subtype": "opse",
        "cortical_dimensions": [416, 1, 20],
        "cortical_dimensions_per_device": [1, 1, 20],
        "dev_count": 416,
        "neuron_count": 8320,
    }


def test_validate_io_kind_aliases() -> None:
    assert validate_io_kind(None) == "both"
    assert validate_io_kind("IPU") == "ipu"
    assert validate_io_kind("motor") == "opu"


def test_validate_io_kind_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="io_kind must be one of"):
        validate_io_kind("vision")


def test_dimension_mismatch_flags_collapsed_encoder_ipu() -> None:
    assert dimension_dev_count_mismatch([1, 1, 1], [1, 1, 1], 416) is True
    assert dimension_dev_count_mismatch([416, 1, 20], [1, 1, 20], 416) is False
    assert dimension_dev_count_mismatch([1, 1, 10], None, 1) is False


def test_project_io_row_decodes_imis_and_flags_mismatch() -> None:
    row = project_io_area_compact_row(_imis_collapsed())
    assert row["subtype"] == "imis"
    assert row["io_kind"] == "ipu"
    assert row["dev_count"] == 416
    assert row["cortical_dimensions"] == [1, 1, 1]
    assert row["dimension_dev_count_mismatch"] is True
    assert "neuron_leak_coefficient" not in row


def test_project_io_row_decodes_opse_without_mismatch() -> None:
    row = project_io_area_compact_row(_opse_expanded())
    assert row["subtype"] == "opse"
    assert row["io_kind"] == "opu"
    assert row["subunit_index"] == 0
    assert row["dimension_dev_count_mismatch"] is False


def test_project_io_row_decodes_opse_speed_subunit() -> None:
    row = project_io_area_compact_row(
        {
            "cortical_id": _OPSE_SPEED_ID,
            "cortical_name": "Positional Servo Speed",
            "cortical_group": "OPU",
            "cortical_type": "motor",
            "cortical_subtype": "opse",
            "cortical_dimensions": [6, 1, 20],
            "cortical_dimensions_per_device": [1, 1, 20],
            "dev_count": 6,
        }
    )
    assert row["subtype"] == "opse"
    assert row["subunit_index"] == 2
    assert row["unit_index"] == 0
    assert row["dimension_dev_count_mismatch"] is False


def test_summary_groups_by_subtype_and_can_omit_areas() -> None:
    ipro = {
        "cortical_id": _IPRO_ID,
        "cortical_name": "cervical_spine_angvel",
        "cortical_group": "IPU",
        "cortical_dimensions": [1, 1, 10],
        "cortical_dimensions_per_device": [1, 1, 10],
        "dev_count": 232,
    }
    vision = {
        "cortical_id": _ISVI_ID,
        "cortical_name": "vision_C",
        "cortical_group": "IPU",
        "cortical_dimensions": [32, 32, 1],
        "dev_count": 1,
    }
    payload = build_io_areas_compact_payload(
        [_imis_collapsed(), ipro, vision, _opse_expanded()],
        io_kind="ipu",
        include_areas=False,
    )
    assert payload["count"] == 3
    assert payload["mismatch_count"] == 2
    assert payload["areas"] == []
    assert payload["by_subtype"]["imis"]["count"] == 1
    assert payload["by_subtype"]["imis"]["mismatch_count"] == 1
    assert payload["by_subtype"]["ipro"]["mismatch_count"] == 1
    assert payload["by_subtype"]["isvi"]["mismatch_count"] == 0


def test_mismatches_only_and_limit() -> None:
    payload = build_io_areas_compact_payload(
        [_imis_collapsed(), _opse_expanded()],
        io_kind="both",
        mismatches_only=True,
        limit=10,
    )
    assert payload["count"] == 2
    assert payload["mismatch_count"] == 1
    assert payload["returned"] == 1
    assert payload["areas"][0]["subtype"] == "imis"


def test_subtype_filter() -> None:
    payload = build_io_areas_compact_payload(
        [_imis_collapsed(), _opse_expanded()],
        io_kind="both",
        subtype="opse",
    )
    assert payload["count"] == 1
    assert payload["areas"][0]["name"] == "ungrouped-0"


def test_catalog_row_keeps_dev_count_and_drops_neuron_params() -> None:
    row = project_cortical_area_catalog_row(_imis_collapsed())
    assert row["dev_count"] == 416
    assert row["cortical_dimensions_per_device"] == [1, 1, 1]
    assert row["cortical_subtype"] == "imis"
    assert "neuron_leak_coefficient" not in row


@pytest.mark.asyncio
async def test_list_io_areas_compact_uses_one_detailed_list_fetch() -> None:
    client = FeagiClient()
    client._client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        _IMIS_ID: _imis_collapsed(),
        _OPSE_ID: _opse_expanded(),
    }
    client._client.get.return_value = mock_response

    result = await client.list_io_areas_compact("ipu", mismatches_only=True)

    assert result["count"] == 1
    assert result["mismatch_count"] == 1
    assert result["areas"][0]["name"] == "actuator_force_ANC"
    client._client.get.assert_called_once()
    call_url = client._client.get.call_args[0][0]
    assert "/v1/connectome/cortical_areas/list/detailed" in call_url


def test_nested_properties_dev_count() -> None:
    row = project_io_area_compact_row(
        {
            "cortical_id": _IMIS_ID,
            "cortical_group": "IPU",
            "cortical_dimensions": [1, 1, 1],
            "cortical_dimensions_per_device": [1, 1, 1],
            "properties": {"dev_count": 416},
        }
    )
    assert row["dev_count"] == 416
    assert row["dimension_dev_count_mismatch"] is True
