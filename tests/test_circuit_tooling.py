"""Region export pruning, validate_genome(file_path), burst timing and compact views."""

from __future__ import annotations

import json
from typing import Any

import pytest

from feagi_mcp import server
from feagi_mcp.compact_views import compact_map, compact_region, compact_rule
from feagi_mcp.feagi_client import BURST_TIMING_GAP, FeagiClient
from feagi_mcp.genome_tools import (
    entering_mappings,
    entering_morphology_ids,
    prune_unreferenced_morphologies,
    read_genome_file,
    referenced_morphology_ids,
)
from feagi_mcp.synapse_counts import MAX_EDGES_LISTED, count_edges_between, edge_synapse_counts


class Resp:
    def __init__(self, data: Any, status: int = 200) -> None:
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self) -> Any:
        return self._data


def _genome() -> dict[str, Any]:
    return {
        "genome_title": "g",
        "version": "2.0",
        "blueprint": {
            "_____10c-AAA=-cx-__name-t": "A",
            "_____10c-AAA=-cx-dstmap-d": {
                "BBB=": [{"morphology_id": "block_to_block"}, {"morphology_id": "my_custom"}]
            },
            "_____10c-BBB=-cx-__name-t": "B",
            "_____10c-BBB=-cx-dstmap-d": {},
        },
        "neuron_morphologies": {
            "block_to_block": {"type": "functions"},
            "my_custom": {"type": "patterns"},
            "unused": {"type": "patterns"},
            "all_to_all": {"type": "patterns"},
        },
    }


def test_prune_keeps_only_referenced_morphologies() -> None:
    genome = _genome()
    assert referenced_morphology_ids(genome) == {"block_to_block", "my_custom"}
    pruned, removed = prune_unreferenced_morphologies(genome)
    assert sorted(pruned["neuron_morphologies"]) == ["block_to_block", "my_custom"]
    assert removed == 2
    assert pruned["blueprint"] == genome["blueprint"]
    assert "unused" in genome["neuron_morphologies"]  # the input is not modified
    assert prune_unreferenced_morphologies({"blueprint": {}}) == ({"blueprint": {}}, 0)


