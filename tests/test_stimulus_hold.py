"""hold_stimulus: argument checks, wall-clock post loop and ledger landing check (mocked)."""

from __future__ import annotations

from typing import Any

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.stimulus_hold import landing_report, new_hold_state, run_hold, validate_hold_args

AREA = "area_a"
VOXELS = [[0, 0, 1], [0, 0, 2]]


class FakeHoldClient:
    """Posts advance a fake burst clock (one burst per two posts); ledger is scripted."""

    def __init__(self, miss: set[int] | None = None, fail_posts: bool = False) -> None:
        self.counter = 500
        self.posts = 0
        self.miss = miss or set()
        self.fail_posts = fail_posts
        self.acquired: list[list[str]] = []
        self.released: list[list[str]] = []

    async def get_burst_engine_config(self) -> dict[str, Any]:
        return {"burst_interval_seconds": 0.002}

    async def get_burst_counter(self) -> dict[str, Any]:
        return {"burst_counter": self.counter}

    async def _post_stimulation(self, payload: dict[str, Any], mode: str) -> dict[str, Any]:
        assert payload == {AREA: VOXELS} and mode == "force_fire"
        self.posts += 1
        if self.posts % 2 == 0:
            self.counter += 1
        if self.fail_posts:
            return {"success": False, "error": "HTTP 500"}
        return {"success": True}

    def acquire_fire_history(self, area_ids: list[str]) -> None:
        self.acquired.append(list(area_ids))

    async def release_fire_history(self, area_ids: list[str]) -> None:
        self.released.append(list(area_ids))

    async def get_fire_history(self, _area_ids: list[str], bursts: int) -> dict[str, Any]:
        frames = [
            {
                "burst": b,
                "voxels": [] if b in self.miss else [list(v) for v in VOXELS],
                "memory_neuron_ids": [],
            }
            for b in range(self.counter - 400, self.counter + 2)
        ]
        return {
            "current_burst": self.counter,
            "subscription_ttl_s": 300,
            "areas": {AREA: {"name": "A", "window": bursts, "frames": frames}},
        }


def test_validate_hold_args() -> None:
    ok = validate_hold_args([[1, 2, 3]], 1.5, 0)
    assert ok == ([[1, 2, 3]], 1.5, 0.0)
    assert isinstance(validate_hold_args([], 1, 0), str)
    assert isinstance(validate_hold_args([[1, 2]], 1, 0), str)
    assert isinstance(validate_hold_args([[1, 2, 3]], 0, 0), str)
    assert isinstance(validate_hold_args([[1, 2, 3]], 31, 0), str)
    assert isinstance(validate_hold_args([[1, 2, 3]], 1, -1), str)


def test_landing_window_is_after_first_post_through_one_past_last() -> None:
    both = ([[0, 0, 1], [0, 0, 2]], [])
    frames = dict.fromkeys(range(10, 20), both)
    frames[13] = ([[0, 0, 1]], [])  # one voxel missing: not landed
    del frames[15]  # no ledger frame at all
    report = landing_report(frames, VOXELS, first_post_burst=11, last_post_burst=17)
    assert report["window"] == [12, 18]
    assert report["checked"] == 7
    assert report["missed"] == [13]
    assert report["no_ledger_frame"] == [15]
    assert report["landed"] == 5  # bursts 12, 14, 16, 17 and 18
    assert report["landed"] + report["missed_count"] + report["no_ledger_frame_count"] == 7


async def test_run_hold_posts_and_verifies_every_burst() -> None:
    client = FakeHoldClient()
    state = new_hold_state(AREA, VOXELS, 0.1)
    result = await run_hold(client, state, AREA, VOXELS, 0.1, 0.0, True)
    assert result["state"] == "done"
    assert result["posts_sent"] >= 10
    assert result["post_failures"] == 0
    assert result["last_post_burst"] > result["first_post_burst"]
    landed = result["landed"]
    assert landed["landed"] == landed["checked"] and landed["missed_count"] == 0
    assert not any(k.startswith("_") for k in result)
    assert client.acquired == [[AREA]] and client.released == [[AREA]]


