"""Tests for local-first FEAGI runtime diagnosis.

Classifies real feagi-core log text. The HTTP probe uses a refused connection
or a hanging socket; the classifier itself is not mocked.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.runtime_diagnostics import (
    CAUSE_DEREGISTERED,
    CAUSE_HEALTH_TIMEOUT,
    CAUSE_HEALTHY,
    CAUSE_MISSING_NPU_REG,
    CAUSE_NO_LOG_UNREACHABLE,
    CAUSE_OUTSTANDING_REPLY,
    CAUSE_REBUILD_STALL,
    CAUSE_UNREACHABLE,
    CAUSE_WATCHDOG,
    KIND_DESKTOP,
    KIND_EXPLICIT,
    KIND_FEAGI_CORE,
    KIND_RING,
    STATUS_MISSING,
    STATUS_NO_MARKERS,
    STATUS_USED,
    classify_feagi_core_log_line,
    classify_feagi_core_log_lines,
    combine_runtime_diagnosis,
    lines_from_log_tail_records,
    local_log_candidate_paths,
    log_missing_reason,
    select_local_log_diagnosis,
)

REBUILD_OPEN_LINES = [
    (
        "2026-09-22T18:12:01.123456Z  INFO feagi_services: "
        "[STRUCTURAL-REBUILD] Localized rebuild for aWltZwkAAAA="
    ),
    (
        "2026-09-22T18:12:01.223456Z  INFO feagi_services: "
        "[STRUCTURAL-REBUILD] Starting localized rebuild for aWltZwkAAAA="
    ),
    (
        "2026-09-22T18:12:01.323456Z  INFO feagi_services: "
        "[STRUCTURAL-REBUILD] Deleting 147456 existing neurons"
    ),
    (
        "2026-09-22T18:12:08.123456Z  WARN feagi_rs: [NPU-WATCHDOG] Burst loop stalled: "
        "no progress for 5.0s (burst_count=1200) - possible deadlock or NPU lock contention"
    ),
]

REBUILD_FINISHED_LINES = [
    (
        "2026-09-22T18:12:01.123456Z  INFO feagi_services: "
        "[STRUCTURAL-REBUILD] Starting localized rebuild for aWltZwkAAAA="
    ),
    (
        "2026-09-22T18:12:01.223456Z  INFO feagi_services: "
        "[STRUCTURAL-REBUILD] Deleting 10 existing neurons"
    ),
    "2026-09-22T18:12:01.323456Z  INFO feagi_services: [STRUCTURAL-REBUILD] Deleted 10 neurons",
    (
        "2026-09-22T18:12:02.000000Z  INFO feagi_services: "
        "[STRUCTURAL-REBUILD] Complete: 10 neurons, 0 outgoing, 0 incoming synapses"
    ),
]

QUEUED_THEN_STOP_LINES = [
    (
        "2026-09-22T19:01:00.000000Z  INFO feagi_rs: "
        "[MOTOR-REG] Processing queued AgentConfiguration for session agent-abc"
    ),
    (
        "2026-09-22T19:01:00.100000Z  INFO feagi_agent: "
        "Stored device registrations for agent agent-abc"
    ),
    (
        "2026-09-22T19:01:02.000000Z  INFO feagi_agent: "
        "Agent deregistered: agent_id=agent-abc descriptor=true reason=client_requested"
    ),
]

QUEUED_SYNC_THEN_STOP_LINES = [
    (
        "2026-09-22T19:01:00.000000Z  INFO feagi_rs: "
        "[MOTOR-REG] Processing queued AgentConfiguration for session agent-abc"
    ),
    (
        "2026-09-22T19:01:00.200000Z  INFO feagi_api: "
        "[API] Synced 32 cortical IDs into the NPU name map after agent auto-create"
    ),
    (
        "2026-09-22T19:01:02.000000Z  INFO feagi_agent: "
        "Agent deregistered: agent_id=agent-abc descriptor=true reason=client_requested"
    ),
]

UNKNOWN_ISVI_LINES = [
    (
        "2026-09-22T20:00:00.000000Z  WARN feagi_npu: "
        "[NPU] Unknown cortical area: 'aXN2aQkAAQA=' (base64: aXN2aQkAAQA=)"
    ),
    (
        "2026-09-22T20:00:00.100000Z  WARN feagi_npu: "
        "[NPU] Unknown cortical area: 'aXN2aQkAAwA=' (base64: aXN2aQkAAwA=)"
    ),
]


def _session_dir(runtime_root: Path) -> Path:
    session = (
        runtime_root
        / "logs"
        / "neurorobotics-studio"
        / "fds_runtime_logs"
        / "session_diagnose_test"
    )
    session.mkdir(parents=True, exist_ok=True)
    return session


def _session_log(runtime_root: Path, lines: list[str]) -> Path:
    log_path = _session_dir(runtime_root) / "feagi" / "feagi-core.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


def _desktop_log(runtime_root: Path, lines: list[str]) -> Path:
    log_path = _session_dir(runtime_root) / "neurorobotics-studio" / "neurorobotics-studio.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


def _start_json_http_server(
    routes: dict[str, dict[str, object]],
) -> tuple[ThreadingHTTPServer, int]:
    """Serve fixed JSON GET routes. Caller must shut down the server."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            payload = routes.get(path)
            if payload is None:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("localhost", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1])


