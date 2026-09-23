"""Local-first FEAGI runtime failure classification.

``health_check`` and ``get_log_tail`` only work while the HTTP server answers.
This module classifies a stall from local logs first: desktop ``feagi-core.log``,
then ``neurorobotics-studio.log``, then an optional ``FEAGI_LOG_FILE``. When
those have no FEAGI markers it can classify the HTTP ring buffer. The report
lists every path checked so a missing core log is visible.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

_ISO_TS_RE = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)")
_QUEUED_CONFIG_RE = re.compile(
    r"Processing queued AgentConfiguration for session (?P<agent_id>\S+)"
)
_STORED_REGS_RE = re.compile(r"Stored device registrations for agent (?P<agent_id>\S+)")
_DEREGISTER_RE = re.compile(r"Agent deregistered: agent_id=(?P<agent_id>\S+)")
_UNKNOWN_AREA_RE = re.compile(r"Unknown cortical area: '(?P<cortical_id>[^']+)'")
_DELETE_NEURONS_RE = re.compile(r"Deleting (?P<count>\d+) existing neurons")

#: How many classified events to return. The full log stays on disk.
EVENT_LIMIT = 20
#: Bytes read from the end of a log file. The rest stays on disk.
LOG_READ_MAX_BYTES = 262144
#: Ring-buffer records fetched when no local FEAGI log has markers.
RING_TAIL_LIMIT = 400

KIND_EXPLICIT = "explicit_log_file"
KIND_FEAGI_CORE = "feagi_core"
KIND_DESKTOP = "desktop"
KIND_RING = "http_log_tail"

STATUS_MISSING = "missing"
STATUS_EMPTY = "empty"
STATUS_UNREADABLE = "unreadable"
STATUS_USED = "used"
STATUS_NO_MARKERS = "read_no_feagi_markers"
STATUS_NOT_CHECKED = "not_checked"
STATUS_RING_DISABLED = "ring_disabled"
STATUS_RING_FAILED = "probe_failed"

CAUSE_HEALTHY = "healthy"
CAUSE_UNREACHABLE = "feagi_unreachable"
CAUSE_HEALTH_TIMEOUT = "health_check_timeout"
CAUSE_NO_LOG_UNREACHABLE = "no_local_log_and_unreachable"
CAUSE_REBUILD_STALL = "npu_lock_during_structural_rebuild"
CAUSE_WATCHDOG = "npu_watchdog_stall"
CAUSE_OUTSTANDING_REPLY = "outstanding_control_reply_then_client_stop"
CAUSE_MISSING_NPU_REG = "npu_missing_cortical_registration"
CAUSE_DEREGISTERED = "agent_deregistered"


def parse_log_timestamp_ms(line: str) -> int | None:
    """Parse a FEAGI core ISO timestamp into unix milliseconds."""
    match = _ISO_TS_RE.search(line)
    if match is None:
        return None
    raw_ts = match.group("ts")
    try:
        parsed = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def classify_feagi_core_log_line(line: str) -> dict[str, Any] | None:
    """Return one classified event, or None when the line is not diagnostic."""
    if "[NPU-WATCHDOG] Burst loop stalled" in line:
        kind = "npu_watchdog_stall"
        extra: dict[str, Any] = {}
    elif "[STRUCTURAL-REBUILD] Deleting" in line:
        kind = "structural_rebuild_delete_started"
        count_match = _DELETE_NEURONS_RE.search(line)
        extra = {"neuron_count": int(count_match.group("count"))} if count_match else {}
    elif "[STRUCTURAL-REBUILD] Deleted" in line or "[STRUCTURAL-REBUILD] Complete:" in line:
        kind = "structural_rebuild_finished"
        extra = {}
    elif (
        "[STRUCTURAL-REBUILD] Starting" in line or "[STRUCTURAL-REBUILD] Localized rebuild" in line
    ):
        kind = "structural_rebuild_started"
        extra = {}
    elif "Unknown cortical area:" in line:
        kind = "unknown_cortical_area"
        area_match = _UNKNOWN_AREA_RE.search(line)
        extra = {"cortical_id": area_match.group("cortical_id")} if area_match else {}
    elif "Processing queued AgentConfiguration" in line:
        kind = "agent_configuration_queued"
        queued = _QUEUED_CONFIG_RE.search(line)
        extra = {"agent_id": queued.group("agent_id")} if queued else {}
    elif "Stored device registrations for agent" in line:
        kind = "agent_configuration_stored"
        stored = _STORED_REGS_RE.search(line)
        extra = {"agent_id": stored.group("agent_id")} if stored else {}
    elif "Agent deregistered:" in line:
        kind = "agent_deregistered"
        dereg = _DEREGISTER_RE.search(line)
        extra = {"agent_id": dereg.group("agent_id")} if dereg else {}
    elif "Synced" in line and "cortical IDs into the NPU name map" in line:
        kind = "npu_cortical_ids_synced"
        extra = {}
    else:
        return None

    event: dict[str, Any] = {
        "kind": kind,
        "timestamp_ms": parse_log_timestamp_ms(line),
        "message": line.strip(),
    }
    event.update(extra)
    return event


def classify_feagi_core_log_lines(lines: list[str]) -> dict[str, Any]:
    """Classify a FEAGI core log into a compact stall diagnosis."""
    events: list[dict[str, Any]] = []
    for line in lines:
        event = classify_feagi_core_log_line(line)
        if event is not None:
            events.append(event)

    rebuild_open = False
    outstanding_reply = False
    last_config_agent: str | None = None
    unknown_ids: list[str] = []
    for event in events:
        kind = event["kind"]
        if kind in {"structural_rebuild_started", "structural_rebuild_delete_started"}:
            rebuild_open = True
        elif kind == "structural_rebuild_finished":
            rebuild_open = False
        if kind in {"agent_configuration_queued", "agent_configuration_stored"}:
            last_config_agent = event.get("agent_id")
            outstanding_reply = True
        elif kind == "npu_cortical_ids_synced":
            outstanding_reply = False
        elif kind == "agent_deregistered":
            same_agent = last_config_agent is None or event.get("agent_id") == last_config_agent
            outstanding_reply = outstanding_reply and same_agent
        if kind == "unknown_cortical_area":
            cortical_id = event.get("cortical_id")
            if isinstance(cortical_id, str) and cortical_id not in unknown_ids:
                unknown_ids.append(cortical_id)

    watchdog_stall = any(event["kind"] == "npu_watchdog_stall" for event in events)
    deregistered = bool(events) and events[-1]["kind"] == "agent_deregistered"
    likely_cause = _likely_cause(
        rebuild_open=rebuild_open,
        watchdog_stall=watchdog_stall,
        outstanding_reply=outstanding_reply,
        deregistered=deregistered,
        unknown_ids=unknown_ids,
    )
    last_event = events[-1] if events else None
    return {
        "event_count": len(events),
        "events": events[-EVENT_LIMIT:],
        "likely_cause": likely_cause,
        "structural_rebuild_open": rebuild_open,
        "npu_watchdog_stall": watchdog_stall,
        "outstanding_control_reply": outstanding_reply and deregistered,
        "unknown_cortical_ids": unknown_ids[:16],
        "last_event": last_event,
        "last_timestamp_ms": last_event.get("timestamp_ms") if last_event else None,
    }


def _likely_cause(
    *,
    rebuild_open: bool,
    watchdog_stall: bool,
    outstanding_reply: bool,
    deregistered: bool,
    unknown_ids: list[str],
) -> str:
    """Pick the highest-priority cause from classified evidence."""
    if rebuild_open and watchdog_stall:
        return CAUSE_REBUILD_STALL
    if outstanding_reply and deregistered:
        return CAUSE_OUTSTANDING_REPLY
    if unknown_ids:
        return CAUSE_MISSING_NPU_REG
    if watchdog_stall:
        return CAUSE_WATCHDOG
    if deregistered:
        return CAUSE_DEREGISTERED
    return CAUSE_HEALTHY


def combine_runtime_diagnosis(
    *,
    log_diagnosis: dict[str, Any] | None,
    http_reachable: bool,
    http_error_type: str | None,
) -> dict[str, Any]:
    """Merge local log classification with a short HTTP probe."""
    log_cause = log_diagnosis.get("likely_cause") if log_diagnosis else None
    if log_cause in {
        CAUSE_REBUILD_STALL,
        CAUSE_OUTSTANDING_REPLY,
        CAUSE_MISSING_NPU_REG,
        CAUSE_WATCHDOG,
    }:
        likely_cause = log_cause
    elif not http_reachable:
        if http_error_type in {"read_timeout", "connect_timeout", "timeout"}:
            likely_cause = CAUSE_HEALTH_TIMEOUT
        elif log_diagnosis is None:
            likely_cause = CAUSE_NO_LOG_UNREACHABLE
        else:
            likely_cause = CAUSE_UNREACHABLE
    else:
        likely_cause = log_cause or CAUSE_HEALTHY

    report: dict[str, Any] = {
        "likely_cause": likely_cause,
        "http_reachable": http_reachable,
        "http_error_type": http_error_type,
        "log_available": log_diagnosis is not None,
    }
    if log_diagnosis is not None:
        report.update(log_diagnosis)
        report["likely_cause"] = likely_cause
    return report


def read_log_tail_lines(path: Path, max_bytes: int) -> list[str]:
    """Read the tail of a log file without loading the whole file."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, 2)
            data = handle.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes and "\n" in text:
        text = text.split("\n", 1)[1]
    return text.splitlines()


