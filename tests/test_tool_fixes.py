"""Regression tests for tool fixes: IO area sizing and name, log tail default, plastic-rule
validation, relay-template PSP distribution, and ``steps_file``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp import server
from feagi_mcp.circuit_spec import expand_spec
from feagi_mcp.feagi_client import LOG_TAIL_DEFAULT_LIMIT, FeagiClient
from feagi_mcp.steps_file import load_steps_file


@pytest.fixture
def client() -> FeagiClient:
    c = FeagiClient()
    c._client = AsyncMock()
    return c


def _ok(data: Any) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = data
    return r


# ---- 1. create_io_area_for_unit
async def test_io_area_channels_is_total_width_and_name_applied(client: FeagiClient) -> None:
    client._client.post.return_value = _ok({"cortical_id": "aWNudAEAAAA="})
    client.update_cortical_area = AsyncMock(return_value={"success": True})  # type: ignore[method-assign]
    res = await client.create_io_area_for_unit(
        name="Wanted", subtype="icnt", channels=7, depth=1, device_count=7
    )
    body = client._client.post.call_args.kwargs["json"]
    assert body["per_device_dimensions"][0] == 1 and body["device_count"] == 7
    assert body["per_device_dimensions"][0] * body["device_count"] == 7
    client.update_cortical_area.assert_awaited_once_with(
        "aWNudAEAAAA=", {"cortical_name": "Wanted"}
    )
    assert res["name_result"] == {"success": True}


async def test_io_area_uneven_channels_is_an_error(client: FeagiClient) -> None:
    client._client.post = AsyncMock()
    res = await client.create_io_area_for_unit(
        name="x", subtype="icnt", channels=7, depth=1, device_count=2
    )
    assert res["error"] == "invalid_channels"
    client._client.post.assert_not_awaited()


# ---- 2. get_log_tail default limit
async def test_log_tail_defaults_limit(client: FeagiClient) -> None:
    client._client.get.return_value = _ok({"enabled": True, "records": [], "returned": 0})
    await client.get_log_tail()
    assert client._client.get.call_args.kwargs["params"]["limit"] == str(LOG_TAIL_DEFAULT_LIMIT)
    assert LOG_TAIL_DEFAULT_LIMIT == 200


# ---- 3. plastic rule validation shared by dry run and real run
@pytest.mark.parametrize("missing", ["ltd_multiplier", "ltp_multiplier"])
def test_plastic_associative_rule_without_multiplier_fails_dry_run(missing: str) -> None:
    rule: dict[str, Any] = {
        "morphology": "associative_memory",
        "psc": 1,
        "plasticity_mode": "stdp",
        "plasticity_window": 3,
        "plasticity_constant": 1,
        "ltp_multiplier": 1,
        "ltd_multiplier": 1,
    }
    del rule[missing]
    spec = {
        "region": {"title": "R"},
        "areas": [
            {"name": "Mem", "dimensions": [1, 1, 1], "cortical_type": "MEMORY"},
            {"name": "Out", "dimensions": [1, 1, 1]},
        ],
        "mappings": [{"src": "Mem", "dst": "Out", "rules": [rule]}],
    }
    report, _ = expand_spec(spec)
    assert not report["valid"]
    assert any(missing in e for e in report["errors"])


# ---- 4. psp uniform in relay templates
def test_port_and_onset_pulse_set_psp_uniform() -> None:
    spec = {
        "region": {"title": "R", "coordinates_2d": [0, 0], "coordinates_3d": [100, 100, 100]},
        "defaults": {"origin": [0, 0, 0]},
        "areas": [{"name": "Gate", "dimensions": [1, 1, 1], "position": [1, 1, 1]}],
        "templates": [
            {"template": "port", "name": "P", "bins": 2, "threshold": 1, "psp": 1, "input": 1},
            {"template": "onset_pulse", "name": "O", "gate": "Gate"},
        ],
    }
    report, plan = expand_spec(spec)
    assert report["valid"], report["errors"]
    for a in plan.areas:
        if a["name"] in ("P", "O_Onset", "O_Delay"):
            assert a["properties"]["neuron_psp_uniform_distribution"] is True


# ---- 5. steps_file
def test_load_steps_file_errors(tmp_path: Path) -> None:
    assert "does not exist" in (load_steps_file(str(tmp_path / "nope.json"))[1] or "")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert "not valid JSON" in (load_steps_file(str(bad))[1] or "")
    obj = tmp_path / "obj.json"
    obj.write_text("{}")
    assert "JSON list" in (load_steps_file(str(obj))[1] or "")
    empty = tmp_path / "e.json"
    empty.write_text("[]")
    assert "empty" in (load_steps_file(str(empty))[1] or "")
    item = tmp_path / "i.json"
    item.write_text("[1]")
    assert "item 0" in (load_steps_file(str(item))[1] or "")


async def test_run_stimulus_protocol_reads_steps_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "s.json"
    steps = [{"bursts": 2, "stimuli": []}]
    f.write_text(json.dumps(steps))
    fake = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(server.feagi, "run_stimulus_protocol", fake)
    out = await server.run_stimulus_protocol(record_areas=["a"], steps_file=str(f))
    assert out == {"success": True}
    assert fake.call_args.args[0] == steps
    both = await server.run_stimulus_protocol(steps=steps, record_areas=["a"], steps_file=str(f))
    assert both["success"] is False and "not both" in both["error"]
    none = await server.run_stimulus_protocol(record_areas=["a"])
    assert none["success"] is False


async def test_schedule_stimulus_reads_steps_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "e.json"
    entries = [{"burst_offset": 0, "stimuli": [{"area_id": "a", "coordinates": [[0, 0, 0]]}]}]
    f.write_text(json.dumps(entries))
    fake = AsyncMock(return_value={"schedule_id": 1})
    monkeypatch.setattr(server.feagi, "schedule_stimulus", fake)
    out = await server.schedule_stimulus(steps_file=str(f))
    assert out == {"schedule_id": 1} and fake.call_args.args[0] == entries
    bad = await server.schedule_stimulus(steps_file=str(tmp_path / "missing.json"))
    assert bad["success"] is False
