"""Unit tests for the pure IPU/OPU cortical-id encoder (no live FEAGI)."""

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation
from feagi_mcp.io_cortical_id_encode import configuration_flag, encode_io_cortical_id


class TestConfigurationFlag:
    """Flag bitmask derivation mirrors the Rust source of truth."""

    def test_percentage_absolute_linear_is_one(self):
        flag, err = configuration_flag("percentage", "absolute", "linear")
        assert err is None
        assert flag == 1

    def test_incremental_sets_bit_8(self):
        flag, err = configuration_flag("percentage", "incremental", "linear")
        assert err is None
        assert flag == 1 | (1 << 8)

    def test_fractional_sets_bit_9(self):
        flag, err = configuration_flag("percentage", "absolute", "fractional")
        assert err is None
        assert flag == 1 | (1 << 9)

    def test_boolean_variant_is_zero(self):
        flag, err = configuration_flag("boolean", "absolute", "linear")
        assert err is None
        assert flag == 0

    def test_unsupported_variant_errors(self):
        flag, err = configuration_flag("pose_estimation", "absolute", "linear")
        assert flag is None
        assert err is not None

    def test_boolean_rejects_non_neutral_framing(self):
        # Boolean has no frame-change axis; a non-neutral value is an explicit error.
        flag, err = configuration_flag("boolean", "incremental", "linear")
        assert flag is None
        assert "frame-change" in err


class TestEncodeIoCorticalId:
    """Canonical 8-byte id encoding for count IPU/OPU areas."""

    def test_count_input_matches_trainer_id(self):
        result = encode_io_cortical_id("icnt")
        assert result["ok"] is True
        assert result["cortical_id"] == "aWNudAEAAAA="
        assert result["config_flag"] == 1
        assert result["io_kind"] == "sensory"

    def test_count_output_matches_trainer_id(self):
        result = encode_io_cortical_id("ocnt")
        assert result["ok"] is True
        assert result["cortical_id"] == "b2NudAEAAAA="
        assert result["io_kind"] == "motor_output"

    def test_round_trips_through_decoder(self):
        encoded = encode_io_cortical_id(
            "icnt", framing="incremental", positioning="fractional", unit_index=2
        )
        decoded = decode_cortical_id_interpretation(encoded["cortical_id"])
        assert decoded["ok"] is True
        assert decoded["subtype_4char"] == "icnt"
        assert decoded["cortical_unit_index"] == 2
        assert decoded["config_bytes_4_5"] == encoded["config_bytes_4_5"]

    def test_unit_and_subunit_indices_land_in_bytes(self):
        result = encode_io_cortical_id("ocnt", unit_index=5, subunit_index=3)
        decoded = decode_cortical_id_interpretation(result["cortical_id"])
        assert decoded["cortical_unit_index"] == 5
        assert decoded["cortical_subunit_index"] == 3

    def test_rejects_wrong_length_subtype(self):
        result = encode_io_cortical_id("icn")
        assert result["ok"] is False
        assert "4 chars" in result["error"]

    def test_rejects_bad_direction(self):
        result = encode_io_cortical_id("xcnt")
        assert result["ok"] is False
        assert "input" in result["error"]

    def test_rejects_out_of_range_unit_index(self):
        result = encode_io_cortical_id("icnt", unit_index=256)
        assert result["ok"] is False
        assert "0..255" in result["error"]