def local_log_candidate_paths(
    *,
    session_dir: Path | None,
    explicit_log_file: Path | None,
) -> list[tuple[str, Path]]:
    """Return local log paths in precedence order, without reading them."""
    ordered: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def add(kind: str, path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        ordered.append((kind, path))

    if explicit_log_file is not None:
        add(KIND_EXPLICIT, explicit_log_file)
    if session_dir is not None:
        add(KIND_FEAGI_CORE, session_dir / "feagi" / "feagi-core.log")
        add(KIND_DESKTOP, session_dir / "neurorobotics-studio" / "neurorobotics-studio.log")
        try:
            extras = sorted(session_dir.rglob("feagi-core.log"))
        except OSError:
            extras = []
        for extra in extras:
            add(KIND_FEAGI_CORE, extra)
    return ordered


def select_local_log_diagnosis(
    candidates: list[tuple[str, Path]],
    max_bytes: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None, Path | None]:
    """Classify the first local log that is a FEAGI source or has markers."""
    checks: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    selected_kind: str | None = None
    selected_path: Path | None = None
    for kind, path in candidates:
        if selected is not None:
            checks.append({"path": str(path), "kind": kind, "status": STATUS_NOT_CHECKED})
            continue
        if not path.is_file():
            checks.append({"path": str(path), "kind": kind, "status": STATUS_MISSING})
            continue
        try:
            size = path.stat().st_size
        except OSError:
            checks.append({"path": str(path), "kind": kind, "status": STATUS_UNREADABLE})
            continue
        if size == 0:
            checks.append({"path": str(path), "kind": kind, "status": STATUS_EMPTY, "bytes": 0})
            continue
        lines = read_log_tail_lines(path, max_bytes)
        diagnosis = classify_feagi_core_log_lines(lines)
        event_count = int(diagnosis["event_count"])
        authoritative = kind in {KIND_FEAGI_CORE, KIND_EXPLICIT}
        if authoritative or event_count > 0:
            checks.append(
                {
                    "path": str(path),
                    "kind": kind,
                    "status": STATUS_USED,
                    "bytes": size,
                    "event_count": event_count,
                }
            )
            selected = diagnosis
            selected_kind = kind
            selected_path = path
            continue
        checks.append(
            {
                "path": str(path),
                "kind": kind,
                "status": STATUS_NO_MARKERS,
                "bytes": size,
                "event_count": 0,
            }
        )
    return selected, checks, selected_kind, selected_path


def lines_from_log_tail_records(records: list[Any]) -> list[str]:
    """Turn ring-buffer records into classifier lines. Drops empty messages."""
    lines: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        message = record.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        if _ISO_TS_RE.search(message):
            lines.append(message)
            continue
        level = str(record.get("level") or "").strip()
        target = str(record.get("target") or "").strip()
        prefix = " ".join(part for part in (level, target) if part)
        lines.append(f"{prefix}: {message}" if prefix else message)
    return lines


def log_missing_reason(paths_checked: list[dict[str, Any]]) -> str:
    """Explain why no FEAGI log source was selected."""
    kinds = {str(item.get("kind")): str(item.get("status")) for item in paths_checked}
    core_missing = kinds.get(KIND_FEAGI_CORE) == STATUS_MISSING
    desktop_empty = kinds.get(KIND_DESKTOP) == STATUS_NO_MARKERS
    if core_missing and desktop_empty:
        return "no_feagi_core_log_and_no_markers_in_desktop"
    if all(item.get("status") == STATUS_MISSING for item in paths_checked):
        return "no_local_log_files"
    return "no_classified_feagi_markers"
