"""Acceptance metrics from a spikes CSV (pure; no FEAGI access).

Reads either spike format:

- Trainer run data ``neural/spikes.csv``: ``burst,area,x,y,z`` (``area`` is the area name);
- ``record_spikes`` ``csv_path``: ``burst,area_id,area_name,x,y,z,memory_neuron_id``.

An area is matched by name (or, in the second format, by id). Rows without a voxel
(memory-neuron rows) are skipped. The phase of a phase area at a burst is the set of its
firing ``z`` bins; at a burst where it is silent, the last seen phase is carried forward
(``phase_known`` counts spikes that came before any phase). All bursts are the bursts in the
file (or ``first_burst..last_burst``); a burst with no rows is a silent burst.

Metrics (each optional, one call): ``ring`` period and bins visited; ``port_in_window``
share of a port's spikes whose lagged phase is inside given bins; ``window_counts`` an
area's spikes inside / outside a phase window; ``duty`` fire fraction and silent episodes per
half-cycle of a ring.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

MAX_HALF_CYCLES_LISTED = 20


class AnalysisError(ValueError):
    """The CSV or a metric request is invalid; the message says what."""


def _int_list(value: Any, field: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise AnalysisError(f"'{field}' must be a non-empty list of integer bins")
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise AnalysisError(f"'{field}' must hold integers, got {item!r}")
        out.append(item)
    return out


def _bins(value: Any, field: str) -> set[int]:
    """Bins as a list (``[3, 4]``) or an inclusive range ``[[3, 7]]`` / ``"3..7"``."""
    if isinstance(value, str) and ".." in value:
        lo, _, hi = value.partition("..")
        try:
            return set(range(int(lo), int(hi) + 1))
        except ValueError as e:
            raise AnalysisError(f"'{field}': bad range {value!r}") from e
    if (
        isinstance(value, list)
        and value
        and all(isinstance(v, list) and len(v) == 2 for v in value)
    ):
        out: set[int] = set()
        for lo, hi in value:
            out.update(range(int(lo), int(hi) + 1))
        return out
    return set(_int_list(value, field))


def _need(request: dict[str, Any], key: str, metric: str) -> Any:
    value = request.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AnalysisError(f"{metric}: '{key}' is required")
    return value


def _lag(request: dict[str, Any], metric: str) -> int:
    lag = request.get("lag", 0)
    if isinstance(lag, bool) or not isinstance(lag, int):
        raise AnalysisError(f"{metric}: 'lag' must be an integer number of bursts")
    return lag


class SpikeTable:
    """``spikes[area][burst]`` = list of z bins that fired (one entry per voxel)."""

    def __init__(self) -> None:
        self.spikes: dict[str, dict[int, list[int]]] = {}
        self.first_burst: int | None = None
        self.last_burst: int | None = None
        self.rows = 0
        self.format = ""
        self.areas_seen: set[str] = set()


def load_spikes(
    csv_path: str,
    areas: set[str],
    first_burst: int | None = None,
    last_burst: int | None = None,
) -> SpikeTable:
    """Stream the CSV once, keeping only the voxel rows of ``areas`` inside the burst range."""
    path = Path(csv_path).expanduser()
    if not path.is_file():
        raise AnalysisError(f"csv_path not found: {path}")
    table = SpikeTable()
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            raise AnalysisError("csv is empty (no header)")
        cols = {name.strip(): i for i, name in enumerate(header)}
        if "burst" not in cols or "z" not in cols:
            raise AnalysisError(f"csv header needs 'burst' and 'z'; got {header}")
        name_cols = [cols[c] for c in ("area_name", "area", "area_id") if c in cols]
        if not name_cols:
            raise AnalysisError("csv header needs 'area' (Trainer) or 'area_name' (record_spikes)")
        table.format = "record_spikes" if "area_name" in cols else "trainer"
        b_i, z_i = cols["burst"], cols["z"]
        for row in reader:
            if len(row) <= max(b_i, z_i):
                continue
            try:
                burst = int(row[b_i])
            except ValueError:
                continue
            if (first_burst is not None and burst < first_burst) or (
                last_burst is not None and burst > last_burst
            ):
                continue
            if row[z_i] == "":
                continue
            table.rows += 1
            if table.first_burst is None or burst < table.first_burst:
                table.first_burst = burst
            if table.last_burst is None or burst > table.last_burst:
                table.last_burst = burst
            keys = {row[i] for i in name_cols if i < len(row) and row[i]}
            table.areas_seen.update(keys)
            for key in keys & areas:
                table.spikes.setdefault(key, {}).setdefault(burst, []).append(int(row[z_i]))
    return table


def _phase_lookup(table: SpikeTable, area: str) -> tuple[list[int], dict[int, list[int]]]:
    frames = table.spikes.get(area, {})
    return sorted(frames), frames


class _Phase:
    """Phase of an area at a burst: its firing z bins, last seen one carried forward."""

    def __init__(self, table: SpikeTable, area: str) -> None:
        self.bursts, self.frames = _phase_lookup(table, area)
        self._i = 0

    def at(self, burst: int) -> set[int] | None:
        """Phase at ``burst``; call with non-decreasing bursts."""
        while self._i + 1 < len(self.bursts) and self.bursts[self._i + 1] <= burst:
            self._i += 1
        if not self.bursts or self.bursts[self._i] > burst:
            return None
        return set(self.frames[self.bursts[self._i]])


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 2) if whole else None


def ring_metrics(table: SpikeTable, request: dict[str, Any]) -> dict[str, Any]:
    """Period (bursts between entries into ``anchor_bin``) and bins visited."""
    area = str(_need(request, "area", "ring"))
    anchor = request.get("anchor_bin", 0)
    if isinstance(anchor, bool) or not isinstance(anchor, int):
        raise AnalysisError("ring: 'anchor_bin' must be an integer")
    frames = table.spikes.get(area, {})
    visited: dict[int, int] = {}
    entries: list[int] = []
    last_here: int | None = None  # last burst on the anchor bin
    for burst in sorted(frames):
        zs = set(frames[burst])
        for z in zs:
            visited[z] = visited.get(z, 0) + 1
        if anchor in zs:
            # an entry is the first burst of a run on the anchor bin; a silent burst ends a run
            if last_here is None or burst != last_here + 1:
                entries.append(burst)
            last_here = burst
    periods = [b - a for a, b in zip(entries, entries[1:], strict=False)]
    out: dict[str, Any] = {
        "area": area,
        "spikes": sum(len(v) for v in frames.values()),
        "cycles": len(periods),
        "anchor_bin": anchor,
        "period_mean": round(statistics.fmean(periods), 3) if periods else None,
        "period_sd": round(statistics.pstdev(periods), 3) if len(periods) > 1 else None,
        "period_min": min(periods) if periods else None,
        "period_max": max(periods) if periods else None,
        "bins_visited": sorted(visited),
        "bins_visited_count": len(visited),
    }
    n_bins = request.get("bins")
    if isinstance(n_bins, int) and not isinstance(n_bins, bool) and n_bins > 0:
        out["bins_missing"] = [z for z in range(n_bins) if z not in visited]
    if not frames:
        out["note"] = "area has no spikes in the file (check its name)"
    return out


def port_in_window_metric(table: SpikeTable, request: dict[str, Any]) -> dict[str, Any]:
    """Share of a port's spikes whose phase ``lag`` bursts earlier lies in ``bins``."""
    port = str(_need(request, "port", "port_in_window"))
    phase_area = str(_need(request, "phase_area", "port_in_window"))
    bins = _bins(_need(request, "bins", "port_in_window"), "bins")
    lag = _lag(request, "port_in_window")
    phase = _Phase(table, phase_area)
    frames = table.spikes.get(port, {})
    inside = outside = unknown = 0
    for burst in sorted(frames):
        n = len(frames[burst])
        at = phase.at(burst - lag)
        if at is None:
            unknown += n
        elif at & bins:
            inside += n
        else:
            outside += n
    known = inside + outside
    return {
        "port": port,
        "phase_area": phase_area,
        "lag": lag,
        "bins": sorted(bins),
        "port_spikes": inside + outside + unknown,
        "inside": inside,
        "outside": outside,
        "phase_unknown": unknown,
        "pct_inside": _pct(inside, known),
    }


