"""Stance mapping after the move to the bindings: bins identical to the former Python rule.

``data/stance_mapping_golden.json`` was recorded from the Python ``value_to_z_bin`` /
``z_bin_to_value`` implementation before it was removed. Bins and rows must match exactly;
joint-unit values (decoded by the binding in single precision) match within 1e-4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from feagi_mcp.stance_mapping import compile_stance_offset_rows, range_fraction
from tests.io_fixtures import servo_coding

GOLDEN = json.loads((Path(__file__).parent / "data" / "stance_mapping_golden.json").read_text())


def test_value_to_bin_sweep_matches_the_recorded_python_rule() -> None:
    codings: dict[int, Any] = {}
    mismatches = []
    for row in GOLDEN["bins"]:
        coding = codings.setdefault(row["depth"], servo_coding(row["depth"]))
        fraction = range_fraction(row["value"], row["lo"], row["hi"])
        if coding.bin_for_fraction(fraction) != row["bin"]:
            mismatches.append(row)
    assert len(GOLDEN["bins"]) > 3000
    assert mismatches == []


@pytest.mark.parametrize("index", range(len(GOLDEN["compile"])))
def test_compile_matches_the_recorded_python_rule(index: int) -> None:
    case = GOLDEN["compile"][index]
    kwargs = dict(case["kwargs"])
    coactive = kwargs.get("coactive_z")
    if isinstance(coactive, dict):
        kwargs["coactive_z"] = {int(k): v for k, v in coactive.items()}
    depth = kwargs.pop("depth")
    new = compile_stance_offset_rows(coding=servo_coding(depth), **kwargs)
    old = case["result"]
    assert new["voxel_mappings"] == old["voxel_mappings"]
    assert new["warnings"] == old["warnings"]
    assert [s["stance_dst"] for s in new["stance"]] == [s["stance_dst"] for s in old["stance"]]
    assert [(t["channel"], t["src_bin"], t.get("dst_z")) for t in new["table"]] == [
        (t["channel"], t["src_bin"], t.get("dst_z")) for t in old["table"]
    ]
    for got, want in zip(new["table"], old["table"], strict=True):
        assert got.get("offset") == want.get("offset")
        if "target_value" in want:
            assert got["target_value"] == pytest.approx(want["target_value"], abs=1e-4)
    for got, want in zip(new["stance"], old["stance"], strict=True):
        assert got["stance_value"] == pytest.approx(want["stance_value"], abs=1e-4)
    assert new["table_text"] == old["table_text"]
