"""Block datasheet: author validators, port contract check, Composer client, tool registration."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp import composer_datasheet, server
from feagi_mcp.composer_datasheet import ComposerDatasheetClient
from feagi_mcp.datasheet import (
    CODE_ENUM,
    CODE_SOURCE_ENUM,
    FRAME_ENUM,
    KIND_ENUM,
    MANDATORY_PORT_KEYS,
    POSITIONING_ENUM,
    VOCABULARY_PATH,
    check_port_contract,
    live_area_from_properties,
    missing_mandatory_keys,
    validate_author_fields,
)
from feagi_mcp.io_cortical_id_encode import encode_io_cortical_id


def _doc() -> dict[str, Any]:
    return {
        "format": "feagi.datasheet/1",
        "block": {"name": "hold-level", "behavior": "Holds an output level."},
        "level": "characterised",
        "burst": {"timestep_s": 0.02},
        "ports": [
            {
                "name": "in_a",
                "area_id": "abc",
                "dir": "in",
                "shape": [1, 1, 8],
                "code": "thermometer",
                "min_bins_that_pass": 4,
                "function": "Level in.",
                "code_source": "measured",
                "kind": "Percentage",
                "signed": False,
                "frame": "Absolute",
                "positioning": "Linear",
                "hold": None,
                "zero": "No input.",
                "positive": "Raises the output.",
                "if_silent": None,
                "fits": [{"io_kind": "Percentage", "frame": "Absolute", "min_bins": 4}],
            }
        ],
        "measured": [{"from": "in_a", "to": "out_a", "sign": "+", "gain": 1.5, "lag_bursts": 2}],
    }


def test_valid_doc_ignores_generated_fields() -> None:
    assert validate_author_fields(_doc()) == []


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda d: d.update(extra=1), "unknown key 'extra'"),
        (lambda d: d["ports"][0].update(code="analog"), "ports[0].code"),
        (lambda d: d["ports"][0].update(persistence="level"), "unknown key 'persistence'"),
        (lambda d: d["ports"][0].update(fail_behavior="x"), "unknown key 'fail_behavior'"),
        (lambda d: d["ports"][0].update(kind="Analog"), "ports[0].kind"),
        (lambda d: d["ports"][0].update(frame="Relative"), "ports[0].frame"),
        (lambda d: d["ports"][0].update(positioning="Log"), "ports[0].positioning"),
        (lambda d: d["ports"][0].update(code_source="guessed"), "ports[0].code_source"),
        (lambda d: d["ports"][0].update(signed="yes"), "ports[0].signed"),
        (lambda d: d["ports"][0].update(signed=True), "requires signed false"),
        (
            lambda d: d["ports"][0].update(kind="SignedPercentage2D", signed=False),
            "requires signed true",
        ),
        (lambda d: d["ports"][0].update(fits=[{}] * 9), "exceeds the cap of 8"),
        (lambda d: d["ports"][0].update(fits=[{"frame": "x"}]), "fits[0].frame"),
        (lambda d: d["ports"][0].update(fits=[{"bogus": 1}]), "unknown key 'bogus'"),
        (lambda d: d["measured"][0].update(gate="no"), "measured[0].gate"),
        (lambda d: d["ports"][0].update(min_bins_that_pass=0), "min_bins_that_pass"),
        (lambda d: d["ports"][0].update(function="x" * 2001), "2001 chars"),
        (lambda d: d["ports"][0].update(bogus=1), "unknown key 'bogus'"),
        (lambda d: d.update(ports=[{"name": f"p{i}"} for i in range(65)]), "exceeds the cap of 64"),
        (lambda d: d.update(mistakes=["m"] * 21), "mistakes"),
        (lambda d: d.update(format="feagi.datasheet/2"), "format"),
        (lambda d: d["measured"][0].update(lag_bursts=1.5), "lag_bursts"),
        (lambda d: d.update(notes=[{"body": "a", "html": "<b>"}]), "unknown key 'html'"),
        (
            lambda d: d.update(measured=[{"test": "t" * 2000}] * 64, mistakes=["y" * 2000] * 5),
            "bytes",
        ),
    ],
)
def test_invalid_author_fields(mutate: Any, needle: str) -> None:
    doc = _doc()
    mutate(doc)
    assert any(needle in p for p in validate_author_fields(doc)), validate_author_fields(doc)


def test_null_is_unknown_and_absent_is_reported() -> None:
    doc = _doc()
    for key in MANDATORY_PORT_KEYS:
        doc["ports"][0][key] = None
    assert validate_author_fields(doc) == []
    assert missing_mandatory_keys(doc) == []
    del doc["ports"][0]["hold"], doc["ports"][0]["signed"]
    assert validate_author_fields(doc) == []
    missing = missing_mandatory_keys(doc)
    assert len(missing) == 2 and any("'hold'" in m for m in missing)
    assert any("'signed'" in m for m in missing)


def test_enums_equal_shared_vocabulary() -> None:
    vocab = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))
    assert set(vocab) == {"code", "code_source", "kind", "frame", "positioning"}
    assert list(CODE_ENUM) == vocab["code"]
    assert list(CODE_SOURCE_ENUM) == vocab["code_source"]
    assert list(KIND_ENUM) == vocab["kind"]
    assert list(FRAME_ENUM) == vocab["frame"]
    assert list(POSITIONING_ENUM) == vocab["positioning"]


def test_non_object_rejected() -> None:
    assert validate_author_fields([]) == ["datasheet: must be an object"]


_ROW: dict[str, Any] = {
    "name": "in_a",
    "dir": "in",
    "shape": [1, 1, 8],
    "code": "thermometer",
    "min_bins_that_pass": 4,
    "drive": {"threshold": 1.0, "psp": 2.0, "leak": 0.0, "refractory": 1, "accumulate": True},
    "latency_bursts": 2,
}


def _live(**over: Any) -> dict[str, Any]:
    live: dict[str, Any] = {
        "shape": [1, 1, 8],
        "code": "thermometer",
        "bins": 6,
        "threshold": 1.0,
        "psp": 2.0,
        "leak": 0.0,
        "refractory": 1,
        "accumulate": True,
    }
    live.update(over)
    return live


def _by(result: dict[str, Any]) -> dict[str, str]:
    return {c["check"]: c["status"] for c in result["checks"]}


def test_port_pass() -> None:
    r = check_port_contract(_ROW, _live())
    assert r["passed"] is True and r["failed_checks"] == []
    assert _by(r)["latency_bursts"] == "skipped" and _by(r)["dir"] == "skipped"


def test_port_shape_mismatch() -> None:
    r = check_port_contract(_ROW, _live(shape=[1, 1, 4]))
    assert r["passed"] is False and r["failed_checks"] == ["shape"]
    shape = next(c for c in r["checks"] if c["check"] == "shape")
    assert shape["expected"] == [1, 1, 8] and shape["observed"] == [1, 1, 4]


def test_port_code_mismatch() -> None:
    r = check_port_contract(_ROW, _live(code="one-hot"))
    assert r["failed_checks"] == ["code"]


def test_port_bins_below_min() -> None:
    r = check_port_contract(_ROW, _live(bins=3))
    assert r["failed_checks"] == ["bins"]
    assert check_port_contract(_ROW, _live(bins=4))["passed"] is True


def test_port_drive_outside_tolerance() -> None:
    assert check_port_contract(_ROW, _live(psp=2.1))["failed_checks"] == ["drive.psp"]
    assert check_port_contract(_ROW, _live(psp=2.1), drive_rel_tolerance=0.1)["passed"] is True
    row = {**_ROW, "drive": {**_ROW["drive"], "tolerance_rel": 0.01}}
    assert check_port_contract(row, _live(psp=2.1))["failed_checks"] == ["drive.psp"]


def test_port_latency_and_probe() -> None:
    assert check_port_contract(_ROW, _live(observed_latency_bursts=5))["failed_checks"] == [
        "latency_bursts"
    ]
    ok = check_port_contract(_ROW, _live(observed_latency_bursts=3), latency_tolerance_bursts=1)
    assert ok["passed"] is True
    assert check_port_contract(_ROW, _live(responded=False))["failed_checks"] == ["path_responds"]


def test_all_skipped_is_none() -> None:
    assert check_port_contract({"name": "p"}, {})["passed"] is None


def test_live_area_projection() -> None:
    props = {
        "cortical_dimensions": {"x": 1, "y": 2, "z": 3},
        "neuron_fire_threshold": 1.0,
        "neuron_mp_charge_accumulation": True,
    }
    live = live_area_from_properties(props)
    assert live["shape"] == [1, 2, 3] and live["threshold"] == 1.0 and live["accumulate"] is True
    assert live_area_from_properties({"cortical_dimensions": [1, 2, 3]})["shape"] == [1, 2, 3]


def _io_live(variant: str = "percentage", **over: Any) -> dict[str, Any]:
    cid = encode_io_cortical_id(
        "ipro", variant=variant, framing="absolute", positioning="linear", unit_index=0
    )["cortical_id"]
    props: dict[str, Any] = {
        "cortical_dimensions": {"x": 6, "y": 2, "z": 10},
        "dev_count": 3,
        "encoding_type": "Absolute",
        "encoding_format": "Linear",
    }
    props.update(over)
    return live_area_from_properties(props, cid)


_IO_ROW: dict[str, Any] = {
    "name": "in_a",
    "kind": "Percentage",
    "signed": False,
    "frame": "Absolute",
    "positioning": "Linear",
    "shape": [2, 2, 8],
    "min_bins_that_pass": 4,
    "fits": [{"io_kind": "Percentage", "frame": "Absolute", "min_bins": 6}],
}


def test_io_projection_uses_per_device_x() -> None:
    live = _io_live()
    assert live["shape"] == [6, 2, 10] and live["per_device_shape"] == [2, 2, 10]
    assert live["kind"] == "Percentage" and live["signed"] is False


def test_io_port_pass_and_fits() -> None:
    r = check_port_contract(_IO_ROW, _io_live())
    assert r["passed"] is True, r
    by = _by(r)
    assert all(by[k] == "pass" for k in ("kind", "signed", "frame", "positioning", "shape_xy"))
    assert by["fits"] == "pass" and by["z_depth"] == "pass" and "shape" not in by
    assert any("different" in n for n in r["advisory"])


def test_io_port_mismatches() -> None:
    r = check_port_contract(_IO_ROW, _io_live("signed_percentage"))
    assert {"kind", "signed", "fits"} <= set(r["failed_checks"])
    r = check_port_contract(
        _IO_ROW, _io_live(encoding_type="Incremental", encoding_format="Fractional")
    )
    assert {"frame", "positioning", "fits"} <= set(r["failed_checks"])
    r = check_port_contract(_IO_ROW, _io_live(cortical_dimensions={"x": 6, "y": 2, "z": 5}))
    assert r["failed_checks"] == ["z_depth"]
    r = check_port_contract(_IO_ROW, _io_live(cortical_dimensions={"x": 9, "y": 2, "z": 10}))
    assert r["failed_checks"] == ["shape_xy"]


def test_io_null_datasheet_is_skipped_not_passed() -> None:
    row = {**_IO_ROW, "kind": None, "signed": None, "frame": None, "positioning": None}
    r = check_port_contract(row, _io_live())
    skipped = [c for c in r["checks"] if c["check"] in ("kind", "signed", "frame", "positioning")]
    assert len(skipped) == 4
    assert all(
        c["status"] == "skipped" and "datasheet states no value" in c["detail"] for c in skipped
    )


# --- Composer client -------------------------------------------------------------------


def _resp(status: int, body: Any) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = ""
    return r


@pytest.fixture
def client() -> ComposerDatasheetClient:
    c = ComposerDatasheetClient(base_url="https://composer.example.invalid", timeout=5.0)
    c._client = AsyncMock()  # type: ignore[assignment]
    return c


@pytest.mark.asyncio
async def test_disabled_client() -> None:
    c = ComposerDatasheetClient(base_url=" ", timeout=5.0)
    assert (await c.get_release_datasheet("i", 1))["error"] == "composer_base_url_not_configured"


@pytest.mark.asyncio
async def test_get_release_datasheet(client: ComposerDatasheetClient) -> None:
    sheet = {"format": "feagi.datasheet/1"}
    client._client.get.return_value = _resp(  # type: ignore[union-attr]
        200, {"data": {"datasheet": sheet, "ports_summary": [{"name": "a"}]}}
    )
    out = await client.get_release_datasheet("item 1", 3)
    assert out["datasheet"] == sheet and out["ports_summary"] == [{"name": "a"}]
    path = client._client.get.call_args.args[0]  # type: ignore[union-attr]
    assert path == composer_datasheet.RELEASE_PATH.format(item_id="item%201", version=3)


@pytest.mark.asyncio
async def test_release_without_datasheet_and_http_error(client: ComposerDatasheetClient) -> None:
    client._client.get.return_value = _resp(200, {"data": {"version": 1}})  # type: ignore[union-attr]
    assert (await client.get_release_datasheet("i", 1))["error"] == "no_datasheet"
    client._client.get.return_value = _resp(404, {"detail": "not_found"})  # type: ignore[union-attr]
    out = await client.get_release_datasheet("i", 1)
    assert out["error"] == "not_found" and out["http_status"] == 404


# --- Tools -----------------------------------------------------------------------------


def test_tools_registered() -> None:
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"get_block_datasheet", "check_port_contract"} <= names
    # No authenticated Composer route exists, so the draft tools must not be registered.
    assert not names & {"set_block_datasheet_draft", "preview_block_datasheet"}


@pytest.mark.asyncio
async def test_check_port_contract_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server.feagi,
        "get_area_parameters",
        AsyncMock(return_value={"cortical_dimensions": [1, 1, 4], "neuron_fire_threshold": 1.0}),
    )
    probe = AsyncMock(return_value={"responded": True})
    monkeypatch.setattr(server.feagi, "probe_area_response", probe)
    out = await server.check_port_contract(
        {"name": "p", "shape": [1, 1, 8], "latency_bursts": 2},
        "area",
        latency_probe={
            "stimulus_area": "s",
            "stimulus_voxels": [[0, 0, 0]],
            "observe_area": "o",
            "burst_period_ms": 20,
        },
    )
    assert out["failed_checks"] == ["shape"] and _by(out)["path_responds"] == "pass"
    assert probe.call_args.kwargs["settle_ms"] == 60
    row = {"name": "p", "latency_bursts": 2}
    bad = await server.check_port_contract(row, "a", latency_probe={})
    assert "latency_probe needs" in bad["error"]
    failing = AsyncMock(return_value={"error": "x"})
    monkeypatch.setattr(server.feagi, "get_area_parameters", failing)
    assert (await server.check_port_contract({}, "a"))["error"] == "area_unavailable"
