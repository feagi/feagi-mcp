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
