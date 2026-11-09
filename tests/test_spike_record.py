"""record_spikes: ledger merging, summary, CSV and subscription lifecycle (mocked FEAGI)."""

from __future__ import annotations

import asyncio
from typing import Any

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.spike_record import (
    LedgerCollector,
    expand_region_refs,
    record_spikes_window,
    runs_of,
    summarize_frames,
)

AREA = "area_a"
OTHER = "area_b"


class FakeLedger:
    """Counter advances 10 bursts per read; area fires on even bursts at voxel (0,0,1)."""

    def __init__(self, drop: set[int] | None = None, ttl: int = 300) -> None:
        self.counter = 1000
        self.drop = drop or set()
        self.ttl = ttl
        self.acquired: list[list[str]] = []
        self.released: list[list[str]] = []
        self.history_calls: list[tuple[list[str], int]] = []

    async def get_burst_engine_config(self) -> dict[str, Any]:
        return {"burst_interval_seconds": 0.001}

    async def get_burst_counter(self) -> dict[str, Any]:
        self.counter += 10
        return {"burst_counter": self.counter}

    def acquire_fire_history(self, area_ids: list[str]) -> None:
        self.acquired.append(list(area_ids))

    async def release_fire_history(self, area_ids: list[str]) -> None:
        self.released.append(list(area_ids))

    async def get_fire_history(self, area_ids: list[str], bursts: int) -> dict[str, Any]:
        self.history_calls.append((list(area_ids), bursts))
        cur = self.counter
        areas = {}
        for a in area_ids:
            frames = []
            for b in range(cur - bursts + 1, cur + 1):
                if b in self.drop:
                    continue
                fires = a == AREA and b % 2 == 0
                frames.append(
                    {"burst": b, "voxels": [[0, 0, 1]] if fires else [], "memory_neuron_ids": []}
                )
            areas[a] = {"cortical_idx": 1, "name": f"name_{a}", "window": bursts, "frames": frames}
        return {
            "current_burst": cur,
            "bursts": bursts,
            "subscription_ttl_s": self.ttl,
            "areas": areas,
        }


def test_runs_of_groups_consecutive_bursts() -> None:
    assert runs_of([1, 2, 3, 7, 9, 10]) == [[1, 3], [7, 7], [9, 10]]
    assert runs_of([]) == []


async def test_record_spikes_summarizes_fire_fraction_and_runs() -> None:
    client = FakeLedger()
    result = await record_spikes_window(client, [AREA, OTHER], bursts=100)
    assert result["success"] is True
    assert result["bursts_requested"] == 100
    assert result["first_burst"] == 1001  # the subscription read saw burst 1000
    assert result["gap_count"] == 0
    a = result["areas"][AREA]
    assert a["name"] == f"name_{AREA}"
    assert a["fire_fraction"] == 0.5
    assert a["fired_bursts"] == result["bursts_observed"] // 2
    assert a["top_voxels"][0]["voxel"] == [0, 0, 1]
    assert a["top_voxels"][0]["fraction"] == 0.5
    assert a["run_count"] == a["fired_bursts"]  # every other burst: runs of length 1
    assert len(a["runs"]) <= 20
    quiet = result["areas"][OTHER]
    assert quiet["fired_bursts"] == 0 and quiet["first_fire_burst"] is None
    # one acquire and one release for the recording, whatever the number of reads
    assert client.acquired == [[AREA, OTHER]]
    assert client.released == [[AREA, OTHER]]
    assert all(bursts <= 500 for _, bursts in client.history_calls)


async def test_record_spikes_reports_ledger_gaps() -> None:
    client = FakeLedger(drop={1050, 1051})
    result = await record_spikes_window(client, [AREA], bursts=60)
    assert result["success"] is False
    assert result["gaps"] == [1050, 1051]
    assert result["gap_count"] == 2


async def test_record_spikes_validates_arguments_before_any_request() -> None:
    client = FakeLedger()
    assert (await record_spikes_window(client, [], 10))["success"] is False
    assert (await record_spikes_window(client, [AREA], 0))["success"] is False
    assert (await record_spikes_window(client, [AREA], 20001))["success"] is False
    assert (await record_spikes_window(client, [str(i) for i in range(65)], 10))["success"] is False
    assert client.acquired == []


