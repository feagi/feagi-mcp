"""Unit tests for local connectivity-rule authoring and validation."""

from __future__ import annotations

from feagi_mcp.connectivity_rules import (
    ENUMERATED_PATTERN_REJECT_THRESHOLD,
    analyze_patterns,
    build_connectivity_proposal,
    compact_source_x_filter_patterns,
    dest_kind_from_cortical_id,
    motor_z_errors_for_patterns,
    validate_morphology_parameters,
    validate_pattern_element,
)

# Live ungrouped-0 PositionalServo absolute id (subunit 0).
_OPSE_ABS = "b3BzZQEAAAA="


class TestPatternTokens:
    def test_accepts_language_tokens(self):
        for token in (
            "*",
            "?",
            "!",
            "?+",
            "?-",
            "?+=",
            "?-=",
            "?+17",
            "?-2",
            "?-1:?+1",
            "1..98",
        ):
            assert validate_pattern_element(token) is None
        assert validate_pattern_element(0) is None
        assert validate_pattern_element(-2) is None

    def test_rejects_unknown_string_instead_of_treating_as_wildcard(self):
        err = validate_pattern_element("even")
        assert err is not None
        assert "unknown pattern token" in err


class TestAnalyzePatterns:
    def test_accepts_compact_identity(self):
        out = analyze_patterns([[["*", "*", "*"], ["?", "?", "?"]]])
        assert out["ok"] is True
        assert out["reject"] is False

    def test_rejects_enumerated_constant_offset_dump(self):
        patterns = []
        for x in range(4):
            for z in range(2):
                patterns.append([[x, 0, z], [x, 0, z + 17]])
        assert len(patterns) >= ENUMERATED_PATTERN_REJECT_THRESHOLD
        out = analyze_patterns(patterns)
        assert out["reject"] is True
        compact = out["compact_form"]["parameters"]["patterns"]
        assert compact == [[["0..3", "*", "*"], ["?", "?", "?+17"]]]

    def test_allows_small_irregular_exact_table(self):
        out = analyze_patterns(
            [
                [[0, 0, 0], [0, 0, 4]],
                [[0, 0, 1], [0, 0, 3]],
            ]
        )
        assert out["ok"] is True
        assert out["reject"] is False

    def test_rejects_enumerated_source_x_filters(self):
        patterns = [[[x, "*", "*"], ["?", "?", 0]] for x in range(10)]
        out = analyze_patterns(patterns)
        assert out["reject"] is True
        assert out["compact_form"]["parameters"]["patterns"] == [
            [["0..9", "*", "*"], ["?", "?", 0]]
        ]


class TestCompactSourceXFilters:
    def test_merges_contiguous_and_keeps_gaps(self):
        patterns = [
            [[1, "*", "*"], ["?", "?", 0]],
            [[2, "*", "*"], ["?", "?", 0]],
            [[3, "*", "*"], ["?", "?", 0]],
            [[98, "*", "*"], ["?", "?", 0]],
        ]
        assert compact_source_x_filter_patterns(patterns) == [
            [["1..3", "*", "*"], ["?", "?", 0]],
            [[98, "*", "*"], ["?", "?", 0]],
        ]

    def test_returns_none_when_already_compact(self):
        patterns = [
            [["1..3", "*", "*"], ["?", "?", 0]],
            [[98, "*", "*"], ["?", "?", 0]],
        ]
        assert compact_source_x_filter_patterns(patterns) is None


class TestMotorZ:
    def test_opse_absolute_detected(self):
        assert dest_kind_from_cortical_id(_OPSE_ABS) == "positional_servo_absolute"

    def test_rejects_high_z_on_absolute_servo(self):
        errors = motor_z_errors_for_patterns(
            [[[382, "*", "*"], ["?", "?", 17]]],
            dest_kind_from_cortical_id(_OPSE_ABS),
        )
        assert errors
        assert "z=0 is max" in errors[0]

    def test_allows_dest_z_zero_on_absolute_servo(self):
        errors = motor_z_errors_for_patterns(
            [[[382, "*", "*"], ["?", "?", 0]]],
            dest_kind_from_cortical_id(_OPSE_ABS),
        )
        assert errors == []


class TestPropose:
    def test_sit_requires_channels_on_servo(self):
        out = build_connectivity_proposal(
            "sit motor",
            dest_kind=dest_kind_from_cortical_id(_OPSE_ABS),
        )
        assert out["error"]
        assert "source_x_channels" in out["error"]
        assert out["custom"] is None
        assert out["full_area_form"]["parameters"]["patterns"] == [[["*", "*", "*"], ["?", "?", 0]]]

    def test_sit_emits_one_pattern_per_channel_at_z0(self):
        out = build_connectivity_proposal(
            "sit motor",
            dest_kind=dest_kind_from_cortical_id(_OPSE_ABS),
            source_x_channels=[394, 382, 382],
        )
        assert out["error"] is None
        assert out["custom"]["parameters"]["patterns"] == [
            [[382, "*", "*"], ["?", "?", 0]],
            [[394, "*", "*"], ["?", "?", 0]],
        ]

    def test_sit_collapses_contiguous_channels_to_absolute_range(self):
        out = build_connectivity_proposal(
            "sit motor",
            dest_kind=dest_kind_from_cortical_id(_OPSE_ABS),
            source_x_channels=[1, 2, 3, 98],
        )
        assert out["error"] is None
        assert out["custom"]["parameters"]["patterns"] == [
            [["1..3", "*", "*"], ["?", "?", 0]],
            [[98, "*", "*"], ["?", "?", 0]],
        ]

    def test_offset_on_servo_is_rejected(self):
        out = build_connectivity_proposal(
            "z offset",
            dest_kind=dest_kind_from_cortical_id(_OPSE_ABS),
            z_offset=17,
        )
        assert out["error"]
        assert "invert" in out["error"]

    def test_offset_on_custom_uses_one_vector(self):
        out = build_connectivity_proposal("z offset", dest_kind="custom", z_offset=17)
        assert out["error"] is None
        assert out["custom"]["parameters"]["vectors"] == [[0, 0, 17]]
        assert out["custom"]["pattern_equivalent"]["parameters"]["patterns"] == [
            [["*", "*", "*"], ["?", "?", "?+17"]]
        ]

    def test_identity_reuses_block_to_block(self):
        out = build_connectivity_proposal("one-to-one identity")
        assert out["reuse"]["morphology_id"] == "block_to_block"

    def test_broadcast_from_single_voxel_reuses_core_fanout(self):
        out = build_connectivity_proposal(
            "broadcast projector",
            src_dimensions=[1, 1, 1],
        )
        assert out["reuse"]["morphology_id"] == "0-0-0_to_all"


class TestValidateMorphologyParameters:
    def test_vectors_require_triples(self):
        out = validate_morphology_parameters("vectors", {"vectors": [[0, 0]]})
        assert out["reject"] is True
