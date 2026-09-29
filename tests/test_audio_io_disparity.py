"""Tests for live audio input/output disparity measurement."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.audio_io_disparity import (
    frame_from_samples,
    measure_frame_disparity,
)
from feagi_mcp.feagi_client import FeagiClient

SRC = "aWF1ZAoAAAA="
DST = "b2F1ZAoAAAA="


def _frame(*columns: tuple[int, float, int]) -> dict[int, tuple[float, int]]:
    return {column: (potential, phase) for column, potential, phase in columns}


def _measure(
    src: dict[int, dict[int, tuple[float, int]]],
    dst: dict[int, dict[int, tuple[float, int]]],
    src_merged: int = 0,
    dst_merged: int = 0,
) -> dict[str, Any]:
    return measure_frame_disparity(
        src,
        dst,
        src_merged_columns=src_merged,
        dst_merged_columns=dst_merged,
    )


class TestFrameFromSamples:
    def test_loudest_phase_row_wins_a_shared_column(self):
        frame, merged = frame_from_samples(
            [
                {"x": 3, "y": 1, "potential": 0.2},
                {"x": 3, "y": 9, "potential": 0.8},
                {"x": 4, "y": 2, "potential": 0.4},
            ]
        )
        assert merged == 1
        assert frame[3] == (0.8, 9)
        assert frame[4] == (0.4, 2)


class TestMeasureFrameDisparity:
    def test_matching_output_one_burst_later_is_close(self):
        src = {10: _frame((1, 0.5, 4), (2, 0.2, 8)), 11: _frame((1, 0.4, 5))}
        dst = {11: _frame((1, 0.5, 4), (2, 0.2, 8)), 12: _frame((1, 0.4, 5))}
        report = _measure(src, dst)
        assert report["streaming"] is True
        assert report["burst_delay"] == 1
        assert report["dominant_gap"] == "close"
        assert report["dropped_frames"] == 0
        assert report["phase_mismatch_fraction"] == 0.0

    def test_missing_output_bursts_are_dropped_frames(self):
        src = {1: _frame((1, 0.5, 1)), 2: _frame((1, 0.5, 2)), 3: _frame((1, 0.5, 3))}
        dst = {2: _frame((1, 0.5, 1))}
        report = _measure(src, dst)
        assert report["dominant_gap"] == "frames_dropped"
        assert report["dropped_frames"] == 2

    def test_phase_change_is_named_when_frames_arrive(self):
        src = {1: _frame((1, 0.5, 4)), 2: _frame((1, 0.5, 6))}
        dst = {2: _frame((1, 0.5, 9)), 3: _frame((1, 0.5, 1))}
        report = _measure(src, dst)
        assert report["dropped_frames"] == 0
        assert report["dominant_gap"] == "phase_changed"
        assert report["phase_mismatch_fraction"] == 1.0

    def test_quiet_columns_that_never_leave_are_dropped_columns(self):
        src = {1: _frame((1, 0.6, 2), (9, 0.05, 3)), 2: _frame((1, 0.6, 4), (9, 0.05, 5))}
        dst = {2: _frame((1, 0.6, 2)), 3: _frame((1, 0.6, 4))}
        report = _measure(src, dst)
        assert report["dominant_gap"] == "columns_dropped"
        assert report["columns_missing_on_output"] == 2

    def test_bursts_without_input_are_named_even_when_the_copy_is_exact(self):
        # Bursts 3, 4, 7 carried no input frame. What did arrive is copied exactly.
        steps = [1, 2, 5, 6, 8, 9, 10]
        src = {b: _frame((1, 0.5, b % 8)) for b in steps}
        dst = {b + 1: _frame((1, 0.5, b % 8)) for b in steps}
        report = _measure(src, dst)
        assert report["dropped_frames"] == 0
        assert report["input_gaps"] == 2
        assert report["input_bursts_missing"] == 3
        assert report["input_gap_fraction"] == 0.3
        assert report["dominant_gap"] == "input_gaps"

    def test_merged_columns_outrank_other_gaps(self):
        src = {1: _frame((1, 0.5, 1)), 2: _frame((1, 0.5, 1))}
        dst = {2: _frame((1, 0.5, 1)), 3: _frame((1, 0.5, 1))}
        report = _measure(src, dst, src_merged=3)
        assert report["dominant_gap"] == "frames_merged"

    def test_too_few_input_frames_is_not_streaming(self):
        report = _measure({1: _frame((1, 0.2, 1))}, {})
        assert report == {
            "streaming": False,
            "input_frames": 1,
            "output_frames": 0,
            "dominant_gap": "not_streaming",
        }


def _ok(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _snapshot(
    burst: int,
    cortical_id: str,
    columns: list[tuple[int, float, int]],
) -> dict[str, Any]:
    return {
        "burst_num": burst,
        "areas": [
            {
                "cortical_id": cortical_id,
                "samples": [
                    {"x": column, "y": phase, "z": 0, "potential": potential}
                    for column, potential, phase in columns
                ],
            }
        ],
    }


class TestClientMeasure:
    @pytest.mark.asyncio
    async def test_polls_until_the_window_closes_and_reports(self):
        client = FeagiClient()
        client._client = AsyncMock()
        calls = {"n": 0}

        def get(*_args, **_kwargs):
            index = calls["n"]
            calls["n"] += 1
            if index % 2 == 0:
                burst = 10 + index // 2
                return _ok(_snapshot(burst, SRC, [(1, 0.5, 4 + index // 2)]))
            burst = 11 + index // 2
            return _ok(_snapshot(burst, DST, [(1, 0.5, 4 + index // 2)]))

        client._client.get.side_effect = get
        report = await client.measure_audio_io_disparity(SRC, DST, duration_s=0.2)
        assert report["streaming"] is True
        assert report["burst_delay"] == 1
        assert report["input_frames"] >= 2
        assert report["polls"] >= 2