async def test_run_hold_reports_missed_bursts_instead_of_claiming_success() -> None:
    client = FakeHoldClient()
    client.miss = {502, 503}
    state = new_hold_state(AREA, VOXELS, 0.1)
    result = await run_hold(client, state, AREA, VOXELS, 0.1, 0.0, True)
    assert result["landed"]["missed"] == [502, 503]


async def test_run_hold_counts_failed_posts() -> None:
    client = FakeHoldClient(fail_posts=True)
    state = new_hold_state(AREA, VOXELS, 0.05)
    result = await run_hold(client, state, AREA, VOXELS, 0.05, 0.0, False)
    assert result["post_failures"] == result["posts_sent"] > 0
    assert result["first_failure"] == "HTTP 500"
    assert "landed" not in result


async def test_run_hold_cancel_during_start_delay() -> None:
    client = FakeHoldClient()
    state = new_hold_state(AREA, VOXELS, 1.0)
    state["_cancel"].set()
    result = await run_hold(client, state, AREA, VOXELS, 1.0, 5.0, False)
    assert result["state"] == "cancelled" and client.posts == 0


async def test_client_background_hold_and_status() -> None:
    client = FeagiClient()
    fake = FakeHoldClient()

    async def resolve(*refs: str) -> tuple[list[str], None]:
        return list(refs), None

    client._resolve_area_refs = resolve  # type: ignore[method-assign]
    for name in (
        "get_burst_engine_config",
        "get_burst_counter",
        "_post_stimulation",
        "get_fire_history",
        "release_fire_history",
    ):
        setattr(client, name, getattr(fake, name))
    client.acquire_fire_history = fake.acquire_fire_history  # type: ignore[method-assign]
    started = await client.hold_stimulus(AREA, VOXELS, 0.05, background=True)
    assert started["background"] is True and started["state"] in ("pending", "running")
    final = await client.get_stimulus_hold(started["hold_id"])
    assert final["state"] in ("pending", "running", "done")
    task = client._holds[started["hold_id"]]["_task"]
    await task
    done = await client.get_stimulus_hold(started["hold_id"])
    assert done["state"] == "done" and done["posts_sent"] > 0
    listing = await client.get_stimulus_hold()
    assert listing["holds"][0]["hold_id"] == started["hold_id"]
    assert "error" in await client.get_stimulus_hold("nope")
    bad = await client.hold_stimulus(AREA, [], 1.0)
    assert bad["success"] is False


# ------------------------------------------------------------- stimulus schedule (mocked HTTP)


def _http_client(post_status: int = 200, post_json: Any = None) -> Any:
    from unittest.mock import AsyncMock, MagicMock

    client = FeagiClient()
    response = MagicMock(status_code=post_status, text="body")
    response.json.return_value = post_json or {"schedule_id": 7, "start_burst": 11, "end_burst": 14}
    client._client = MagicMock()
    client._client.post = AsyncMock(return_value=response)
    client._client.delete = AsyncMock(return_value=response)
    client._client.get = AsyncMock(return_value=response)
    return client


AREA_ID = "AAAAAAAAAAA="


async def test_schedule_stimulus_posts_the_contract_body() -> None:
    client = _http_client()
    out = await client.schedule_stimulus(
        [
            {
                "burst_offset": 0,
                "stimuli": [
                    {"area_id": AREA_ID, "coordinates": [[0, 0, 1]]},
                    {"area_id": AREA_ID, "coordinates": [[0, 0, 2]]},
                ],
            },
            {"burst_offset": 5, "stimuli": [{"area_id": AREA_ID, "coordinates": [[0, 0, 3]]}]},
        ]
    )
    assert out == {"success": True, "schedule_id": 7, "start_burst": 11, "end_burst": 14}
    call = client._client.post.call_args
    assert call.args[0].endswith("/v1/simulation/stimulus_schedule")
    assert call.kwargs["json"] == {
        "entries": [
            {"burst_offset": 0, "stimulation": {AREA_ID: [[0, 0, 1], [0, 0, 2]]}},
            {"burst_offset": 5, "stimulation": {AREA_ID: [[0, 0, 3]]}},
        ]
    }


