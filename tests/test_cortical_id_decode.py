"""Tests for cortical ID interpretation (MCP enhancement)."""

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation


def test_decode_omot_rotary_base64_known_regression():
    """Bytes from user regression: subunit 0, unit index 1, config byte4=0x05."""
    out = decode_cortical_id_interpretation("b21vdAUAAAE=")
    assert out["ok"] is True
    assert out["cortical_subunit_index"] == 0
    assert out["cortical_unit_index"] == 1
    assert out["subtype_4char"] == "omot"
    assert out["io_kind"] == "motor_output"
    assert out["config_bytes_4_5"] == [5, 0]
    assert out["mapping_hints"]["ros_connector_device_group_id"] == 1


def test_decode_legacy_latin1_eight_char_key():
    raw = bytes([111, 109, 111, 116, 5, 0, 0, 1])
    key = raw.decode("latin-1")
    out = decode_cortical_id_interpretation(key)
    assert out["ok"] is True
    assert out["cortical_unit_index"] == 1


def test_decode_invalid():
    out = decode_cortical_id_interpretation("not-valid-base64!!!")
    assert out["ok"] is False
    assert out.get("error")
