"""Unit tests for BV placement policy helpers."""

from feagi_mcp.placement_policy import (
    LAYOUT_TEMPORAL_Z,
    LAYOUT_XY_PLANE,
    ORIGIN_EXCLUSION_RADIUS_VOXELS,
    check_min_separation_to_existing,
    check_origin_exclusion,
    parse_region_coordinate_3d,
    suggest_anchor_positions,
)


def test_origin_exclusion_inside_sphere_fails() -> None:
    err = check_origin_exclusion([10, 0, 0])
    assert err is not None
    assert str(ORIGIN_EXCLUSION_RADIUS_VOXELS) in err


def test_origin_exclusion_outside_sphere_ok() -> None:
    assert check_origin_exclusion([25, 0, 0]) is None


def test_min_separation_detects_close_neighbor() -> None:
    geom = {
        "id1": {
            "cortical_name": "Other",
            "coordinates_3d": [50, 50, 0],
        }
    }
    err = check_min_separation_to_existing([60, 50, 0], geom, min_separation=32)
    assert err is not None
    assert "Other" in err


def test_min_separation_far_ok() -> None:
    geom = {
        "id1": {
            "cortical_name": "Other",
            "coordinates_3d": [0, 100, 0],
        }
    }
    assert check_min_separation_to_existing([50, 50, 0], geom, min_separation=32) is None


def test_parse_region_coordinate_3d() -> None:
    rm = {
        "rid-1": {"coordinate_3d": [10, 20, 30], "title": "X"},
    }
    assert parse_region_coordinate_3d(rm, "rid-1") == (10, 20, 30)
    assert parse_region_coordinate_3d(rm, "missing") is None


def test_suggest_anchor_positions_xy_plane_spreads_x_same_yz() -> None:
    geom = {
        "a": {"coordinates_3d": [500, 500, 500], "cortical_name": "Far"},
    }
    positions = suggest_anchor_positions(
        3,
        geom,
        base_hint=(120, 120, 120),
        spacing=40,
        layout=LAYOUT_XY_PLANE,
    )
    assert len(positions) == 3
    assert positions[0][1] == positions[1][1] == positions[2][1]
    assert positions[0][2] == positions[1][2] == positions[2][2]
    assert positions[1][0] - positions[0][0] >= 32


def test_suggest_anchor_positions_temporal_z_stacks_along_z() -> None:
    geom = {
        "a": {"coordinates_3d": [500, 500, 500], "cortical_name": "Far"},
    }
    positions = suggest_anchor_positions(
        3,
        geom,
        base_hint=(120, 120, 120),
        spacing=40,
        layout=LAYOUT_TEMPORAL_Z,
    )
    assert len(positions) == 3
    assert positions[0][0] == positions[1][0] == positions[2][0]
    assert positions[1][2] - positions[0][2] >= 32
