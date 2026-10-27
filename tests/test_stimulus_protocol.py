"""Tests for run_stimulus_protocol with a mocked HTTP layer."""

from __future__ import annotations

from typing import Any

from feagi_mcp.feagi_client import STIMULATION_HOLD_MAX_MS, FeagiClient

AREA_A = "area_a"
AREA_B = "area_b"
AREA_MEM = "area_mem"


class FakeResponse:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self) -> Any:
        return self._data


def _sample(ts: int, fired: dict[str, list[list[int]]], available: bool = True) -> dict[str, Any]:
    areas = {
        a: {
            "coordinates_x": [v[0] for v in vs],
            "coordinates_y": [v[1] for v in vs],
            "coordinates_z": [v[2] for v in vs],
            "fired_count": len(vs),
        }
        for a, vs in fired.items()
    }
    return {
        "timestep": ts,
        "current_burst": ts,
        "sample_available": available,
        "sampled_burst_fired_nothing": not fired,
        "cortical_areas": areas,
    }


class FakeHttp:
    """Counter advances one per read; fire queue is scripted by timestep."""

    def __init__(self, samples: dict[int, dict[str, Any]], start: int = 100, interval: float = 0.1):
        self.samples = samples
        self.counter = start - 1
        self.interval = interval
        self.posts: list[dict[str, Any]] = []
        self.post_counters: list[int] = []

    async def get(self, url: str) -> FakeResponse:
        if url.endswith("/burst_counter"):
            self.counter += 1
            return FakeResponse(self.counter)
        if url.endswith("/burst_engine/config"):
            return FakeResponse({"burst_interval_seconds": self.interval})
        if url.endswith("/fire_queue/detailed"):
            ts = self.counter
            return FakeResponse(self.samples.get(ts, _sample(ts, {})))
        raise AssertionError(url)

    async def post(self, url: str, json: dict[str, Any]) -> FakeResponse:
        assert url.endswith("/v1/agent/manual_stimulation")
        self.posts.append(json)
        self.post_counters.append(self.counter)
        return FakeResponse({"success": True, "unique_neuron_ids": 1, "matched_coordinates": 1})


def _client(http: FakeHttp) -> FeagiClient:
    client = FeagiClient(host="localhost", port=8000)
    client._client = http  # type: ignore[assignment]
    return client


STEPS = [
    {
        "bursts": 2,
        "label": "first",
        "stimuli": [
            {"area_id": AREA_A, "coordinates": [[0, 0, 0], [1, 0, 0]]},
            {"area_id": AREA_B, "coordinates": [[2, 0, 0]]},
        ],
    },
    {"bursts": 1, "label": "rest", "stimuli": []},
    {"bursts": 1, "stimuli": [{"area_id": AREA_A, "coordinates": [[3, 0, 0]]}]},
]


async def test_one_merged_payload_per_burst_and_rest_posts_nothing() -> None:
    http = FakeHttp({})
    out = await _client(http).run_stimulus_protocol(STEPS, [AREA_A], tail_bursts=1)
    assert out["success"] is True
    assert len(http.posts) == 3  # 2 + 0 (rest) + 1
    assert http.posts[0]["stimulation_payload"] == {
        AREA_A: [[0, 0, 0], [1, 0, 0]],
        AREA_B: [[2, 0, 0]],
    }
    assert http.posts[0]["mode"] == "force_fire"
    assert http.posts[2]["stimulation_payload"] == {AREA_A: [[3, 0, 0]]}
    assert out["bursts_run"] == 5


async def test_each_burst_recorded_once_and_filtered_to_record_areas() -> None:
    samples = {
        101: _sample(101, {AREA_A: [[0, 0, 0]], AREA_B: [[2, 0, 0]], AREA_MEM: [[0, 0, 0]]}),
        102: _sample(102, {AREA_A: [[0, 0, 0], [1, 0, 0]]}),
    }
    http = FakeHttp(samples)
    out = await _client(http).run_stimulus_protocol(STEPS, [AREA_A, AREA_MEM], tail_bursts=1)
    rows = out["bursts"]
    assert [r["burst"] for r in rows] == [101, 102]
    assert set(rows[0]["areas"]) == {AREA_A, AREA_MEM}  # AREA_B not recorded
    assert rows[0]["areas"][AREA_MEM] == [[0, 0, 0]]
    assert out["areas"][AREA_A]["firing_bursts"] == 2
    assert out["areas"][AREA_A]["voxel_counts"] == {"0,0,0": 2, "1,0,0": 1}
    assert out["areas"][AREA_MEM]["firing_bursts"] == 1


