"""Optional ``potential`` on manual stimulation and stimulus schedules (mocked HTTP)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.stimulus_hold import check_applied_potential, run_hold, validate_potential

AREA = "area_a"


class Resp:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self) -> Any:
        return self._data


class Http:
    """Records posts; echoes ``applied_potential`` unless ``old_server`` (field ignored)."""

    def __init__(self, old_server: bool = False, applied: float | None = None) -> None:
        self.old_server = old_server
        self.applied = applied
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.counter = 0

    async def get(self, url: str) -> Resp:
        if url.endswith("/burst_counter"):
            self.counter += 1
            return Resp(self.counter)
        if url.endswith("/burst_engine/config"):
            return Resp({"burst_interval_seconds": 0.001})
        raise AssertionError(url)

    async def post(self, url: str, json: dict[str, Any]) -> Resp:
        self.posts.append((url, json))
        data: dict[str, Any] = {"success": True, "unique_neuron_ids": 1, "matched_coordinates": 1}
        if url.endswith("stimulus_schedule"):
            data = {"schedule_id": 7, "start_burst": 1, "end_burst": 2}
        sent = json.get("potential")
        if sent is None and json.get("entries"):
            sent = json["entries"][0].get("potential")
        if sent is not None and not self.old_server:
            data["applied_potential"] = self.applied if self.applied is not None else sent
        return Resp(data)


def _client(http: Http) -> FeagiClient:
    client = FeagiClient(host="localhost", port=8000)
    client._client = http  # type: ignore[assignment]

    async def _known(*refs: str) -> tuple[list[str], None]:
        return list(refs), None

    client._resolve_known_areas = _known  # type: ignore[method-assign]
    client._resolve_area_refs = _known  # type: ignore[method-assign]
    return client


async def test_body_has_potential_only_when_given() -> None:
    http = Http()
    client = _client(http)
    without = await client.stimulate_area(AREA, [0, 0, 0])
    assert http.posts[-1][1] == {"stimulation_payload": {AREA: [[0, 0, 0]]}, "mode": "force_fire"}
    assert "applied_potential" not in without and without["success"] is True
    with_p = await client.stimulate_area(AREA, [0, 0, 0], 40.0)
    assert http.posts[-1][1] == {
        "stimulation_payload": {AREA: [[0, 0, 0]]},
        "mode": "force_fire",
        "potential": 40.0,
    }
    assert with_p["success"] is True and with_p["applied_potential"] == 40.0


@pytest.mark.parametrize("bad", [0, -1.0, math.nan, math.inf, -math.inf, True, "5"])
async def test_invalid_potential_rejected_before_any_request(bad: Any) -> None:
    assert validate_potential(bad) is not None
    http = Http()
    client = _client(http)
    results = [
        await client.stimulate_area(AREA, [0, 0, 0], bad),
        await client.stimulate_area_batch(AREA, [[0, 0, 0]], potential=bad),
        await client.hold_stimulus(AREA, [[0, 0, 0]], 0.1, potential=bad),
        await client.schedule_stimulus(
            [{"burst_offset": 0, "stimuli": [{"area_id": AREA, "coordinates": [[0, 0, 0]]}]}],
            potential=bad,
        ),
        await client.run_stimulus_protocol([{"bursts": 1, "stimuli": []}], [AREA], potential=bad),
    ]
    assert all(r["success"] is False and "potential" in r["error"] for r in results)
    assert http.posts == []


async def test_old_server_without_applied_potential_is_an_error() -> None:
    client = _client(Http(old_server=True))
    result = await client.stimulate_area(AREA, [0, 0, 0], 40.0)
    assert result["success"] is False
    assert "did not apply the requested potential 40" in result["error"]
    assert "Update FEAGI" in result["error"]
    # no potential requested: an old server is fine
    assert (await client.stimulate_area(AREA, [0, 0, 0]))["success"] is True


async def test_mismatched_applied_potential_is_an_error() -> None:
    result = await _client(Http(applied=100.0)).stimulate_area(AREA, [0, 0, 0], 40.0)
    assert result["success"] is False and "applied_potential=100.0" in result["error"]
    assert check_applied_potential(40.0, {"applied_potential": 40.0000001}) is None
    assert check_applied_potential(None, {}) is None


async def test_batch_and_hold_by_bursts_carry_potential() -> None:
    http = Http()
    client = _client(http)
    res = await client.stimulate_area_batch(AREA, [[0, 0, 0], [1, 0, 0]], bursts=2, potential=25.0)
    assert res["success"] is True and res["applied_potential"] == 25.0
    assert len(http.posts) == 2 and all(b["potential"] == 25.0 for _, b in http.posts)


async def test_hold_stimulus_posts_potential_and_reports_applied() -> None:
    http = Http()
    client = _client(http)
    out = await client.hold_stimulus(AREA, [[0, 0, 1]], 0.02, verify=False, potential=30.0)
    assert out["state"] == "done" and out["applied_potential"] == 30.0
    assert http.posts and all(b["potential"] == 30.0 for _, b in http.posts)


async def test_hold_stimulus_on_old_server_records_failures() -> None:
    http = Http(old_server=True)
    client = _client(http)
    out = await client.hold_stimulus(AREA, [[0, 0, 1]], 0.02, verify=False, potential=30.0)
    assert out["post_failures"] == out["posts_sent"] > 0
    assert "did not apply the requested potential" in out["first_failure"]


async def test_run_hold_passes_potential_positionally_to_the_post() -> None:
    seen: list[float | None] = []

    class C:
        async def get_burst_engine_config(self) -> dict[str, Any]:
            return {"burst_interval_seconds": 0.001}

        async def get_burst_counter(self) -> dict[str, Any]:
            return {"burst_counter": 1}

        async def _post_stimulation(self, p: Any, m: str, potential: float | None = None) -> Any:
            assert p and m == "force_fire"
            seen.append(potential)
            return {"success": True}

    state = {"_cancel": __import__("asyncio").Event(), "state": "pending"}
    await run_hold(C(), state, AREA, [[0, 0, 1]], 0.01, 0.0, False, 12.5)
    assert seen and set(seen) == {12.5}


async def test_schedule_sends_potential_on_every_entry() -> None:
    http = Http()
    client = _client(http)
    entries = [
        {"burst_offset": 0, "stimuli": [{"area_id": AREA, "coordinates": [[0, 0, 0]]}]},
        {"burst_offset": 2, "stimuli": [{"area_id": AREA, "coordinates": [[1, 0, 0]]}]},
    ]
    out = await client.schedule_stimulus(entries, potential=55.0)
    sent = http.posts[-1][1]["entries"]
    assert [e["potential"] for e in sent] == [55.0, 55.0]
    assert out["success"] is True and out["applied_potential"] == 55.0
    await client.schedule_stimulus(entries)
    assert all("potential" not in e for e in http.posts[-1][1]["entries"])
    old = await _client(Http(old_server=True)).schedule_stimulus(entries, potential=55.0)
    assert old["success"] is False and "did not apply" in old["error"]


async def test_protocol_posts_potential_and_surfaces_applied() -> None:
    http = Http()
    client = _client(http)

    async def fq() -> dict[str, Any]:
        return {"timestep": http.counter, "sample_available": False}

    client.get_fire_queue_detailed = fq  # type: ignore[method-assign]
    steps = [{"bursts": 2, "stimuli": [{"area_id": AREA, "coordinates": [[0, 0, 0]]}]}]
    out = await client.run_stimulus_protocol(steps, [AREA], potential=70.0)
    assert out["success"] is True and out["applied_potential"] == 70.0
    assert http.posts and all(b["potential"] == 70.0 for _, b in http.posts)
    bad = await _client(Http(old_server=True)).run_stimulus_protocol(steps, [AREA], potential=70.0)
    assert bad["success"] is False and "did not apply" in bad["error"]


async def test_schedule_stimulus_rejects_unsupported_bursts_field() -> None:
    http = Http()
    entries = [
        {"burst_offset": 0, "bursts": 5, "stimuli": [{"area_id": AREA, "coordinates": [[0, 0, 0]]}]}
    ]
    out = await _client(http).schedule_stimulus(entries)
    assert out["success"] is False
    assert "bursts" in out["error"] and "hold_stimulus" in out["error"]
    assert http.posts == []
