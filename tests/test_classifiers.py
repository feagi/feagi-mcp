"""Tests for classifier MCP list/inspect helpers and client calls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.classifiers import (
    build_classifier_inspect,
    filter_classifier_records,
    project_classifier_row,
    scan_blockers,
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
        "sample_area_ids": ["kernel"],
        "class_bindings": [{"class_area_id": "class", "class_output_area_id": "twin"}],
        "sample_memory_id": "kmem",
        "class_memory_id": "cmem",
        "error_area_id": "err",
        "correct_area_id": "corr",
        "properties": {},
    }


def _areas() -> list[dict]:
    return [
        {
            "cortical_id": "kernel",
            "cortical_name": "turn_right",
            "cortical_type": "custom",
            "cortical_dimensions": [4, 4, 1],
            "visible": True,
            "coordinates_3d": [0, 0, 0],
            "parent_region_id": "region-1",
            "neuron_count": 1,
        },
        {
            "cortical_id": "class",
            "name": "backward",
            "cortical_type": "custom",
            "cortical_dimensions": [1, 1, 3],
            "visible": True,
        },
        {
            "cortical_id": "field",
            "cortical_name": "turn_left",
            "cortical_type": "custom",
            "cortical_dimensions": [4, 4, 1],
            "visible": True,
            "neuron_burst_engine_active": True,
        },
        {
            "cortical_id": "err",
            "cortical_name": "Ela joon error",
            "cortical_type": "custom",
            "cortical_dimensions": [1, 1, 1],
            "visible": True,
        },
        {
            "cortical_id": "corr",
            "cortical_name": "Ela joon correct",
            "cortical_type": "custom",
            "cortical_dimensions": [1, 1, 1],
            "visible": True,
        },
        {
            "cortical_id": "kmem",
            "cortical_name": "Ela joon_sample_mem",
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
            "cortical_name": "Ela joon class output",
            "cortical_type": "custom",
            "cortical_dimensions": [1, 1, 3],
            "neuron_mp_driven_psp": False,
            "visible": True,
            "coordinates_3d": [-35, 0, 5],
            "neuron_burst_engine_active": True,
            "neuron_count": 360,
        },
    ]


def _mappings() -> list[dict]:
    return [
        {"src": "kernel", "dst": "kmem", "morphology": "classifier_sample"},
        {"src": "class", "dst": "cmem", "morphology": "classifier_class"},
        {"src": "kmem", "dst": "cmem", "morphology": "associative_memory"},
    ]


def test_project_classifier_row_drops_properties() -> None:
    row = project_classifier_row(_classifier())
    assert row["classifier_id"] == "clf-1"
    assert row["class_bindings"] == [{"class_area_id": "class", "class_output_area_id": "twin"}]
    assert "properties" not in row
    assert "training_mode" not in row


def test_project_classifier_row_keeps_error_area() -> None:
    row = project_classifier_row(_classifier())
    assert row["error_area_id"] == "err"
    assert row["sample_memory_id"] == "kmem"


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
    assert payload["outputs_visible"] is True
    assert payload["class_bindings"][0]["class_output"]["name"] == "Ela joon class output"
    assert payload["class_bindings"][0]["class_output"]["cortical_dimensions"] == [1, 1, 3]
    assert payload["value_findings"] == []
    assert payload["missing_slots"] == []
    assert payload["missing_mappings"] == []
    roles = [row["role"] for row in payload["mappings"]]
    assert roles == [
        "sample_mem_to_class_mem",
        "sample_to_sample_mem",
        "class_to_class_mem",
    ]


def test_inspect_lists_correct_slot_and_flags_when_missing() -> None:
    payload = build_classifier_inspect(_classifier(), _areas(), _mappings())
    assert payload["slots"]["correct"]["area_id"] == "corr"
    assert payload["slots"]["correct"]["present"] is True
    classifier = _classifier()
    classifier["correct_area_id"] = ""
    broken = build_classifier_inspect(classifier, _areas(), _mappings())
    assert "correct" in broken["missing_slots"]
    assert "correct_missing" in broken["blockers"]
    assert "error_missing" not in broken["blockers"]
    assert "correct_missing" in scan_blockers({}, ["correct"], [])


def test_inspect_flags_missing_class_output() -> None:
    classifier = _classifier()
    classifier["class_bindings"] = [{"class_area_id": "class", "class_output_area_id": ""}]
    mappings = [row for row in _mappings() if row["morphology"] != "classifier_class"]
    payload = build_classifier_inspect(classifier, _areas(), mappings)
    assert payload["outputs_visible"] is False
    assert "class_output_missing" in payload["blockers"]
    assert payload["ready"] is False


def test_inspect_reports_scan_blockers_for_ltm_and_burst() -> None:
    areas = _areas()
    for area in areas:
        if area["cortical_id"] in {"field", "twin"}:
            area["neuron_burst_engine_active"] = False
    payload = build_classifier_inspect(
        _classifier(),
        areas,
        _mappings(),
        {
            "kmem": {
                "short_term_neuron_count": 0,
                "long_term_neuron_count": 0,
                "memory_parameters": {
                    "init_lifespan": 9,
                    "longterm_mem_threshold": 100,
                },
            }
        },
    )
    assert payload["slots"]["sample_memory"]["long_term_neuron_count"] == 0
    assert payload["slots"]["sample_memory"]["init_lifespan"] == 9
    assert "sample_memory_no_ltm" in payload["blockers"]
    assert "class_output_burst_engine_off" in payload["blockers"]
    assert payload["ready"] is False
    blockers = scan_blockers(payload["slots"], [], [])
    assert "sample_memory_no_ltm" in blockers


def test_inspect_flags_sample_memory_without_an_encode() -> None:
    mappings = [row for row in _mappings() if not (row["src"] == "kernel" and row["dst"] == "kmem")]
    payload = build_classifier_inspect(_classifier(), _areas(), mappings)
    sample = payload["slots"]["sample_memory"]
    assert sample["episodic_upstream"] == []
    assert payload["slots"]["class_memory"]["episodic_upstream"] == ["class"]
    assert "memory_no_episodic_upstream" in payload["blockers"]
    assert payload["memory_findings"][0]["slot"] == "sample_memory"
    assert payload["ready"] is False


def test_inspect_attaches_lifecycle_totals_and_churn_finding() -> None:
    payload = build_classifier_inspect(
        _classifier(),
        _areas(),
        _mappings(),
        {"kmem": {"short_term_neuron_count": 0, "long_term_neuron_count": 0}},
        {"kmem": {"created_total": 12, "deleted_total": 12, "neuron_count": 0}},
    )
    sample = payload["slots"]["sample_memory"]
    assert sample["created_total"] == 12
    assert sample["deleted_total"] == 12
    assert sample["episodic_upstream"] == ["kernel"]
    codes = [(f["slot"], f["code"]) for f in payload["memory_findings"]]
    assert codes == [("sample_memory", "memory_neurons_expire_unmatched")]
    assert "memory_neurons_expire_unmatched" not in payload["blockers"]


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
    client.list_memory_neurons = AsyncMock(
        return_value={
            "short_term_neuron_count": 0,
            "long_term_neuron_count": 2,
            "memory_parameters": {"init_lifespan": 9, "longterm_mem_threshold": 100},
        }
    )
    client.health_check = AsyncMock(
        return_value={
            "status": "ok",
            "memory_area_stats": {
                "kmem": {"created_total": 5, "deleted_total": 3, "neuron_count": 2}
            },
        }
    )
    payload = await client.inspect_classifier(classifier_id="clf-1")
    assert payload["classifier"]["name"] == "Ela joon"
    assert payload["outputs_visible"] is True
    assert payload["missing_mappings"] == []
    assert payload["ready"] is True
    assert payload["memory_findings"] == []
    assert payload["slots"]["sample_memory"]["created_total"] == 5
    assert payload["slots"]["class_memory"]["created_total"] is None
    assert client.list_memory_neurons.await_count == 2
    client.health_check.assert_awaited_once()


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
