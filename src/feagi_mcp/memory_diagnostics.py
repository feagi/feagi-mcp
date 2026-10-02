"""Memory-area wiring and lifecycle diagnostics for MCP tools.

These functions stay local. They do not call FEAGI. Callers pass the mapping
table from ``get_connectivity_summary`` and the ``memory_area_stats`` block from
``GET /v1/system/health_check``.

Plasticity registers a memory area with one upstream area per ``episodic_memory``
source; only those sources create memory neurons. ``episodic_scan`` matches
stored long-term patterns and never creates them, so a memory area whose only
inbound rule is a scan stays empty.
"""

from __future__ import annotations

from typing import Any

ENCODE_MORPHOLOGY = "episodic_memory"
SCAN_MORPHOLOGY = "episodic_scan"

CODE_NO_EPISODIC_UPSTREAM = "memory_no_episodic_upstream"
CODE_EXPIRES_UNMATCHED = "memory_neurons_expire_unmatched"


def inbound_sources(
    mapping_items: list[dict[str, Any]],
    memory_id: str,
    morphology: str,
) -> list[str]:
    """Sorted source area IDs mapped into ``memory_id`` with ``morphology``."""
    sources: set[str] = set()
    for item in mapping_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("dst", "")).strip() != memory_id:
            continue
        if str(item.get("morphology", "")).strip() != morphology:
            continue
        src = str(item.get("src", "")).strip()
        if src:
            sources.add(src)
    return sorted(sources)


def lifecycle_totals(
    memory_area_stats: dict[str, Any] | None,
    memory_id: str,
) -> dict[str, int | None]:
    """Lifetime create/delete counters and live count for one memory area."""
    stats = (memory_area_stats or {}).get(memory_id)
    if not isinstance(stats, dict):
        return {"created_total": None, "deleted_total": None, "neuron_count": None}
    return {
        "created_total": _int_or_none(stats.get("created_total")),
        "deleted_total": _int_or_none(stats.get("deleted_total")),
        "neuron_count": _int_or_none(stats.get("neuron_count")),
    }


def memory_area_diagnostics(
    memory_id: str,
    mapping_items: list[dict[str, Any]],
    memory_area_stats: dict[str, Any] | None,
    long_term_neuron_count: int | None,
) -> dict[str, Any]:
    """Upstream wiring, lifecycle totals, and findings for one memory area."""
    episodic_upstream = inbound_sources(mapping_items, memory_id, ENCODE_MORPHOLOGY)
    scan_sources = inbound_sources(mapping_items, memory_id, SCAN_MORPHOLOGY)
    totals = lifecycle_totals(memory_area_stats, memory_id)
    findings: list[dict[str, Any]] = []
    if not episodic_upstream:
        message = "No episodic_memory mapping feeds this area; plasticity creates no neurons here."
        if scan_sources:
            message += (
                f" Inbound episodic_scan from {', '.join(scan_sources)} only matches "
                f"stored long-term patterns."
            )
        findings.append(
            {"severity": "error", "code": CODE_NO_EPISODIC_UPSTREAM, "message": message}
        )
    created = totals["created_total"]
    alive = totals["neuron_count"]
    if created and alive == 0 and not long_term_neuron_count:
        findings.append(
            {
                "severity": "warning",
                "code": CODE_EXPIRES_UNMATCHED,
                "message": (
                    f"{created} neurons created, {totals['deleted_total']} deleted, none alive "
                    f"and none long-term. Patterns expire before they repeat: raise "
                    f"init_lifespan or hold each sample for more bursts."
                ),
            }
        )
    return {
        "episodic_upstream": episodic_upstream,
        "scan_sources": scan_sources,
        **totals,
        "findings": findings,
    }


def annotate_shared_edges(rows: list[dict[str, Any]]) -> None:
    """Add ``edge_morphologies`` to rows whose src->dst edge carries more than one rule."""
    by_edge: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        by_edge.setdefault((row["src"], row["dst"]), []).append(str(row["morphology"]))
    for row in rows:
        morphologies = by_edge[(row["src"], row["dst"])]
        if len(morphologies) > 1:
            row["edge_morphologies"] = morphologies


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