async def test_schedule_stimulus_repeat_and_null_end_burst() -> None:
    client = _http_client(post_json={"schedule_id": 8, "start_burst": 5, "end_burst": None})
    entry = {"burst_offset": 0, "stimuli": [{"area_id": AREA_ID, "coordinates": [[0, 0, 0]]}]}
    out = await client.schedule_stimulus([entry], repeat_period_bursts=1)
    assert out == {"success": True, "schedule_id": 8, "start_burst": 5, "end_burst": None}
    assert client._client.post.call_args.kwargs["json"]["repeat"] == {"period_bursts": 1}
    plain = _http_client()
    await plain.schedule_stimulus([entry])
    assert "repeat" not in plain._client.post.call_args.kwargs["json"]


async def test_schedule_stimulus_rejects_bad_repeat_before_any_request() -> None:
    client = _http_client()
    entry = {"burst_offset": 3, "stimuli": [{"area_id": AREA_ID, "coordinates": [[0, 0, 0]]}]}
    for period in (0, 3, True, "2"):
        out = await client.schedule_stimulus([entry], repeat_period_bursts=period)
        assert out["success"] is False
    client._client.post.assert_not_called()


async def test_get_stimulus_schedule_passes_repeat_fields() -> None:
    item = {"schedule_id": 8, "end_burst": None, "next_burst": 9, "repeat": {"period_bursts": 1}}
    client = _http_client(post_json={"schedules": [item]})
    assert (await client.get_stimulus_schedule())["schedules"] == [item]


async def test_schedule_stimulus_resolves_area_names() -> None:
    client = _http_client()

    async def mapping() -> dict[str, str]:
        return {AREA_ID: "Pulse"}

    client.get_cortical_id_name_mapping = mapping  # type: ignore[method-assign]
    await client.schedule_stimulus(
        [{"burst_offset": 2, "stimuli": [{"area_id": "Pulse", "coordinates": [[0, 0, 0]]}]}]
    )
    body = client._client.post.call_args.kwargs["json"]
    assert list(body["entries"][0]["stimulation"]) == [AREA_ID]


async def test_schedule_stimulus_rejects_bad_input_before_any_request() -> None:
    client = _http_client()
    good = {"area_id": AREA_ID, "coordinates": [[0, 0, 0]]}
    bad_entries: list[Any] = [
        [],
        [{"burst_offset": -1, "stimuli": [good]}],
        [{"burst_offset": 0, "stimuli": []}],
        [{"burst_offset": 0, "stimuli": [{"area_id": AREA_ID, "coordinates": [[0, -1, 0]]}]}],
        [{"burst_offset": 0, "stimuli": [{"area_id": AREA_ID, "coordinates": [[0, 0]]}]}],
    ]
    for entries in bad_entries:
        assert (await client.schedule_stimulus(entries))["success"] is False
    client._client.post.assert_not_called()


async def test_schedule_stimulus_surfaces_http_errors() -> None:
    client = _http_client(post_status=400)
    out = await client.schedule_stimulus(
        [{"burst_offset": 0, "stimuli": [{"area_id": AREA_ID, "coordinates": [[0, 0, 0]]}]}]
    )
    assert out["success"] is False and out["error"] == "HTTP 400" and out["message"] == "body"


async def test_cancel_and_list_stimulus_schedule() -> None:
    client = _http_client(post_json={"schedule_id": 7, "cancelled": True})
    out = await client.cancel_stimulus(7)
    assert out == {"success": True, "schedule_id": 7, "cancelled": True}
    assert client._client.delete.call_args.args[0].endswith("/v1/simulation/stimulus_schedule/7")
    assert (await client.cancel_stimulus(-1))["success"] is False
    listing = _http_client(post_json={"schedules": []})
    assert await listing.get_stimulus_schedule() == {"schedules": []}
    gone = _http_client(post_status=404)
    assert (await gone.cancel_stimulus(9))["error"] == "HTTP 404"