def _brain() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Region r1 holds B; area S outside maps into B with the morphology ``from_outside``."""
    regions = {
        "r1": {"areas": ["BBB="], "regions": []},
        "root": {"areas": ["SSS="], "regions": ["r1"]},
    }
    cortical_map = {
        "SSS=": {"BBB=": [{"morphology_id": "from_outside", "postSynapticCurrent_multiplier": 3}]},
        "BBB=": {"SSS=": [{"morphology_id": "leaving"}]},
        "XXX=": {"SSS=": [{"morphology_id": "elsewhere"}]},
    }
    geometry = {"SSS=": {"cortical_name": "Src"}, "BBB=": {"cortical_name": "B"}}
    return regions, cortical_map, geometry


def test_entering_mappings_lists_only_edges_into_the_subtree() -> None:
    regions, cortical_map, geometry = _brain()
    rows = entering_mappings(regions, cortical_map, geometry, "r1")
    assert [(r["src"], r["dst"]) for r in rows] == [("Src", "B")]
    assert rows[0]["rules"][0]["rule"] == "from_outside"
    assert rows[0]["rules"][0]["psc"] == 3
    assert entering_morphology_ids(rows) == {"from_outside"}
    with pytest.raises(KeyError):
        entering_mappings(regions, cortical_map, geometry, "nope")


def test_prune_keeps_extra_morphologies() -> None:
    pruned, removed = prune_unreferenced_morphologies(_genome(), {"unused"})
    assert sorted(pruned["neuron_morphologies"]) == ["block_to_block", "my_custom", "unused"]
    assert removed == 1


class RegionHttp:
    """Serves the region export plus the graph reads used for entering mappings."""

    def __init__(self, brain_ok: bool = True) -> None:
        self.seen: list[dict[str, str]] = []
        self.brain_ok = brain_ok

    async def get(self, url: str, params: dict[str, str] | None = None) -> Resp:
        regions, cortical_map, geometry = _brain()
        if url.endswith("/v1/genome/download_region"):
            self.seen.append(params or {})
            genome = _genome()
            genome["neuron_morphologies"]["from_outside"] = {"type": "patterns"}
            return Resp(genome)
        if not self.brain_ok:
            return Resp({"detail": "boom"}, 500)
        if url.endswith("/v1/region/regions_members"):
            return Resp(regions)
        if url.endswith("/v1/cortical_area/cortical_map_detailed"):
            return Resp(cortical_map)
        return Resp(geometry)


async def test_download_region_genome_prunes_but_keeps_entering_morphologies() -> None:
    client = FeagiClient()
    http = RegionHttp()
    client._client = http  # type: ignore[assignment]
    pruned = await client.download_region_genome("r1")
    assert sorted(pruned["neuron_morphologies"]) == ["block_to_block", "from_outside", "my_custom"]
    assert http.seen == [{"region_id": "r1"}]
    notes = pruned["export_notes"]["entering_mappings"]
    assert [(n["src"], n["dst"]) for n in notes] == [("Src", "B")]
    assert "src_id" not in notes[0]
    raw = await client.download_region_genome("r1", prune_morphologies=False)
    assert len(raw["neuron_morphologies"]) == 5


async def test_download_region_genome_keeps_everything_when_graph_unreadable() -> None:
    client = FeagiClient()
    client._client = RegionHttp(brain_ok=False)  # type: ignore[assignment]
    out = await client.download_region_genome("r1")
    assert len(out["neuron_morphologies"]) == 5
    assert "prune_skipped" in out["export_notes"]


async def test_download_region_genome_file_summary_lists_entering_mappings(tmp_path: Any) -> None:
    client = FeagiClient()
    client._client = RegionHttp()  # type: ignore[assignment]
    path = tmp_path / "r.genome"
    result = await client.download_region_genome("r1", file_path=str(path))
    assert result["summary"]["morphologies"] == 3
    assert result["entering_mappings"][0]["rules"][0]["rule"] == "from_outside"
    assert "export_notes" not in json.loads(path.read_text())


def test_read_genome_file_errors(tmp_path: Any) -> None:
    good = tmp_path / "g.genome"
    good.write_text(json.dumps(_genome()))
    assert read_genome_file(str(good))["genome_title"] == "g"
    with pytest.raises(ValueError, match="cannot read"):
        read_genome_file(str(tmp_path / "missing.genome"))
    bad = tmp_path / "bad.genome"
    bad.write_text("[1, 2]")
    with pytest.raises(ValueError, match="not a JSON object"):
        read_genome_file(str(bad))


async def test_validate_genome_accepts_a_file_path(tmp_path: Any) -> None:
    path = tmp_path / "region.genome"
    path.write_text(json.dumps(_genome()))
    from_file = await server.validate_genome(file_path=str(path))
    inline = await server.validate_genome(genome_json=json.dumps(_genome()))
    assert from_file == inline
    assert "Missing required key: neuron_morphologies" not in from_file["issues"]


async def test_validate_genome_input_errors(tmp_path: Any) -> None:
    both = await server.validate_genome("{}", str(tmp_path / "x"))
    none = await server.validate_genome()
    assert both["valid"] is False and none["valid"] is False
    assert "exactly one" in both["issues"][0] and "exactly one" in none["issues"][0]
    missing = await server.validate_genome(file_path=str(tmp_path / "nope.genome"))
    assert missing["valid"] is False and "cannot read" in missing["issues"][0]
    bad = tmp_path / "bad.genome"
    bad.write_text("not json")
    assert "not a JSON object" in (await server.validate_genome(file_path=str(bad)))["issues"][0]


async def test_runtime_metrics_reports_the_burst_timing_gap() -> None:
    client = FeagiClient()

    class Http:
        async def get(self, _url: str, **_: Any) -> Resp:
            return Resp({"burst_count": 5, "burst_frequency_hz": 200.0})

    client._client = Http()  # type: ignore[assignment]
    result = await client.get_runtime_metrics()
    assert result["burst_count"] == 5
    timing = result["burst_timing"]
    assert timing["available"] is False
    assert "avg_burst_time_ms is hard-coded 0.0" in timing["gap"]
    assert "measured" not in timing
    assert timing["gap"] == BURST_TIMING_GAP["gap"]


async def test_runtime_metrics_measures_rate_against_the_wall_clock() -> None:
    client = FeagiClient()
    ticks = iter([1000, 1018])  # 18 bursts counted while ~0.1 s passed at a 5 ms interval

    class Http:
        async def get(self, url: str, **_: Any) -> Resp:
            if url.endswith("/monitoring/metrics"):
                return Resp({"burst_count": 1})
            if url.endswith("/burst_engine/config"):
                return Resp({"burst_interval_seconds": 0.005})
            return Resp(next(ticks))

    client._client = Http()  # type: ignore[assignment]
    result = await client.get_runtime_metrics(measure_s=0.1)
    measured = result["burst_timing"]["measured"]
    assert measured["source"] == "counter_vs_wallclock"
    assert measured["bursts_elapsed"] == 18
    assert measured["expected_bursts"] > 18 and measured["shortfall_bursts"] > 0
    assert measured["target_frequency_hz"] == 200.0
    assert result["burst_timing"]["available"] is False  # a period is not a duration


async def test_runtime_metrics_passes_http_errors_through() -> None:
    client = FeagiClient()

    class Http:
        async def get(self, _url: str, **_: Any) -> Resp:
            return Resp("down", 503)

    client._client = Http()  # type: ignore[assignment]
    assert "error" in await client.get_runtime_metrics()


def test_count_edges_between_uses_global_neuron_ids() -> None:
    outgoing = [{"target_neuron_id": 7}, {"target_neuron_id": 8}, {"target_neuron_id": 99}]
    incoming = [{"target_neuron_id": 7}, {"target_neuron_id": 8}, {"target_neuron_id": 8}]
    assert count_edges_between(outgoing, incoming) == 2
    assert count_edges_between([], incoming) == 0


async def test_edge_synapse_counts_fetches_each_area_once_and_flags_unreadable() -> None:
    fetched: list[tuple[str, str]] = []

    async def fetch(area: str, direction: str) -> list[Any] | None:
        fetched.append((area, direction))
        if area == "bad":
            return None
        return [{"target_neuron_id": 1}]

    counts, note = await edge_synapse_counts([("a", "b"), ("a", "c"), ("a", "bad")], fetch)
    assert counts == {("a", "b"): 1, ("a", "c"): 1, ("a", "bad"): None}
    assert note is None
    assert fetched.count(("a", "outgoing")) == 1

    async def huge(_area: str, _direction: str) -> list[Any]:
        return [{"target_neuron_id": i} for i in range(MAX_EDGES_LISTED)]

    counts, note = await edge_synapse_counts([("a", "b")], huge)
    assert counts == {("a", "b"): None} and "skipped" in note


GEOMETRY = {
    "ID_A": {"cortical_name": "Alpha", "cortical_dimensions": [1, 1, 9]},
    "ID_B": {"cortical_name": "Beta", "cortical_dimensions": [1, 1, 1]},
    "ID_C": {"cortical_name": "Gamma", "cortical_dimensions": [2, 2, 2]},
}
CMAP = {
    "ID_A": {
        "ID_B": [
            {
                "morphology_id": "block_to_block",
                "morphology_scalar": [1, 1, 1],
                "postSynapticCurrent_multiplier": 2,
                "synaptic_delay_bursts": 1,
                "plasticity_flag": False,
                "ltp_multiplier": 1,
            }
        ],
        "ID_C": [],
    },
    "ID_C": {"ID_A": [{"morphology_id": "lateral_+z", "morphology_scalar": [1, 1, 2]}]},
}
REGIONS = {
    "r1": {"title": "Circuit", "areas": ["ID_A", "ID_B"], "regions": []},
}


def test_compact_rule_keeps_only_the_summary_fields() -> None:
    assert compact_rule(CMAP["ID_A"]["ID_B"][0]) == {
        "rule": "block_to_block",
        "psc": 2,
        "delay": 1,
        "plastic": False,
    }
    assert compact_rule(CMAP["ID_C"]["ID_A"][0])["scalar"] == [1, 1, 2]


def test_compact_map_uses_names_and_skips_empty_edges() -> None:
    view = compact_map(CMAP, GEOMETRY, {("ID_A", "ID_B"): 4, ("ID_C", "ID_A"): 0})
    assert view["edge_count"] == 2 and view["area_count"] == 3
    assert view["areas"][0] == {"name": "Alpha", "dimensions": [1, 1, 9]}
    first = view["edges"][0]
    assert (first["src"], first["dst"], first["synapses"]) == ("Alpha", "Beta", 4)
    assert "ID_A" not in json.dumps(view)
    assert "synapses" not in compact_map(CMAP, GEOMETRY)["edges"][0]


def test_compact_region_scopes_edges() -> None:
    view = compact_region(REGIONS, CMAP, GEOMETRY, "r1", True, {("ID_C", "ID_A"): 3})
    assert view["title"] == "Circuit" and view["member_count"] == 2
    assert [m["name"] for m in view["members"]] == ["Alpha", "Beta"]
    scopes = {(e["src"], e["dst"]): e["scope"] for e in view["edges"]}
    assert scopes == {("Alpha", "Beta"): "internal", ("Gamma", "Alpha"): "incoming"}
    assert compact_region(REGIONS, CMAP, GEOMETRY, "nope")["error"] == "unknown_region"


class MapHttp:
    """Routes the GETs the compact views make."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def get(self, url: str, **_: Any) -> Resp:
        self.paths.append(url)
        if url.endswith("/cortical_map_detailed"):
            return Resp(CMAP)
        if url.endswith("/regions_members"):
            return Resp(REGIONS)
        if url.endswith("/cortical_area/geometry"):
            return Resp(GEOMETRY)
        if url.endswith("/synapses"):
            return Resp([{"target_neuron_id": 5}])
        if url.endswith("/synapses/incoming"):
            return Resp([{"target_neuron_id": 5}])
        return Resp({}, 404)


