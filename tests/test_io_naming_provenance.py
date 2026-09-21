"""Tests for compact I/O area naming provenance helpers."""

from feagi_mcp.io_naming_provenance import (
    build_area_naming_explanation,
    compose_naming_cause,
    split_registration_title,
    summarize_motor_groups_from_registrations,
)


def _muscle_registration() -> dict:
    return {
        "output_units_and_decoder_properties": {
            "PositionalServo": [
                [
                    {
                        "cortical_unit_index": 0,
                        "friendly_name": "ungrouped",
                        "io_configuration_flags": {"frame_change_handling": "Absolute"},
                        "device_grouping": [
                            {
                                "friendly_name": "IL_L1_l",
                                "device_properties": {
                                    "joint_name": {"type": "String", "value": ""},
                                    "actuator_name": {"type": "String", "value": "IL_L1_l"},
                                    "bundle_id": {"type": "String", "value": "ungrouped"},
                                },
                            },
                            {
                                "friendly_name": "rect_abd_l",
                                "device_properties": {
                                    "joint_name": {"type": "String", "value": ""},
                                    "actuator_name": {
                                        "type": "String",
                                        "value": "rect_abd_l",
                                    },
                                    "bundle_id": {"type": "String", "value": "ungrouped"},
                                },
                            },
                        ],
                    },
                    {"PositionalServo": [{"value": 10}, "Linear"]},
                ]
            ]
        }
    }


def test_summarize_motor_groups_is_one_row_not_per_channel():
    groups = summarize_motor_groups_from_registrations(_muscle_registration())
    assert len(groups) == 1
    row = groups[0]
    assert row["friendly_name"] == "ungrouped"
    assert row["channel_count"] == 2
    assert row["empty_joint_name_count"] == 2
    assert row["is_catch_all"] is True
    assert row["sample_actuator_names"] == ["IL_L1_l", "rect_abd_l"]
    assert "device_grouping" not in row


def test_split_registration_title_strips_subunit_suffix():
    parts = split_registration_title("ungrouped-1", 1)
    assert parts["group_title"] == "ungrouped"
    assert parts["subunit_suffix"] == "1"


def test_explain_payload_stays_compact_and_names_catch_all():
    payload = build_area_naming_explanation(
        "b3BzZREBAAA=",
        {
            "cortical_name": "ungrouped-1",
            "cortical_subtype": "opse",
            "unit_id": 0,
            "subunit_id": 1,
            "encoding_type": "Incremental",
            "dev_count": 416,
        },
        [
            {
                "agent_id": "myo_agent",
                "agent_name": "myosuite_scene_muscl",
                "group": {
                    "friendly_name": "ungrouped",
                    "unit_id": 0,
                    "is_catch_all": True,
                    "channel_count": 416,
                },
            }
        ],
    )
    assert payload["name_parts"]["group_title"] == "ungrouped"
    assert payload["id_layout"]["cortical_subunit_index"] == 1
    assert payload["id_layout"]["frame_change_handling"] == "Incremental"
    assert "catch-all" in payload["naming_cause"]
    assert "sub-area 1" in payload["naming_cause"]
    assert "device_grouping" not in str(payload["matching_groups"])


def test_compose_naming_cause_without_registration():
    cause = compose_naming_cause(
        title_parts={"group_title": "motor_opu", "subunit_suffix": None},
        subunit_id=None,
        encoding=None,
        matched_group=None,
    )
    assert "motor_opu" in cause
