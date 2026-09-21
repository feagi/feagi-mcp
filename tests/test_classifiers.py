"""Tests for classifier MCP list/inspect helpers and client calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.classifiers import (
    build_classifier_inspect,
    filter_classifier_records,
    project_classifier_row,
    select_classifier_record,
)
from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.server import inspect_classifier, list_classifiers


def _classifier() -> dict:
    return {
        "classifier_id": "clf-1",
        "name": "Ela joon",
        "parent_region_id": "region-1",
        "coordinates_3d": [-29, 57, 10],
        "kernel_area_id": "kernel",
        "class_area_id": "class",
        "field_area_id": "field",
        "kernel_memory_id": "kmem",
        "class_memory_id": "cmem",
        "scan_twin_id": "twin",
        "properties": {},
    }


def _areas() -> list[dict]:
    return [
        {
            "cortical_id": "kernel",
            "cortical_name": "turn_right",
            "cortical_type": "custom",
            "cortical_dimensions": [1, 1, 1],
            "visible": True,
            "coordinates_3d": [0, 0, 0],
            "parent_region_id": "region-1",
            "neuron_count": 1,
        },
        {
            "cortical_id": "class",
            "name": "backward",
            "cortical_type": "custom",
            "cortical_dimensions": [2, 3, 1],
            "visible": True,
        },
        {
            "cortical_id": "field",
            "cortical_name": "turn_left",
            "cortical_type": "custom",
            "cortical_dimensions": [10, 6, 1],
            "visible": True,
        },
        {
            "cortical_id": "kmem",
            "cortical_name": "Ela joon_kernel_mem",
            "cortical_type": "memory",
            "cortical_dimensions": [1, 1, 1],
            "visible": True,
        },
        {
            "cortical_id": "cmem",
            "cortical_name": "Ela joon_class_mem",
            "cortical_type": "memory",
            "cortical_dimensions": [1, 1, 1],
            "visible": False,
        },
        {
            "cortical_id": "twin",
            "cortical_name": "Ela joon_twin",
            "cortical_type": "custom",
            "cortical_dimensions": [10, 6, 6],
            "visible": True,
            "coordinates_3d": [-35, 0, 5],
            "neuron_burst_engine_active": True,
            "neuron_count": 360,
        },
    ]


def _mappings() -> list[dict]:
    return [
        {"src": "kernel", "dst": "kmem", "morphology": "episodic_memory"},
        {"src": "class", "dst": "cmem", "morphology": "episodic_memory"},
        {"src": "kmem", "dst": "cmem", "morphology": "associative_memory"},
        {"src": "field", "dst": "kmem", "morphology": "episodic_scan"},
    ]


def test_project_classifier_row_drops_properties() -> None:
    row = project_classifier_row(_classifier())
    assert row["classifier_id"] == "clf-1"
    assert row["scan_twin_id"] == "twin"
    assert "properties" not in row


def test_filter_and_select_classifier() -> None:
    records = [_classifier(), {**_classifier(), "classifier_id": "clf-2", "name": "Other"}]
    filtered = filter_classifier_records(records, name_contains="ela")
    assert len(filtered) == 1
    selected = select_classifier_record(records, name_contains="ela")
    assert selected["classifier"]["classifier_id"] == "clf-1"
    missing = select_classifier_record(records, name_contains="missing")
    assert missing["error"] == "not_found"
    ambiguous = select_classifier_record(records, name_contains="o")
    assert ambiguous["error"] == "ambiguous"
    blank = select_classifier_record(records)
    assert blank["error"] == "invalid_input"


def test_inspect_reports_twin_and_required_mappings() -> None:
    payload = build_classifier_inspect(_classifier(), _areas(), _mappings())
    assert payload["twin_visible"] is True
    assert payload["slots"]["scan_twin"]["name"] == "Ela joon_twin"
    assert payload["slots"]["scan_twin"]["cortical_dimensions"] == [10, 6, 6]
    assert payload["missing_slots"] == []
    assert payload["missing_mappings"] == []
    roles = [row["role"] for row in payload["mappings"]]
    assert roles == [
        "kernel_to_kernel_mem",
        "class_to_class_mem",
        "kernel_mem_to_class_mem",
        "field_to_kernel_mem",
    ]


def test_inspect_flags_missing_twin_and_scan_mapping() -> None:
    classifier = _classifier()
    classifier["scan_twin_id"] = ""
    mappings = [row for row in _mappings() if row["morphology"] != "episodic_scan"]
    payload = build_classifier_inspect(classifier, _areas(), mappings)
    assert payload["twin_visible"] is False
    assert "scan_twin" in payload["missing_slots"]
    assert "field_to_kernel_mem" in payload["missing_mappings"]


@pytest.mark.asyncio
async def test_client_list_classifiers_filters_locally() -> None:
    client = FeagiClient()
    client._client = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = [
        _classifier(),
        {**_classifier(), "name": "Other", "classifier_id": "clf-2"},
    ]
    client._client.get.return_value = response
    rows = await client.list_classifiers(name_contains="Ela")
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["name"] == "Ela joon"
    client._client.get.assert_awaited_once()
    assert client._client.get.await_args.args[0].endswith("/v1/cortical_area/classifiers")


@pytest.mark.asyncio
async def test_client_get_classifier_requires_id() -> None:
    client = FeagiClient()
    result = await client.get_classifier("  ")
    assert result["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_client_inspect_classifier_uses_one_assembly_payload() -> None:
    client = FeagiClient()
    client.get_classifier = AsyncMock(return_value=_classifier())
    client.list_cortical_areas = AsyncMock(return_value=_areas())
    client.get_connectivity_summary = AsyncMock(
        return_value={"items": _mappings(), "total_filtered": 4}
    )
    payload = await client.inspect_classifier(classifier_id="clf-1")
    assert payload["classifier"]["name"] == "Ela joon"
    assert payload["twin_visible"] is True
    assert payload["missing_mappings"] == []


@pytest.mark.asyncio
async def test_server_tools_delegate_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = [{"classifier_id": "clf-1", "name": "Ela joon"}]
    inspected = {"classifier": listed[0], "twin_visible": True}

    async def fake_list(**kwargs):
        assert kwargs["name_contains"] == "Ela"
        return listed

    async def fake_inspect(**kwargs):
        assert kwargs["classifier_id"] == "clf-1"
        return inspected

    monkeypatch.setattr("feagi_mcp.server.feagi.list_classifiers", fake_list)
    monkeypatch.setattr("feagi_mcp.server.feagi.inspect_classifier", fake_inspect)
    assert await list_classifiers(name_contains="Ela") == listed
    assert await inspect_classifier(classifier_id="clf-1") == inspected