async def test_record_spikes_error_from_subscription_releases() -> None:
    client = FakeLedger()

    async def failing(_ids: list[str], _bursts: int) -> dict[str, Any]:
        return {"error": "HTTP 404", "endpoint": "/v1/burst_engine/fire_history"}

    client.get_fire_history = failing  # type: ignore[method-assign]
    result = await record_spikes_window(client, [AREA], 10)
    assert result["success"] is False and "subscription" in result["error"]
    assert client.released == [[AREA]]


async def test_csv_has_one_row_per_spike(tmp_path: Any) -> None:
    client = FakeLedger()
    path = tmp_path / "spikes.csv"
    result = await record_spikes_window(client, [AREA], bursts=50, csv_path=str(path))
    lines = path.read_text().splitlines()
    assert lines[0] == "burst,area_id,area_name,x,y,z,memory_neuron_id"
    assert len(lines) - 1 == result["areas"][AREA]["total_spikes"]
    assert lines[1].split(",")[1:] == [AREA, f"name_{AREA}", "0", "0", "1", ""]
    assert result["csv_path"] == str(path.resolve())


async def test_collector_rereads_before_ttl_expires() -> None:
    # 0.8 * window * interval = 0.4 s, ttl / 2 = 0.25 s: the shorter one paces the re-reads
    client = FakeLedger(ttl=0.5)  # type: ignore[arg-type]
    collector = LedgerCollector(client, [AREA], window=500)
    assert await collector.start() is None
    assert collector.ttl_s == 0.5
    assert collector.reread_s == 0.25
    await collector.close()


def test_summary_counts_memory_neurons_as_spikes() -> None:
    collector = LedgerCollector(FakeLedger(), [AREA])  # type: ignore[arg-type]
    collector.frames[AREA] = {1: ([], [7]), 2: ([], []), 3: ([[1, 2, 3]], [])}
    out = summarize_frames(collector, 1, 3)["areas"][AREA]
    assert out["total_spikes"] == 2 and out["fired_bursts"] == 2
    assert out["fire_fraction"] == round(2 / 3, 4)
    assert out["memory_spikes"] == 1
    assert out["top_memory_neurons"] == [{"neuron_id": 7, "count": 1, "fraction": round(1 / 3, 4)}]


async def test_client_refcount_deletes_only_when_last_user_releases() -> None:
    client = FeagiClient()
    calls: list[dict[str, Any]] = []

    class Http:
        async def delete(self, _url: str, params: dict[str, str]) -> None:
            calls.append(params)

    client._client = Http()  # type: ignore[assignment]
    client.acquire_fire_history(["a", "b"])
    client.acquire_fire_history(["a"])
    await client.release_fire_history(["a", "b"])
    assert calls == [{"areas": "b"}]  # 'a' still has a user
    await client.release_fire_history(["a"])
    assert calls == [{"areas": "b"}, {"areas": "a"}]


async def test_max_runs_lists_more_runs_and_reports_truncation() -> None:
    default = await record_spikes_window(FakeLedger(), [AREA], bursts=100)
    first = default["areas"][AREA]
    assert first["run_count"] > 20 and len(first["runs"]) == 20 and first["runs_truncated"] is True
    everything = await record_spikes_window(FakeLedger(), [AREA], bursts=100, max_runs=1000)
    area = everything["areas"][AREA]
    assert len(area["runs"]) == area["run_count"] and area["runs_truncated"] is False
    none = await record_spikes_window(FakeLedger(), [AREA], bursts=100, max_runs=0)
    assert none["areas"][AREA]["runs"] == []
    bad = await record_spikes_window(FakeLedger(), [AREA], bursts=100, max_runs=-1)
    assert bad["success"] is False


def test_expand_region_refs_replaces_regions_by_id_or_title_with_members() -> None:
    regions = {
        "r1": {"title": "Ring", "areas": ["a1", "a2"], "regions": ["r2"]},
        "r2": {"title": "Sub", "areas": ["a3", "a1"], "regions": []},
    }
    refs, expanded, error = expand_region_refs(["r1", "x", "Sub"], regions)
    assert error is None
    assert refs == ["a1", "a2", "a3", "x"]
    assert expanded == [{"region": "r1", "areas": 3}, {"region": "r2", "areas": 2}]


def test_expand_region_refs_rejects_ambiguous_title() -> None:
    regions = {"r1": {"title": "Dup", "areas": []}, "r2": {"title": "Dup", "areas": []}}
    _refs, _expanded, error = expand_region_refs(["Dup"], regions)
    assert error and "several regions" in error


