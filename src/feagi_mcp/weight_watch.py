"""Learning observability: weight series, plasticity freeze and weight reset for one mapping.

FEAGI exposes no per-mapping freeze or weight-reset route. ``POST
/v1/neuroplasticity/{enable,disable}/{area_id}`` exist but only log and return a
message (verified in feagi-core ``endpoints/neuroplasticity.rs``). So:

* **freeze** rewrites the mapping's rules with ``plasticity_flag`` off (on again to
  unfreeze; ``plasticity_mode`` is left as stored) through
  ``PUT /v1/cortical_mapping/mapping_properties``.
* **reset** deletes the mapping and recreates it with the same rules. FEAGI keeps the
  weight of a synapse whose neuron pair already existed (verified live), so the tool
  compares weight statistics before and after and reports whether they went back
  to one uniform value.

Both report the statistics before and after so the caller never has to assume.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

MAX_WATCH_S = 25.0
MIN_INTERVAL_S = 0.5
EXTREME_COUNT = 5
FULL_SAMPLE_LIMIT = 200


def _scan_parts(
    diagnostics: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    """``(synapse_scan, weight_stats, sample)`` from a diagnostics payload, each defaulted."""
    scan_raw = diagnostics.get("synapse_scan") if isinstance(diagnostics, dict) else None
    scan: dict[str, Any] = scan_raw if isinstance(scan_raw, dict) else {}
    stats_raw = scan.get("weight_stats")
    stats: dict[str, Any] = stats_raw if isinstance(stats_raw, dict) else {}
    sample_raw = scan.get("sample")
    sample: list[Any] = sample_raw if isinstance(sample_raw, list) else []
    return scan, stats, sample


def weight_sample(diagnostics: dict[str, Any], cap: float | None) -> dict[str, Any]:
    """One series point from a ``diagnose_mapping_plasticity`` payload."""
    scan, stats, sample = _scan_parts(diagnostics)
    weighted = [
        s for s in sample if isinstance(s, dict) and isinstance(s.get("weight"), (int, float))
    ]
    ordered = sorted(weighted, key=lambda s: float(s["weight"]))

    def ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "src": s.get("source_neuron_id"),
                "dst": s.get("target_neuron_id"),
                "w": round(float(s["weight"]), 4),
            }
            for s in items
        ]

    at_cap = (
        sum(1 for s in weighted if cap is not None and float(s["weight"]) >= cap)
        if cap is not None
        else None
    )
    return {
        "count": scan.get("matched_synapse_count_src_to_dst"),
        "min": stats.get("min"),
        "max": stats.get("max"),
        "avg": round(stats["avg"], 4) if isinstance(stats.get("avg"), (int, float)) else None,
        "count_at_zero": stats.get("zero_weight_count"),
        "count_at_cap": at_cap,
        "largest": ids(ordered[-EXTREME_COUNT:][::-1]),
        "smallest": ids(ordered[:EXTREME_COUNT]),
        "extremes_from_sample_of": len(weighted),
    }


def weight_cap_from_area(area: dict[str, Any] | None) -> float | None:
    """Destination area's ``neuron_post_synaptic_potential_max``, FEAGI's weight ceiling."""
    if not isinstance(area, dict):
        return None
    for bag in (area, area.get("properties")):
        if isinstance(bag, dict):
            value = bag.get("neuron_post_synaptic_potential_max")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


async def watch_weights(
    diagnose: Callable[[], Awaitable[dict[str, Any]]],
    duration_s: float,
    interval_s: float,
    *,
    cap: float | None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Sample ``diagnose`` every ``interval_s`` for ``duration_s`` and return the series."""
    duration = max(0.0, min(float(duration_s), MAX_WATCH_S))
    interval = max(MIN_INTERVAL_S, float(interval_s))
    start = clock()
    series: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    while True:
        t0 = clock()
        payload = await diagnose()
        if isinstance(payload, dict) and not payload.get("error"):
            point = weight_sample(payload, cap)
            point["t"] = round(t0 - start, 3)
            series.append(point)
        else:
            errors.append({"t": round(t0 - start, 3), "error": payload})
        if clock() - start + interval > duration:
            break
        await sleep(max(0.0, interval - (clock() - t0)))
    avgs = [p["avg"] for p in series if isinstance(p.get("avg"), (int, float))]
    return {
        "window_s": duration,
        "interval_s": interval,
        "capped": float(duration_s) > MAX_WATCH_S,
        "weight_cap": cap,
        "samples": series,
        "errors": errors,
        "avg_delta": round(avgs[-1] - avgs[0], 4) if len(avgs) >= 2 else None,
        "max_delta": (
            round(series[-1]["max"] - series[0]["max"], 4)
            if len(series) >= 2
            and isinstance(series[0].get("max"), (int, float))
            and isinstance(series[-1].get("max"), (int, float))
            else None
        ),
    }


def frozen_rules(rules: list[dict[str, Any]], frozen: bool) -> list[dict[str, Any]]:
    """Copy of ``rules`` with ``plasticity_flag`` off (frozen) or on.

    feagi-core gates learning on ``plasticity_flag`` alone; ``plasticity_mode`` is left
    as stored so unfreezing restores the same rule.
    """
    out: list[dict[str, Any]] = []
    for rule in rules:
        new = dict(rule)
        if frozen:
            new["plasticity_flag"] = False
        elif new.get("plasticity_mode") not in (None, "", "none"):
            new["plasticity_flag"] = True
        out.append(new)
    return out


