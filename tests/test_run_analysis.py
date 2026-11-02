"""analyze_run: ring period, port-in-window, window counts and duty on synthetic spike CSVs."""

from __future__ import annotations

from pathlib import Path

from feagi_mcp.run_analysis import analyze_spikes_csv

RING_BINS = 8
PERIOD = 8  # one bin per burst


def _trainer_csv(path: Path, rows: list[tuple[int, str, int]]) -> str:
    lines = ["burst,area,x,y,z"] + [f"{b},{a},0,0,{z}" for b, a, z in rows]
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _ring_rows(cycles: int) -> list[tuple[int, str, int]]:
    return [(b, "Ring", b % RING_BINS) for b in range(1, cycles * RING_BINS + 1)]


def test_ring_period_and_bins_visited(tmp_path: Path) -> None:
    path = _trainer_csv(tmp_path / "s.csv", _ring_rows(5))
    out = analyze_spikes_csv(path, ring={"area": "Ring", "bins": RING_BINS})
    ring = out["ring"]
    assert out["csv_format"] == "trainer"
    assert ring["period_mean"] == PERIOD and ring["period_sd"] == 0
    assert ring["cycles"] == 4  # bin 0 is entered at bursts 8, 16, ..., 40: 5 entries
    assert ring["bins_visited"] == list(range(RING_BINS)) and ring["bins_missing"] == []


def test_ring_reports_a_missing_bin_and_jitter(tmp_path: Path) -> None:
    rows = [r for r in _ring_rows(4) if r[2] != 5]
    rows += [(40, "Ring", 0), (50, "Ring", 0)]
    path = _trainer_csv(tmp_path / "s.csv", rows)
    ring = analyze_spikes_csv(path, ring={"area": "Ring", "bins": RING_BINS})["ring"]
    assert ring["bins_missing"] == [5]
    assert ring["period_sd"] > 0


def test_port_in_window_uses_lagged_phase(tmp_path: Path) -> None:
    rows = _ring_rows(4)
    # phase at burst b is b % 8; the port fires 2 bursts after bins 2..3, and once after bin 4
    rows += [(12, "Port", 0), (13, "Port", 0), (21, "Port", 0), (22, "Port", 1)]
    path = _trainer_csv(tmp_path / "s.csv", rows)
    out = analyze_spikes_csv(
        path,
        port_in_window=[{"port": "Port", "phase_area": "Ring", "bins": [2, 3], "lag": 2}],
    )["port_in_window"][0]
    assert out["port_spikes"] == 4
    assert out["inside"] + out["outside"] == 4
    assert out["pct_inside"] == round(100 * out["inside"] / 4, 2)
    assert out["inside"] == 3 and out["outside"] == 1


def test_window_counts_in_and_out(tmp_path: Path) -> None:
    rows = _ring_rows(3) + [(2, "Reset", 0), (3, "Reset", 0), (6, "Reset", 0), (7, "Reset", 0)]
    path = _trainer_csv(tmp_path / "s.csv", rows)
    out = analyze_spikes_csv(
        path, window_counts=[{"area": "Reset", "phase_area": "Ring", "bins": "2..3"}]
    )["window_counts"][0]
    assert out["spikes_in_window"] == 2 and out["spikes_out_of_window"] == 2


def test_duty_and_off_episodes_per_half_cycle(tmp_path: Path) -> None:
    rows = _ring_rows(4)
    # Area fires every burst of the low half (bins 0..3) except one gap, never in the high half
    for b in range(1, 33):
        z = b % RING_BINS
        if z < 4 and b != 17:
            rows.append((b, "Drive", 0))
    path = _trainer_csv(tmp_path / "s.csv", rows)
    out = analyze_spikes_csv(path, duty={"area": "Drive", "phase_area": "Ring", "bins": RING_BINS})
    halves = out["duty"]["halves"]
    assert halves["high"]["duty"] == 0 and halves["high"]["off_episodes_per_half_cycle"] == 1
    assert 0.8 < halves["low"]["duty"] < 1
    assert out["duty"]["half_cycles_total"] >= 6


def test_record_spikes_format_and_burst_filter(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    lines = ["burst,area_id,area_name,x,y,z,memory_neuron_id"]
    lines += [f"{b},id1,Ring,0,0,{b % RING_BINS}," for b in range(1, 41)]
    lines += ["5,id1,Ring,,,,99"]  # memory-neuron row is skipped
    path.write_text("\n".join(lines) + "\n")
    out = analyze_spikes_csv(str(path), ring={"area": "Ring"}, first_burst=9, last_burst=40)
    assert out["csv_format"] == "record_spikes"
    assert out["burst_range"] == [9, 40] and out["rows"] == 32
    by_id = analyze_spikes_csv(str(path), ring={"area": "id1"})["ring"]
    assert by_id["spikes"] == 40


def test_errors_are_reported_not_raised(tmp_path: Path) -> None:
    assert analyze_spikes_csv(str(tmp_path / "none.csv"), ring={"area": "x"})["success"] is False
    assert analyze_spikes_csv(str(tmp_path / "none.csv"))["success"] is False
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n")
    assert "header" in analyze_spikes_csv(str(bad), ring={"area": "x"})["error"]
    good = _trainer_csv(tmp_path / "g.csv", _ring_rows(1))
    out = analyze_spikes_csv(good, ring={"area": "Typo"})
    assert out["areas_not_in_file"] == ["Typo"] and "Ring" in out["areas_in_file"]