async def test_get_cortical_map_detailed_compact_and_full() -> None:
    client = FeagiClient()
    client._client = MapHttp()  # type: ignore[assignment]
    assert await client.get_cortical_map_detailed() == CMAP
    view = await client.get_cortical_map_detailed(compact=True)
    assert [e["synapses"] for e in view["edges"]] == [1, 1]
    no_counts = await client.get_cortical_map_detailed(compact=True, synapse_counts=False)
    assert "synapses" not in no_counts["edges"][0]


async def test_get_region_circuit_compact_is_smaller_and_uses_names() -> None:
    client = FeagiClient()
    client._client = MapHttp()  # type: ignore[assignment]

    async def names() -> dict[str, str]:
        return {"ID_A": "Alpha", "ID_B": "Beta", "ID_C": "Gamma"}

    client.get_cortical_id_name_mapping = names  # type: ignore[method-assign]
    full = await client.get_region_circuit("r1")
    compact = await client.get_region_circuit("r1", compact=True)
    assert compact["members"][0] == {"name": "Alpha", "dimensions": [1, 1, 9]}
    assert {e["scope"] for e in compact["edges"]} == {"internal", "incoming"}
    assert "boundary" in full and "boundary" not in compact
    assert "isolated_area_ids" in full and "isolated_area_ids" not in compact
    assert (await client.get_region_circuit("zzz", compact=True))["error"] == "unknown_region"


