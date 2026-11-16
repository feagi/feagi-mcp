"""Tests for cortical ID interpretation (MCP enhancement)."""

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation
from feagi_mcp.io_cortical_id_encode import encode_io_cortical_id


def test_decode_omot_rotary_base64_known_regression():
    """SignedPercentage omot, subunit 0, unit index 1 packed as little-endian u16."""
    encoded = encode_io_cortical_id(
        "omot",
        variant="signed_percentage",
        unit_index=1,
        subunit_index=0,
    )
    out = decode_cortical_id_interpretation(encoded["cortical_id"])
    assert out["ok"] is True
    assert out["cortical_subunit_index"] == 0
    assert out["cortical_unit_index"] == 1
    assert out["subtype_4char"] == "omot"
    assert out["io_kind"] == "motor_output"
    assert out["mapping_hints"]["ros_connector_device_group_id"] == 1
    assert out["bytes_hex"].endswith("01 00")


def test_decode_legacy_latin1_eight_char_key():
    raw = bytes([111, 109, 111, 116, 5, 0, 1, 0])
    key = raw.decode("latin-1")
    out = decode_cortical_id_interpretation(key)
    assert out["ok"] is True
    assert out["cortical_unit_index"] == 1


def test_decode_positional_servo_incremental_live_id():
    """Live ungrouped-1 id stores subunit 1 in flag bits 4-7, not byte 6."""
    out = decode_cortical_id_interpretation("b3BzZREBAAA=")
    assert out["ok"] is True
    assert out["subtype_4char"] == "opse"
    assert out["cortical_subunit_index"] == 1
    assert out["cortical_unit_index"] == 0
    assert out["frame_change_handling"] == "Incremental"
    assert out["mapping_hints"]["bv_subunit_id"] == 1


def test_decode_positional_servo_speed_live_id():
    """Live Positional Servo Speed id stores subunit 2 in flag bits 4-7."""
    out = decode_cortical_id_interpretation("b3BzZSEAAAA=")
    assert out["ok"] is True
    assert out["subtype_4char"] == "opse"
    assert out["cortical_subunit_index"] == 2
    assert out["cortical_unit_index"] == 0
    assert out["frame_change_handling"] == "Absolute"
    assert out["mapping_hints"]["bv_subunit_id"] == 2


def test_decode_invalid():
    out = decode_cortical_id_interpretation("not-valid-base64!!!")
    assert out["ok"] is False
    assert out.get("error")


def test_decode_variant_kind_signed_and_positioning():
    """Bits 0-3 variant, bit 9 positioning; variants without a positioning axis report None."""
    cases = [
        ("percentage", "Percentage", False, "Fractional", "fractional"),
        ("signed_percentage_2d", "SignedPercentage2D", True, "Linear", "linear"),
        ("misc", "Misc", False, None, "linear"),
    ]
    for variant, kind, signed, positioning, pos_arg in cases:
        encoded = encode_io_cortical_id(
            "omot",
            variant=variant,
            unit_index=0,
            subunit_index=3,
            positioning=pos_arg,
            framing="incremental",
        )
        out = decode_cortical_id_interpretation(encoded["cortical_id"])
        assert out["kind"] == kind and out["signed"] is signed
        assert out["positioning"] == positioning
        assert out["cortical_subunit_index"] == 3
        assert out["frame_change_handling"] == "Incremental"


def _io_id(flag: int, prefix: bytes = b"i") -> str:
    import base64

    return base64.b64encode(prefix + b"abc" + flag.to_bytes(2, "little") + b"\x00\x00").decode()


def test_shared_io_flag_fixture_matches_the_rust_flag_rules() -> None:
    """``io-flag-fixture.json`` is the same table feagi-core and Composer assert."""
    import json
    from pathlib import Path

    from feagi_mcp.cortical_id_decode import io_flag_datasheet_fields

    cases = json.loads(
        (Path(__file__).parent / "io-flag-fixture.json").read_text(encoding="utf-8")
    )["cases"]
    assert len(cases) >= 15
    for case in cases:
        expected = None if case["expect"] == "invalid" else case["expect"]
        assert io_flag_datasheet_fields(case["flag"]) == expected, case["note"]
        out = decode_cortical_id_interpretation(_io_id(case["flag"]))
        if expected is not None:
            assert out["kind"] == expected["kind"], case["note"]
            assert out["positioning"] == expected.get("positioning"), case["note"]
            assert out["frame_change_handling"] == expected.get("frame"), case["note"]


def test_boolean_has_no_frame_like_rust() -> None:
    out = decode_cortical_id_interpretation(_io_id(0x0100))
    assert out["kind"] == "Boolean"
    assert out["frame_change_handling"] is None