class TestClassifyFeagiCoreLogLine:
    def test_rebuild_delete_extracts_neuron_count(self) -> None:
        event = classify_feagi_core_log_line(REBUILD_OPEN_LINES[2])
        assert event is not None
        assert event["kind"] == "structural_rebuild_delete_started"
        assert event["neuron_count"] == 147456
        assert event["timestamp_ms"] == 1790100721323

    def test_unknown_area_extracts_cortical_id(self) -> None:
        event = classify_feagi_core_log_line(UNKNOWN_ISVI_LINES[0])
        assert event is not None
        assert event["kind"] == "unknown_cortical_area"
        assert event["cortical_id"] == "aXN2aQkAAQA="

    def test_ignores_unrelated_lines(self) -> None:
        assert classify_feagi_core_log_line("2026-09-22T18:12:01.123456Z  INFO other: idle") is None


class TestClassifyFeagiCoreLogLines:
    def test_rebuild_plus_watchdog_is_npu_lock_stall(self) -> None:
        report = classify_feagi_core_log_lines(REBUILD_OPEN_LINES)
        assert report["likely_cause"] == CAUSE_REBUILD_STALL
        assert report["structural_rebuild_open"] is True
        assert report["npu_watchdog_stall"] is True
        assert report["event_count"] == 4

    def test_finished_rebuild_is_healthy(self) -> None:
        report = classify_feagi_core_log_lines(REBUILD_FINISHED_LINES)
        assert report["likely_cause"] == CAUSE_HEALTHY
        assert report["structural_rebuild_open"] is False

    def test_queued_config_then_stop_is_outstanding_reply(self) -> None:
        report = classify_feagi_core_log_lines(QUEUED_THEN_STOP_LINES)
        assert report["likely_cause"] == CAUSE_OUTSTANDING_REPLY
        assert report["outstanding_control_reply"] is True

    def test_sync_before_stop_is_deregistered_not_outstanding(self) -> None:
        report = classify_feagi_core_log_lines(QUEUED_SYNC_THEN_STOP_LINES)
        assert report["likely_cause"] == CAUSE_DEREGISTERED
        assert report["outstanding_control_reply"] is False

    def test_unknown_cortical_ids_are_missing_npu_registration(self) -> None:
        report = classify_feagi_core_log_lines(UNKNOWN_ISVI_LINES)
        assert report["likely_cause"] == CAUSE_MISSING_NPU_REG
        assert report["unknown_cortical_ids"] == ["aXN2aQkAAQA=", "aXN2aQkAAwA="]

    def test_watchdog_alone_is_watchdog_stall(self) -> None:
        report = classify_feagi_core_log_lines([REBUILD_OPEN_LINES[3]])
        assert report["likely_cause"] == CAUSE_WATCHDOG


