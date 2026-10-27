"""Tests for Brain Visualizer operation registry and path resolution."""

import pytest

from feagi_mcp.bv_operations import (
    BV_OPERATION_BY_ID,
    BV_OPERATIONS,
    list_operation_summaries,
    resolve_path,
)


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
