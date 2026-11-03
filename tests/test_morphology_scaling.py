"""scale_morphology_rows: grouping, base, clamp rules, half-up rounding, axis detection."""

from __future__ import annotations

from fractions import Fraction

import pytest

from feagi_mcp.morphology_scaling import ScaleRowsError, half_up, plan_scaled_rows

ASC = [[[0, 0, i], [2, 0, z]] for i, z in enumerate([100, 110, 120, 130, 140])]
DESC = [[[0, 0, i], [2, 0, z]] for i, z in enumerate([200, 190, 180, 170, 160])]


def zs(plan):
    return [r[1][2] for r in plan["rows"]]


def test_grouping_and_base_default() -> None:
    rows = ASC + [[[0, 0, i], [4, 0, z]] for i, z in enumerate([50, 60, 70, 80, 90])]
    plan = plan_scaled_rows(rows, gain=2, depth=511, used_src_bins=[0, 1, 2])
    assert zs(plan) == [100, 120, 140, 160, 180, 50, 70, 90, 110, 130]
    assert plan["src_axis"] == 2


def test_explicit_base_z() -> None:
    plan = plan_scaled_rows(ASC, gain=2, depth=511, used_src_bins=[0, 1], base_z=110)
    assert zs(plan) == [90, 110, 130, 150, 170]


def test_used_bin_outside_strip_refused() -> None:
    with pytest.raises(ScaleRowsError, match="bin 4"):
        plan_scaled_rows(ASC, gain=3, depth=200, used_src_bins=[0, 4])


def test_unused_clamp_stored_and_flagged() -> None:
    plan = plan_scaled_rows(ASC, gain=3, depth=200, used_src_bins=[0, 1, 2])
    assert zs(plan) == [100, 130, 160, 190, 199]
    assert [e["status"] for e in plan["table"]][-2:] == ["in-strip", "clamped"]
    assert plan["table"][-1]["new_z"] == 220 and plan["table"][-1]["used"] is False


def test_mirrored_descending_rows_and_max_gain() -> None:
    plan = plan_scaled_rows(DESC, gain=2, depth=511, used_src_bins=[0, 1, 2, 3])
    assert zs(plan) == [200, 180, 160, 140, 120]
    # base 200, used d down to -30: no clamp while 200 - 30*g >= -0.5
    assert plan["largest_no_clamp_gain"] == 6.683
    plan = plan_scaled_rows(DESC, gain=6.683, depth=511, used_src_bins=[0, 1, 2, 3])
    assert min(zs(plan)[:4]) == 0


def test_half_up_not_bankers() -> None:
    assert half_up(Fraction(5, 2)) == 3 and half_up(Fraction(-5, 2)) == -2
    # ascending: 100 + 1.25*10 = 112.5 -> 113 (banker's round gives 112)
    plan = plan_scaled_rows(ASC, gain=1.25, depth=511, used_src_bins=[0, 1])
    assert zs(plan)[1] == 113
    # descending: 200 - 0.85*30 = 174.5 -> 175 (banker's round gives 174)
    plan = plan_scaled_rows(DESC, gain=0.85, depth=511, used_src_bins=[0, 3])
    assert zs(plan)[3] == 175


def test_multi_axis_refusal_and_src_axis() -> None:
    rows = [[[0, i, i], [2, 0, 100 + i]] for i in range(3)]
    with pytest.raises(ScaleRowsError, match="more than one source coordinate"):
        plan_scaled_rows(rows, gain=2, depth=511, used_src_bins=[0])
    rows = [[[i, 0, 5], [2, 0, 100 + i]] for i in range(3)]
    assert plan_scaled_rows(rows, gain=2, depth=511, used_src_bins=[0])["src_axis"] == 0


def test_wildcard_refused() -> None:
    with pytest.raises(ScaleRowsError, match="wildcard"):
        plan_scaled_rows([[["*", 0, 0], [0, 0, 1]]], gain=2, depth=10, used_src_bins=[0])
