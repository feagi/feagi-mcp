"""Percentage coding bindings: forwarding, conventions and the no-fallback import check."""

from __future__ import annotations

import sys

import pytest

from feagi_mcp import percentage_coding as pc
from tests.io_fixtures import DEPTH, RANGE, servo_coding, unit_definition


def test_unit_coding_decodes_and_inverts_through_the_binding() -> None:
    coding = servo_coding()
    assert coding.variant == "UnsignedLinear"
    assert coding.decode_fraction([0]) == 1.0
    assert coding.decode_fraction([DEPTH - 1]) == 0.0
    assert coding.decode_fraction([10, 10, 40]) == pytest.approx(0.8, abs=1e-6)
    for z in range(DEPTH):
        assert coding.bin_for_fraction(coding.decode_fraction([z])) == z


def test_signed_variant_fraction_is_zero_to_one() -> None:
    coding = pc.UnitCoding.build(pc.OUTPUT_SECTION, "RotaryMotor", unit_definition(), 0, 9)
    assert coding.variant == "SignedLinearAlongZ"
    middle = coding.bin_for_fraction(0.5)
    assert middle == 4
    assert coding.decode_native([middle]) == 0.0
    assert coding.decode_fraction([middle]) == 0.5
    assert coding.decode_fraction([0]) == 1.0 and coding.decode_fraction([8]) == 0.0


def test_two_lobe_variant_uses_both_lobes_and_has_no_single_bin() -> None:
    flags = {"frame_change_handling": "Incremental", "percentage_neuron_positioning": "Linear"}
    coding = pc.UnitCoding.build(
        pc.OUTPUT_SECTION, "SpatialPointer", unit_definition(flags=flags), 0, 9
    )
    assert coding.variant == "SignedLinearTwoLobe" and coding.two_lobe
    with pytest.raises(ValueError):
        coding.bin_for_fraction(0.5)
    positive, negative = coding.encode_fraction(0.75)
    assert positive and not negative
    assert coding.decode_fraction(positive, negative) == pytest.approx(0.75, abs=0.1)


def test_binding_errors_surface_as_value_error() -> None:
    with pytest.raises(ValueError):
        pc.UnitCoding.build(pc.OUTPUT_SECTION, "NoSuchUnit", unit_definition(), 0, 9)
    coding = servo_coding()
    for bad in (-0.1, 1.5, float("nan"), True, "x"):
        with pytest.raises(ValueError):
            coding.bin_for_fraction(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        coding.decode_fraction([DEPTH])


def test_same_coding_ignores_unit_kind_but_not_variant() -> None:
    a = servo_coding()
    other_kind = pc.UnitCoding.build(pc.OUTPUT_SECTION, "CountOutput", unit_definition(), 0, DEPTH)
    assert a.same_coding(other_kind)
    fractional = pc.UnitCoding.build(
        pc.OUTPUT_SECTION,
        "PositionalServo",
        unit_definition(
            flags={
                "frame_change_handling": "Absolute",
                "percentage_neuron_positioning": "Fractional",
            }
        ),
        0,
        DEPTH,
    )
    assert fractional.variant == "UnsignedFractional" and not a.same_coding(fractional)


def test_physical_range_is_validated_by_the_binding_and_linear() -> None:
    rng = pc.parse_physical_range(RANGE)
    assert rng is not None and rng.unit == "deg"
    assert rng.to_value(0.0) == -90.0 and rng.to_value(1.0) == 90.0
    assert rng.to_value(0.75) == 45.0 and rng.to_fraction(45.0) == 0.75
    inverted = pc.parse_physical_range({"value_at_0": 5.0, "value_at_1": -5.0, "unit": "rad"})
    assert inverted is not None and inverted.to_value(0.25) == 2.5
    assert pc.parse_physical_range(None) is None
    for bad in (
        {"value_at_0": 1.0, "value_at_1": 1.0, "unit": "rad"},
        {"value_at_0": 0.0, "value_at_1": 1.0, "unit": " "},
        {"value_at_0": 0.0, "value_at_1": 1.0},
    ):
        with pytest.raises(ValueError):
            pc.parse_physical_range(bad)


def test_old_or_missing_binding_is_a_clear_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from feagi_rust_py_libs import connector_core

    monkeypatch.delattr(connector_core, "target_to_z_bin")
    with pytest.raises(ImportError, match=r"feagi_rust_py_libs >= 0\.0\.122.*target_to_z_bin"):
        pc._load_connector_core()


def test_unimportable_package_is_a_clear_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "feagi_rust_py_libs", None)
    with pytest.raises(ImportError, match=r"feagi_rust_py_libs >= 0\.0\.122"):
        pc._load_connector_core()