def _stats(diag: dict[str, Any]) -> dict[str, Any]:
    scan, stats, sample = _scan_parts(diag)
    weights = sorted(
        {
            round(float(s["weight"]), 6)
            for s in sample
            if isinstance(s, dict) and isinstance(s.get("weight"), (int, float))
        }
    )
    return {
        "count": scan.get("matched_synapse_count_src_to_dst"),
        "min": stats.get("min"),
        "max": stats.get("max"),
        "avg": stats.get("avg"),
        "unique_weights_in_sample": weights[:10],
        "unique_weight_count_in_sample": len(weights),
    }


async def freeze_mapping(client: Any, src: str, dst: str, frozen: bool) -> dict[str, Any]:
    """Rewrite the src->dst rules with plasticity off (or on); report weights before/after."""
    before_map, before_diag = await asyncio.gather(
        client.get_cortical_mapping(src, dst),
        client.get_mapping_plasticity_diagnostics(src, dst, sample_limit=FULL_SAMPLE_LIMIT),
    )
    rules = before_map.get("rules") if isinstance(before_map, dict) else None
    if not isinstance(rules, list) or not rules:
        return {
            "error": "mapping_not_found",
            "src_area": src,
            "dst_area": dst,
            "details": before_map,
        }
    rules = [r for r in rules if isinstance(r, dict)]
    new_rules = frozen_rules(rules, frozen)
    update = await client.update_cortical_mapping(src, dst, new_rules)
    if not isinstance(update, dict) or update.get("error"):
        return {"error": "update_failed", "src_area": src, "dst_area": dst, "details": update}
    after_diag = await client.get_mapping_plasticity_diagnostics(
        src, dst, sample_limit=FULL_SAMPLE_LIMIT
    )
    before, after = _stats(before_diag), _stats(after_diag)
    return {
        "src_area": src,
        "dst_area": dst,
        "frozen": frozen,
        "rules_written": len(new_rules),
        "plastic_rules_after": (
            after_diag.get("plastic_rules_count") if isinstance(after_diag, dict) else None
        ),
        "weights_before": before,
        "weights_after": after,
        "weights_preserved": before.get("count") == after.get("count")
        and before.get("avg") == after.get("avg"),
        "method": "PUT /v1/cortical_mapping/mapping_properties with plasticity_flag off; "
        "FEAGI has no per-mapping freeze route (its /v1/neuroplasticity/disable is a no-op).",
    }


async def reset_mapping(client: Any, src: str, dst: str) -> dict[str, Any]:
    """Delete and recreate the src->dst mapping; report whether weights became uniform."""
    before_map, before_diag = await asyncio.gather(
        client.get_cortical_mapping(src, dst),
        client.get_mapping_plasticity_diagnostics(src, dst, sample_limit=FULL_SAMPLE_LIMIT),
    )
    rules = before_map.get("rules") if isinstance(before_map, dict) else None
    if not isinstance(rules, list) or not rules:
        return {
            "error": "mapping_not_found",
            "src_area": src,
            "dst_area": dst,
            "details": before_map,
        }
    rules = [dict(r) for r in rules if isinstance(r, dict)]
    deleted = await client.delete_cortical_mapping(src, dst)
    if not isinstance(deleted, dict) or deleted.get("error"):
        return {"error": "delete_failed", "src_area": src, "dst_area": dst, "details": deleted}
    recreated = await client.update_cortical_mapping(src, dst, rules)
    if not isinstance(recreated, dict) or recreated.get("error"):
        return {
            "error": "recreate_failed",
            "src_area": src,
            "dst_area": dst,
            "details": recreated,
            "rules_to_reapply": rules,
        }
    after_diag = await client.get_mapping_plasticity_diagnostics(
        src, dst, sample_limit=FULL_SAMPLE_LIMIT
    )
    before, after = _stats(before_diag), _stats(after_diag)
    before_uniform = before["unique_weight_count_in_sample"] <= 1
    after_uniform = after["unique_weight_count_in_sample"] == 1
    changed = before.get("avg") != after.get("avg") or before.get("max") != after.get("max")
    return {
        "src_area": src,
        "dst_area": dst,
        "rules_reapplied": len(rules),
        "weights_before": before,
        "weights_after": after,
        "weights_reset": after_uniform and (changed or before_uniform),
        "weights_changed": changed,
        "method": "DELETE /v1/cortical_mapping/mapping, then PUT mapping_properties with the "
        "same rules. FEAGI keeps the weight of an existing neuron pair (verified), so "
        "weights_reset may be false.",
    }


async def reset_mapping_native_first(client: Any, src: str, dst: str) -> dict[str, Any]:
    """Reset one mapping's weights natively; recreate the mapping on older FEAGI."""
    native = await client.reset_mapping_weights_native(src, dst)
    if isinstance(native, dict) and native.get("route_missing"):
        result = await reset_mapping(client, src, dst)
        result["method"] = "recreate_fallback"
        return result
    if not isinstance(native, dict) or native.get("error"):
        return {
            "error": "native_reset_failed",
            "src_area": src,
            "dst_area": dst,
            "details": native,
        }
    return {
        "src_area": src,
        "dst_area": dst,
        "method": "native",
        "synapses_reset": native.get("synapses_reset"),
        "weight": native.get("weight"),
    }
