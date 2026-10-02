"""Tests for local memory-area wiring and lifecycle diagnostics."""

from feagi_mcp.memory_diagnostics import (
    CODE_EXPIRES_UNMATCHED,
    CODE_NO_EPISODIC_UPSTREAM,
    annotate_shared_edges,
    inbound_sources,
    lifecycle_totals,
    memory_area_diagnostics,
)


def _items() -> list[dict]:
    return [
        {"src": "kernel", "dst": "kmem", "morphology": "episodic_memory"},
        {"src": "kernel", "dst": "kmem", "morphology": "episodic_scan"},
        {"src": "field", "dst": "kmem", "morphology": "episodic_scan"},
        {"src": "kernel", "dst": "kmem_other", "morphology": "episodic_memory"},
    ]


def test_inbound_sources_match_exact_destination_and_morphology() -> None:
    assert inbound_sources(_items(), "kmem", "episodic_memory") == ["kernel"]
    assert inbound_sources(_items(), "kmem", "episodic_scan") == ["field", "kernel"]
    assert inbound_sources(_items(), "kmem_", "episodic_memory") == []


def test_lifecycle_totals_absent_area_is_unknown_not_zero() -> None:
    assert lifecycle_totals(None, "kmem") == {
        "created_total": None,
        "deleted_total": None,
        "neuron_count": None,
    }
    stats = {"kmem": {"created_total": 7, "deleted_total": 5, "neuron_count": 2}}
    assert lifecycle_totals(stats, "kmem") == {
        "created_total": 7,
        "deleted_total": 5,
        "neuron_count": 2,
    }


def test_scan_only_memory_reports_no_episodic_upstream() -> None:
    items = [row for row in _items() if row["morphology"] != "episodic_memory"]
    out = memory_area_diagnostics("kmem", items, None, 0)
    assert out["episodic_upstream"] == []
    assert out["scan_sources"] == ["field", "kernel"]
    codes = [f["code"] for f in out["findings"]]
    assert codes == [CODE_NO_EPISODIC_UPSTREAM]
    assert out["findings"][0]["severity"] == "error"
    assert "episodic_scan from field, kernel" in out["findings"][0]["message"]


def test_all_created_neurons_expired_is_flagged() -> None:
    stats = {"kmem": {"created_total": 40, "deleted_total": 40, "neuron_count": 0}}
    out = memory_area_diagnostics("kmem", _items(), stats, 0)
    assert [f["code"] for f in out["findings"]] == [CODE_EXPIRES_UNMATCHED]
    assert out["created_total"] == 40


def test_no_churn_finding_when_long_term_exists_or_nothing_created() -> None:
    expired = {"kmem": {"created_total": 40, "deleted_total": 40, "neuron_count": 0}}
    assert memory_area_diagnostics("kmem", _items(), expired, 3)["findings"] == []
    idle = {"kmem": {"created_total": 0, "deleted_total": 0, "neuron_count": 0}}
    assert memory_area_diagnostics("kmem", _items(), idle, 0)["findings"] == []
    alive = {"kmem": {"created_total": 40, "deleted_total": 38, "neuron_count": 2}}
    assert memory_area_diagnostics("kmem", _items(), alive, 0)["findings"] == []


def test_annotate_shared_edges_only_marks_multi_rule_edges() -> None:
    rows = [{**row} for row in _items()]
    annotate_shared_edges(rows)
    shared = ["episodic_memory", "episodic_scan"]
    assert rows[0]["edge_morphologies"] == shared
    assert rows[1]["edge_morphologies"] == shared
    assert "edge_morphologies" not in rows[2]
    assert "edge_morphologies" not in rows[3]