async def test_download_region_genome_writes_a_file_and_returns_a_summary(tmp_path: Any) -> None:
    client = FeagiClient()

    class Http:
        async def get(self, url: str, **_: Any) -> Resp:
            if url.endswith("/v1/genome/download_region"):
                return Resp(_genome())
            return await RegionHttp().get(url)

    client._client = Http()  # type: ignore[assignment]
    target = tmp_path / "out" / "region.genome"
    result = await client.download_region_genome("r1", file_path=str(target))
    result.pop("entering_mappings")
    assert set(result) == {"file_path", "bytes", "summary"}
    assert result["file_path"] == str(target.resolve()) and result["bytes"] == target.stat().st_size
    assert result["summary"] == {
        "genome_title": "g",
        "areas": 2,
        "morphologies": 2,
        "brain_regions": 0,
    }
    on_disk = read_genome_file(str(target))
    assert sorted(on_disk["neuron_morphologies"]) == ["block_to_block", "my_custom"]
    assert (await server.validate_genome(file_path=str(target)))["cortical_area_count"] >= 0


async def test_download_region_genome_write_error_is_reported(tmp_path: Any) -> None:
    client = FeagiClient()

    class Http:
        async def get(self, _url: str, **_: Any) -> Resp:
            return Resp(_genome())

    client._client = Http()  # type: ignore[assignment]
    blocker = tmp_path / "file"
    blocker.write_text("x")
    result = await client.download_region_genome("r1", file_path=str(blocker / "sub" / "g.genome"))
    assert "cannot write genome file" in result["error"]