async def test_duplicate_sample_timestep_counts_once() -> None:
    # Sampler stuck on burst 101 for every read.
    http = FakeHttp({})
    sample = _sample(101, {AREA_A: [[0, 0, 0]]})

    async def stuck_get(url: str) -> FakeResponse:
        if url.endswith("/fire_queue/detailed"):
            return FakeResponse(sample)
        return await FakeHttp.get(http, url)

    http.get = stuck_get  # type: ignore[method-assign]
    out = await _client(http).run_stimulus_protocol(STEPS, [AREA_A])
    assert len(out["bursts"]) == 1
    assert out["areas"][AREA_A]["voxel_counts"] == {"0,0,0": 1}


async def test_steps_tagged_with_label_and_posted_bursts() -> None:
    samples = {
        101: _sample(101, {AREA_A: [[0, 0, 0]]}),  # posted 100 (step 0)
        103: _sample(103, {AREA_A: [[9, 0, 0]]}),  # posted 102 (step 1, rest)
        104: _sample(104, {AREA_A: [[3, 0, 0]]}),  # tail read, posted 103 (step 2)
    }
    http = FakeHttp(samples)
    out = await _client(http).run_stimulus_protocol(STEPS, [AREA_A], tail_bursts=1)
    assert [(r["burst"], r["step"]) for r in out["bursts"]] == [
        (101, 0),
        (103, 1),
        (104, 2),
    ]
    first, rest, last = out["steps"]
    assert (first["label"], first["first_burst"], first["last_burst"], first["bursts_posted"]) == (
        "first",
        100,
        101,
        2,
    )
    assert (rest["label"], rest["first_burst"], rest["bursts_posted"]) == ("rest", 102, 1)
    assert last["label"] is None and last["first_burst"] == 103


async def test_missed_bursts_listed() -> None:
    samples = {
        101: _sample(101, {AREA_A: [[0, 0, 0]]}),
        104: _sample(104, {AREA_A: [[0, 0, 0]]}),
    }
    http = FakeHttp(samples)

    async def get(url: str) -> FakeResponse:
        if url.endswith("/fire_queue/detailed"):
            return FakeResponse(samples.get(http.counter, _sample(http.counter, {}, False)))
        return await FakeHttp.get(http, url)

    http.get = get  # type: ignore[method-assign]
    out = await _client(http).run_stimulus_protocol(STEPS, [AREA_A], tail_bursts=1)
    assert out["bursts_missed"] == [102, 103]
    assert [r["burst"] for r in out["bursts"]] == [101, 104]


async def test_total_capped_at_hold_max() -> None:
    http = FakeHttp({}, interval=1.0)
    steps = [{"bursts": 40, "stimuli": [{"area_id": AREA_A, "coordinates": [[0, 0, 0]]}]}]
    out = await _client(http).run_stimulus_protocol(steps, [AREA_A])
    cap = STIMULATION_HOLD_MAX_MS // 1000
    assert out["capped_at_ms"] == STIMULATION_HOLD_MAX_MS
    assert out["bursts_run"] == cap
    assert len(http.posts) == cap
    assert out["steps"][0]["bursts_posted"] == cap


async def test_timeout_guard_reports_failure(monkeypatch: Any) -> None:
    http = FakeHttp({})

    async def frozen(url: str) -> FakeResponse:
        if url.endswith("/burst_counter"):
            return FakeResponse(100)
        return await FakeHttp.get(http, url)

    http.get = frozen  # type: ignore[method-assign]
    ticks = iter(range(0, 10_000, 5))
    monkeypatch.setattr("feagi_mcp.feagi_client.time.monotonic", lambda: float(next(ticks)))
    out = await _client(http).run_stimulus_protocol(STEPS, [AREA_A])
    assert out["success"] is False
    assert "timed out" in out["error"]