def window_counts_metric(table: SpikeTable, request: dict[str, Any]) -> dict[str, Any]:
    """An area's spikes (and the bursts they fall in) inside and outside a phase window."""
    area = str(_need(request, "area", "window_counts"))
    phase_area = str(_need(request, "phase_area", "window_counts"))
    bins = _bins(_need(request, "bins", "window_counts"), "bins")
    lag = _lag(request, "window_counts")
    phase = _Phase(table, phase_area)
    frames = table.spikes.get(area, {})
    inside = outside = unknown = 0
    bursts_in = bursts_out = 0
    for burst in sorted(frames):
        n = len(frames[burst])
        at = phase.at(burst - lag)
        if at is None:
            unknown += n
        elif at & bins:
            inside += n
            bursts_in += 1
        else:
            outside += n
            bursts_out += 1
    return {
        "area": area,
        "phase_area": phase_area,
        "lag": lag,
        "bins": sorted(bins),
        "spikes_in_window": inside,
        "spikes_out_of_window": outside,
        "bursts_in_window": bursts_in,
        "bursts_out_of_window": bursts_out,
        "phase_unknown": unknown,
    }


def duty_metrics(table: SpikeTable, request: dict[str, Any]) -> dict[str, Any]:
    """Fire fraction and silent episodes of ``area`` per half-cycle of ``phase_area``.

    A half-cycle is a maximal run of bursts whose phase bin lies in the same half of
    ``0..bins-1`` (the lower half is ``< bins/2``, or the given ``half_bins`` list). A silent
    episode is a maximal run of bursts inside a half-cycle in which ``area`` did not fire.
    """
    area = str(_need(request, "area", "duty"))
    phase_area = str(_need(request, "phase_area", "duty"))
    n_bins = _need(request, "bins", "duty")
    if isinstance(n_bins, bool) or not isinstance(n_bins, int) or n_bins < 2:
        raise AnalysisError("duty: 'bins' must be an integer >= 2 (the phase area's z size)")
    low = (
        _bins(request["half_bins"], "half_bins")
        if request.get("half_bins")
        else set(range(n_bins // 2))
    )
    if table.first_burst is None or table.last_burst is None:
        raise AnalysisError("duty: the csv holds no voxel rows in the burst range")
    phase = _Phase(table, phase_area)
    fired = table.spikes.get(area, {})
    halves: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    silent_run = 0
    for burst in range(table.first_burst, table.last_burst + 1):
        at = phase.at(burst)
        if not at:
            continue
        half = "low" if (at & low) else "high"
        if current is None or current["half"] != half:
            if current is not None and silent_run:
                current["off_episodes"] += 1
            current = {"half": half, "start": burst, "bursts": 0, "fired": 0, "off_episodes": 0}
            halves.append(current)
            silent_run = 0
        current["bursts"] += 1
        if burst in fired:
            current["fired"] += 1
            if silent_run:
                current["off_episodes"] += 1
                silent_run = 0
        else:
            silent_run += 1
    if current is not None and silent_run:
        current["off_episodes"] += 1
    summary: dict[str, Any] = {}
    for half in ("low", "high"):
        mine = [h for h in halves if h["half"] == half]
        total = sum(h["bursts"] for h in mine)
        summary[half] = {
            "half_cycles": len(mine),
            "duty": round(sum(h["fired"] for h in mine) / total, 4) if total else None,
            "off_episodes_per_half_cycle": (
                round(statistics.fmean([h["off_episodes"] for h in mine]), 3) if mine else None
            ),
        }
    return {
        "area": area,
        "phase_area": phase_area,
        "low_bins": sorted(low),
        "halves": summary,
        "half_cycles_total": len(halves),
        "half_cycles": [
            {
                "half": h["half"],
                "start": h["start"],
                "bursts": h["bursts"],
                "duty": round(h["fired"] / h["bursts"], 4),
                "off_episodes": h["off_episodes"],
            }
            for h in halves[:MAX_HALF_CYCLES_LISTED]
        ],
        "half_cycles_truncated": len(halves) > MAX_HALF_CYCLES_LISTED,
    }


def _names_needed(ring: Any, ports: list[Any], windows: list[Any], duty: Any) -> set[str]:
    names: set[str] = set()
    pairs: list[tuple[Any, tuple[str, ...]]] = [(ring, ("area",)), (duty, ("area", "phase_area"))]
    pairs += [(p, ("port", "phase_area")) for p in ports]
    pairs += [(w, ("area", "phase_area")) for w in windows]
    for request, keys in pairs:
        if isinstance(request, dict):
            names.update(str(request[k]) for k in keys if request.get(k))
    return names


def analyze_spikes_csv(
    csv_path: str,
    *,
    ring: dict[str, Any] | None = None,
    port_in_window: list[dict[str, Any]] | None = None,
    window_counts: list[dict[str, Any]] | None = None,
    duty: dict[str, Any] | None = None,
    first_burst: int | None = None,
    last_burst: int | None = None,
) -> dict[str, Any]:
    """Run the requested metrics over one spikes CSV; compact JSON, never rows."""
    ports = port_in_window or []
    windows = window_counts or []
    if not (ring or ports or windows or duty):
        return {
            "success": False,
            "error": "ask for at least one of ring, port_in_window, window_counts, duty",
        }
    for label, seq in (("port_in_window", ports), ("window_counts", windows)):
        if not isinstance(seq, list) or not all(isinstance(r, dict) for r in seq):
            return {"success": False, "error": f"{label} must be a list of objects"}
    try:
        table = load_spikes(
            csv_path, _names_needed(ring, ports, windows, duty), first_burst, last_burst
        )
        out: dict[str, Any] = {
            "success": True,
            "csv_format": table.format,
            "rows": table.rows,
            "burst_range": [table.first_burst, table.last_burst],
        }
        if ring:
            out["ring"] = ring_metrics(table, ring)
        if ports:
            out["port_in_window"] = [port_in_window_metric(table, p) for p in ports]
        if windows:
            out["window_counts"] = [window_counts_metric(table, w) for w in windows]
        if duty:
            out["duty"] = duty_metrics(table, duty)
    except (AnalysisError, KeyError, TypeError, ValueError) as e:
        return {"success": False, "error": str(e)}
    missing = sorted(
        n for n in _names_needed(ring, ports, windows, duty) if n not in table.areas_seen
    )
    if missing:
        out["areas_not_in_file"] = missing
        out["areas_in_file"] = sorted(table.areas_seen)[:30]
    return out


__all__ = ["AnalysisError", "analyze_spikes_csv", "load_spikes"]
