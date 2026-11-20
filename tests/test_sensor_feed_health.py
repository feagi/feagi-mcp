"""feed_stalled: a registered sensory agent whose IPU areas show no sensor data."""

from __future__ import annotations

from typing import Any

from feagi_mcp.sensor_feed_health import feed_stalled_findings
from tests.io_fixtures import registration

IPU_A = "IPUA0000001="
IPU_B = "IPUB0000001="


def _caps(sensory: bool, index: int = 0) -> dict[str, Any]:
    return {
        "agent_name": "ctl",
        "capabilities": {"sensory": sensory},
        "device_registrations": {
            "input_units_and_encoder_properties": registration("Servo", index=index)[
                "output_units_and_decoder_properties"
            ]
        },
    }


def _areas() -> dict[str, dict[str, Any]]:
    base = {"cortical_group": "IPU", "cortical_dimensions": [3, 1, 101], "subunit_id": 0}
    return {IPU_A: {**base, "unit_id": 0, "cortical_name": "pos"}}


def _snap(*ids: str) -> dict[str, Any]:
    return {"areas": [{"cortical_id": i, "neuron_count": 3, "samples": [{"x": 0}]} for i in ids]}


def test_stalled_agent_is_flagged() -> None:
    out = feed_stalled_findings({"a": _caps(True)}, _areas(), [_snap(), _snap()])
    assert len(out) == 1
    assert out[0]["check"] == "feed_stalled"
    assert out[0]["agent_id"] == "a"
    assert [x["cortical_id"] for x in out[0]["silent_ipu_areas"]] == [IPU_A]


def test_partial_feed_is_a_warning() -> None:
    areas = _areas()
    areas[IPU_B] = {**areas[IPU_A], "unit_id": 1, "cortical_name": "link"}
    caps = _caps(True)
    units = caps["device_registrations"]["input_units_and_encoder_properties"]
    units["Servo"].append(
        registration("Servo", index=1)["output_units_and_decoder_properties"]["Servo"][0]
    )
    out = feed_stalled_findings({"a": caps}, areas, [_snap(IPU_B), _snap(IPU_B)])
    assert [f["check"] for f in out] == ["feed_partial"]
    assert out[0]["severity"] == "warning"
    assert [x["cortical_id"] for x in out[0]["silent_ipu_areas"]] == [IPU_A]


def test_healthy_agent_is_not_flagged() -> None:
    assert feed_stalled_findings({"a": _caps(True)}, _areas(), [_snap(), _snap(IPU_A)]) == []


def test_non_sensory_agent_is_ignored() -> None:
    assert feed_stalled_findings({"a": _caps(False)}, _areas(), [_snap(), _snap()]) == []
