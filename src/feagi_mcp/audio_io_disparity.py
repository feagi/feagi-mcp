"""Compare audio spectrum frames that entered FEAGI with the frames that left.

Sensory Generator writes one neuron per frequency column: x is the column,
y is the phase row, potential is the magnitude. Perception Inspector reads
the same layout from the audio output area one burst later. Phase moves to
a new row every frame, so a comparison has to match columns, not the same
voxel across bursts.

The functions here are pure. The MCP tool polls the sensor and motor taps
and passes the captured frames in.
"""

from __future__ import annotations

from typing import Any

#: Potential difference treated as the same magnitude.
POTENTIAL_TOLERANCE = 1e-3
#: Delays searched when pairing an input burst with the output burst it caused.
DELAYS = (0, 1, 2, 3)

Column = tuple[float, int]
Frame = dict[int, Column]


def samples_of(payload: dict[str, Any], cortical_id: str) -> list[dict[str, Any]] | None:
    """Voxel samples for one area, or None when that burst has no audio."""
    areas = payload.get("areas")
    if not isinstance(areas, list):
        return None
    for area in areas:
        if isinstance(area, dict) and area.get("cortical_id") == cortical_id:
            samples = area.get("samples")
            if isinstance(samples, list) and samples:
                return [sample for sample in samples if isinstance(sample, dict)]
    return None


def take_audio_frame(
    payload: dict[str, Any],
    cortical_id: str,
) -> tuple[Frame | None, int]:
    """Frame for this snapshot, or (None, 0) when the area did not fire."""
    samples = samples_of(payload, cortical_id)
    if not samples or not isinstance(payload.get("burst_num"), int):
        return None, 0
    return frame_from_samples(samples)


def frame_from_samples(samples: list[dict[str, Any]]) -> tuple[Frame, int]:
    """Collapse voxels to one column map. The loudest row wins a shared column.

    Returns the frame and how many columns were fired on more than one phase row.
    """
    grouped: dict[int, list[Column]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        x = sample.get("x")
        y = sample.get("y")
        potential = sample.get("potential")
        if not isinstance(x, int) or isinstance(x, bool):
            continue
        if not isinstance(y, int) or isinstance(y, bool):
            continue
        if not isinstance(potential, (int, float)) or isinstance(potential, bool):
            continue
        grouped.setdefault(x, []).append((float(potential), y))
    frame: Frame = {}
    merged = 0
    for column, rows in grouped.items():
        if len(rows) > 1:
            merged += 1
        potential, phase = max(rows, key=lambda row: row[0])
        frame[column] = (potential, phase)
    return frame, merged


def _pair_delay(src: dict[int, Frame], dst: dict[int, Frame]) -> int:
    """Burst delay with the most input columns that reappear at the same phase."""
    best_delay = 1
    best_score = 0
    for delay in DELAYS:
        score = 0
        for burst, frame in src.items():
            output = dst.get(burst + delay)
            if output is None:
                continue
            for column, (_, phase) in frame.items():
                match = output.get(column)
                if match is not None and match[1] == phase:
                    score += 1
        if score > best_score:
            best_score = score
            best_delay = delay
    return best_delay


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def measure_frame_disparity(
    src_frames: dict[int, Frame],
    dst_frames: dict[int, Frame],
    *,
    src_merged_columns: int,
    dst_merged_columns: int,
) -> dict[str, Any]:
    """Summarize how far output frames are from the input frames that caused them.

    ``src_frames`` and ``dst_frames`` map burst number to a column frame.
    """
    if len(src_frames) < 2:
        return {
            "streaming": False,
            "input_frames": len(src_frames),
            "output_frames": len(dst_frames),
            "dominant_gap": "not_streaming",
        }
    delay = _pair_delay(src_frames, dst_frames)
    paired = 0
    dropped_frames = 0
    magnitude_errors: list[float] = []
    compared_columns = 0
    phase_mismatches = 0
    columns_missing = 0
    columns_extra = 0
    input_columns = 0
    for burst, frame in src_frames.items():
        output = dst_frames.get(burst + delay)
        input_columns += len(frame)
        if output is None:
            dropped_frames += 1
            columns_missing += len(frame)
            continue
        paired += 1
        for column, (potential, phase) in frame.items():
            match = output.get(column)
            if match is None:
                columns_missing += 1
                continue
            compared_columns += 1
            out_potential, out_phase = match
            if abs(potential - out_potential) > POTENTIAL_TOLERANCE:
                magnitude_errors.append(abs(potential - out_potential))
            if out_phase != phase:
                phase_mismatches += 1
        for column in output:
            if column not in frame:
                columns_extra += 1
    input_steps = sorted(src_frames)
    input_pairs = list(zip(input_steps, input_steps[1:], strict=False))
    skipped_between = sum(1 for left, right in input_pairs if right - left > 1)
    # Bursts between the first and last input frame that carried no new audio frame.
    # Each one is 1/burst_rate seconds of the original audio that never entered FEAGI.
    input_bursts_missing = sum(right - left - 1 for left, right in input_pairs if right > left + 1)
    input_span = input_steps[-1] - input_steps[0] + 1
    input_gap_fraction = input_bursts_missing / input_span if input_span > 0 else 0.0
    missing_fraction = columns_missing / input_columns if input_columns else 0.0
    phase_fraction = phase_mismatches / compared_columns if compared_columns else 0.0
    drop_fraction = dropped_frames / len(src_frames)
    median_error = _median(magnitude_errors)
    return {
        "streaming": True,
        "burst_delay": delay,
        "input_frames": len(src_frames),
        "output_frames": len(dst_frames),
        "paired_frames": paired,
        "dropped_frames": dropped_frames,
        "dropped_frame_fraction": round(drop_fraction, 4),
        "input_gaps": skipped_between,
        "input_bursts_missing": input_bursts_missing,
        "input_gap_fraction": round(input_gap_fraction, 4),
        "compared_columns": compared_columns,
        "columns_missing_on_output": columns_missing,
        "columns_only_on_output": columns_extra,
        "missing_column_fraction": round(missing_fraction, 4),
        "phase_mismatch_fraction": round(phase_fraction, 4),
        "median_magnitude_error": None if median_error is None else round(median_error, 4),
        "magnitude_columns_changed": len(magnitude_errors),
        "input_merged_columns": src_merged_columns,
        "output_merged_columns": dst_merged_columns,
        "dominant_gap": _dominant_gap(
            drop_fraction=drop_fraction,
            input_gap_fraction=input_gap_fraction,
            missing_fraction=missing_fraction,
            phase_fraction=phase_fraction,
            median_error=median_error,
            merged=src_merged_columns + dst_merged_columns,
        ),
    }


def _dominant_gap(
    *,
    drop_fraction: float,
    input_gap_fraction: float,
    missing_fraction: float,
    phase_fraction: float,
    median_error: float | None,
    merged: int,
) -> str:
    """Name the largest difference so the next change targets one cause.

    ``input_gaps`` means bursts went by with no new input frame. The copy through
    FEAGI can be exact and the audio still has holes, so this outranks column checks.
    """
    if merged > 0:
        return "frames_merged"
    if drop_fraction >= 0.05:
        return "frames_dropped"
    if input_gap_fraction >= 0.02:
        return "input_gaps"
    if missing_fraction >= 0.1:
        return "columns_dropped"
    if phase_fraction >= 0.05:
        return "phase_changed"
    if median_error is not None and median_error >= 0.02:
        return "magnitude_changed"
    return "close"