class TestCombineRuntimeDiagnosis:
    def test_log_stall_wins_over_http_timeout(self) -> None:
        log_diagnosis = classify_feagi_core_log_lines(REBUILD_OPEN_LINES)
        report = combine_runtime_diagnosis(
            log_diagnosis=log_diagnosis,
            http_reachable=False,
            http_error_type="read_timeout",
        )
        assert report["likely_cause"] == CAUSE_REBUILD_STALL
        assert report["http_reachable"] is False

    def test_timeout_without_stall_evidence(self) -> None:
        report = combine_runtime_diagnosis(
            log_diagnosis=classify_feagi_core_log_lines(REBUILD_FINISHED_LINES),
            http_reachable=False,
            http_error_type="read_timeout",
        )
        assert report["likely_cause"] == CAUSE_HEALTH_TIMEOUT

    def test_no_log_and_unreachable(self) -> None:
        report = combine_runtime_diagnosis(
            log_diagnosis=None,
            http_reachable=False,
            http_error_type="connect_error",
        )
        assert report["likely_cause"] == CAUSE_NO_LOG_UNREACHABLE

    def test_log_without_stall_and_unreachable(self) -> None:
        report = combine_runtime_diagnosis(
            log_diagnosis=classify_feagi_core_log_lines(REBUILD_FINISHED_LINES),
            http_reachable=False,
            http_error_type="connect_error",
        )
        assert report["likely_cause"] == CAUSE_UNREACHABLE

    def test_healthy_when_http_answers_and_log_is_clean(self) -> None:
        report = combine_runtime_diagnosis(
            log_diagnosis=classify_feagi_core_log_lines(REBUILD_FINISHED_LINES),
            http_reachable=True,
            http_error_type=None,
        )
        assert report["likely_cause"] == CAUSE_HEALTHY


class TestDiagnoseFeagiRuntime:
    @pytest.mark.asyncio
    async def test_reads_session_log_then_refused_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log_path = _session_log(tmp_path, REBUILD_OPEN_LINES)
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        client = FeagiClient(host="localhost", port=1, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.5)
        finally:
            await client.close()
        assert report["likely_cause"] == CAUSE_REBUILD_STALL
        assert report["http_reachable"] is False
        assert report["http_error_type"] == "connect_error"
        assert report["feagi_core_log"] == str(log_path)
        assert report["log_source"] == KIND_FEAGI_CORE
        assert report["probe_timeout_seconds"] == 0.5
        assert "147456 existing neurons" in report["events"][2]["message"]
        assert report["paths_checked"][0]["status"] == STATUS_USED

    @pytest.mark.asyncio
    async def test_no_session_log_and_refused_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        client = FeagiClient(host="localhost", port=1, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.5)
        finally:
            await client.close()
        assert report["likely_cause"] == CAUSE_NO_LOG_UNREACHABLE
        assert report["log_available"] is False
        assert report["log_source"] is None
        assert report["log_missing_reason"] == "no_local_log_files"

    @pytest.mark.asyncio
    async def test_probe_timeout_does_not_use_client_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _session_log(tmp_path, REBUILD_FINISHED_LINES)
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        hang = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        hang.bind(("localhost", 0))
        hang.listen(1)
        port = hang.getsockname()[1]
        accepted: list[socket.socket] = []

        def _accept() -> None:
            conn, _unused = hang.accept()
            accepted.append(conn)

        acceptor = threading.Thread(target=_accept, daemon=True)
        acceptor.start()
        client = FeagiClient(host="localhost", port=port, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.4)
        finally:
            await client.close()
            for conn in accepted:
                conn.close()
            hang.close()
        assert report["likely_cause"] == CAUSE_HEALTH_TIMEOUT
        assert report["http_error_type"] in {"read_timeout", "timeout"}
        assert report["probe_timeout_seconds"] == 0.4


class TestLocalLogCandidates:
    def test_session_order_is_core_then_desktop(self, tmp_path: Path) -> None:
        session = _session_dir(tmp_path)
        candidates = local_log_candidate_paths(session_dir=session, explicit_log_file=None)
        kinds = [kind for kind, _path in candidates]
        assert kinds[:2] == [KIND_FEAGI_CORE, KIND_DESKTOP]

    def test_explicit_log_file_is_first(self, tmp_path: Path) -> None:
        explicit = tmp_path / "standalone.log"
        session = _session_dir(tmp_path)
        candidates = local_log_candidate_paths(
            session_dir=session,
            explicit_log_file=explicit,
        )
        assert candidates[0] == (KIND_EXPLICIT, explicit)

    def test_desktop_markers_are_selected_when_core_missing(self, tmp_path: Path) -> None:
        desktop = _desktop_log(tmp_path, REBUILD_OPEN_LINES)
        session = desktop.parent.parent
        selected, checks, kind, path = select_local_log_diagnosis(
            local_log_candidate_paths(session_dir=session, explicit_log_file=None),
            max_bytes=65536,
        )
        assert kind == KIND_DESKTOP
        assert path == desktop
        assert selected is not None
        assert selected["likely_cause"] == CAUSE_REBUILD_STALL
        statuses = {item["kind"]: item["status"] for item in checks}
        assert statuses[KIND_FEAGI_CORE] == STATUS_MISSING
        assert statuses[KIND_DESKTOP] == STATUS_USED

    def test_desktop_without_markers_is_not_a_feagi_source(self, tmp_path: Path) -> None:
        desktop = _desktop_log(
            tmp_path,
            ["2026-09-22T20:40:00.000000Z  INFO desktop: window focused"],
        )
        session = desktop.parent.parent
        selected, checks, kind, path = select_local_log_diagnosis(
            local_log_candidate_paths(session_dir=session, explicit_log_file=None),
            max_bytes=65536,
        )
        assert selected is None
        assert kind is None
        assert path is None
        statuses = {item["kind"]: item["status"] for item in checks}
        assert statuses[KIND_FEAGI_CORE] == STATUS_MISSING
        assert statuses[KIND_DESKTOP] == STATUS_NO_MARKERS
        assert log_missing_reason(checks) == "no_feagi_core_log_and_no_markers_in_desktop"

    def test_ring_records_become_classifier_lines(self) -> None:
        lines = lines_from_log_tail_records(
            [{"level": "WARN", "target": "feagi_npu", "message": UNKNOWN_ISVI_LINES[0]}]
        )
        report = classify_feagi_core_log_lines(lines)
        assert report["likely_cause"] == CAUSE_MISSING_NPU_REG