async def test_client_record_spikes_expands_region_before_the_cap() -> None:
    client = FeagiClient()
    members = [f"a{i}" for i in range(40)]

    async def regions() -> dict[str, Any]:
        return {"r1": {"title": "Big", "areas": members, "regions": []}}

    async def resolve(*refs: str) -> tuple[list[str], None]:
        return list(refs), None

    seen: dict[str, Any] = {}

    async def fake_window(_c: Any, ids: list[str], *_a: Any, **_k: Any) -> dict[str, Any]:
        seen["ids"] = ids
        return {"success": True}

    client.get_regions_members = regions  # type: ignore[method-assign]
    client._resolve_area_refs = resolve  # type: ignore[method-assign]
    import feagi_mcp.feagi_client as fc

    original = fc.record_spikes_window
    fc.record_spikes_window = fake_window  # type: ignore[assignment]
    try:
        result = await client.record_spikes(["Big"], 10)
    finally:
        fc.record_spikes_window = original
    assert seen["ids"] == sorted(members)
    assert result["regions_expanded"] == [{"region": "r1", "areas": 40}]


async def test_budget_refuses_a_window_longer_than_one_call_and_releases() -> None:
    client = FakeLedger()  # 0.001 s per burst
    result = await record_spikes_window(client, [AREA], bursts=2000, budget_s=1.0)
    assert result["success"] is False and "background=True" in result["error"]
    assert client.released == [[AREA]]
    ok = await record_spikes_window(FakeLedger(), [AREA], bursts=100, budget_s=1.0)
    assert ok["success"] is True


async def test_cancel_ends_the_window_early_with_a_partial_summary() -> None:
    client = FakeLedger()
    cancel = asyncio.Event()
    cancel.set()
    result = await record_spikes_window(client, [AREA], bursts=10_000, cancel=cancel)
    assert result["cancelled"] is True and result["success"] is False
    assert result["last_burst"] < result["first_burst"] + 10_000 - 1
    assert client.released == [[AREA]]


def _client_on(fake: FakeLedger) -> FeagiClient:
    client = FeagiClient()

    async def resolve_spike_areas(areas: Any) -> tuple[list[str], list[Any], None]:
        return list(areas), [], None

    client.resolve_spike_areas = resolve_spike_areas  # type: ignore[method-assign]
    for name in (
        "get_burst_engine_config",
        "get_burst_counter",
        "get_fire_history",
        "acquire_fire_history",
        "release_fire_history",
    ):
        setattr(client, name, getattr(fake, name))
    return client


async def test_foreground_record_spikes_refuses_past_the_call_budget() -> None:
    fake = FakeLedger()

    async def slow_config() -> dict[str, Any]:
        return {"burst_interval_seconds": 0.005}

    fake.get_burst_engine_config = slow_config  # type: ignore[method-assign]
    client = _client_on(fake)
    result = await client.record_spikes([AREA], 20_000)
    assert result["success"] is False and "get_spike_recording" in result["error"]


async def test_background_record_spikes_returns_at_once_and_reports_the_summary() -> None:
    fake = FakeLedger()
    client = _client_on(fake)
    started = await client.record_spikes([AREA], 100, background=True)
    assert started["background"] is True and started["state"] == "running"
    rid = started["recording_id"]
    await client._recordings[rid]["_task"]
    done = await client.get_spike_recording(rid)
    assert done["state"] == "done"
    assert done["result"]["areas"][AREA]["bursts_observed"] == 100
    assert "_task" not in done and "_cancel" not in done
    listing = await client.get_spike_recording()
    assert listing["recordings"][0]["recording_id"] == rid
    assert "error" in await client.get_spike_recording("nope")
    bad = await client.record_spikes([AREA], 0, background=True)
    assert bad["success"] is False and not client._recordings.get("x")
    assert len(client._recordings) == 1


async def test_background_record_spikes_cancel_returns_partial_result() -> None:
    fake = FakeLedger()

    async def counter() -> dict[str, Any]:
        fake.counter += 1  # slow enough that the window is still running at cancel
        return {"burst_counter": fake.counter}

    fake.get_burst_counter = counter  # type: ignore[method-assign]
    client = _client_on(fake)
    started = await client.record_spikes([AREA], 20_000, background=True)
    await asyncio.sleep(0.05)
    cancelled = await client.get_spike_recording(started["recording_id"], cancel=True)
    assert cancelled["state"] == "cancelled"
    assert cancelled["result"]["cancelled"] is True
    assert fake.released == [[AREA]]