class TestDiagnoseAlternateSources:
    @pytest.mark.asyncio
    async def test_classifies_desktop_log_when_core_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        desktop = _desktop_log(tmp_path, REBUILD_OPEN_LINES)
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        client = FeagiClient(host="localhost", port=1, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.5)
        finally:
            await client.close()
        assert report["likely_cause"] == CAUSE_REBUILD_STALL
        assert report["log_source"] == KIND_DESKTOP
        assert report["feagi_core_log"] == str(desktop)

    @pytest.mark.asyncio
    async def test_classifies_explicit_log_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        explicit = tmp_path / "feagi-stdout.log"
        explicit.write_text("\n".join(UNKNOWN_ISVI_LINES) + "\n", encoding="utf-8")
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        monkeypatch.setenv("FEAGI_LOG_FILE", str(explicit))
        client = FeagiClient(host="localhost", port=1, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.5)
        finally:
            await client.close()
        assert report["likely_cause"] == CAUSE_MISSING_NPU_REG
        assert report["log_source"] == KIND_EXPLICIT
        assert report["feagi_core_log"] == str(explicit)

    @pytest.mark.asyncio
    async def test_uses_http_ring_when_local_logs_have_no_markers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _desktop_log(
            tmp_path,
            ["2026-09-22T20:40:00.000000Z  INFO desktop: window focused"],
        )
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        server, port = _start_json_http_server(
            {
                "/v1/system/health_check": {"status": "ok"},
                "/v1/system/log_tail": {
                    "enabled": True,
                    "capacity": 2000,
                    "returned": 1,
                    "records": [
                        {
                            "level": "WARN",
                            "target": "feagi_npu",
                            "message": UNKNOWN_ISVI_LINES[0],
                        }
                    ],
                },
            }
        )
        client = FeagiClient(host="localhost", port=port, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.5)
        finally:
            await client.close()
            server.shutdown()
        assert report["likely_cause"] == CAUSE_MISSING_NPU_REG
        assert report["log_source"] == KIND_RING
        assert report["http_reachable"] is True
        ring_checks = [item for item in report["paths_checked"] if item["kind"] == KIND_RING]
        assert ring_checks[0]["status"] == STATUS_USED

    @pytest.mark.asyncio
    async def test_reports_paths_when_desktop_has_no_markers_and_http_is_down(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _desktop_log(
            tmp_path,
            ["2026-09-22T20:40:00.000000Z  INFO desktop: window focused"],
        )
        monkeypatch.setenv("FEAGI_RUNTIME_ROOT", str(tmp_path))
        client = FeagiClient(host="localhost", port=1, timeout=30.0)
        try:
            report = await client.diagnose_feagi_runtime(probe_timeout_seconds=0.5)
        finally:
            await client.close()
        assert report["likely_cause"] == CAUSE_NO_LOG_UNREACHABLE
        assert report["log_missing_reason"] == "no_feagi_core_log_and_no_markers_in_desktop"
        statuses = {item["kind"]: item["status"] for item in report["paths_checked"]}
        assert statuses[KIND_FEAGI_CORE] == STATUS_MISSING
        assert statuses[KIND_DESKTOP] == STATUS_NO_MARKERS
