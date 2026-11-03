"""Brain Hub block datasheet (``feagi.datasheet/1``): author-field validation and port checks.

Pure functions, no I/O. The contract is shared with Composer, which owns every GENERATED field
(burst, port name/dir/shape/drive/latency, level). This module never derives those; it only

* validates the AUTHOR and MEASURED fields an agent writes to a datasheet draft, and
* compares one datasheet port row with a live area's inspected properties
  (:func:`check_port_contract`).

The datasheet is inert descriptive data; nothing in it is executed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation

DATASHEET_FORMAT = "feagi.datasheet/1"

MAX_DOC_BYTES = 128 * 1024
MAX_TEXT_CHARS = 2000
MAX_PORTS = 64
MAX_HOST_REQUIREMENTS = 20
MAX_MEASURED = 64
MAX_BENCH_TESTS = 32
MAX_MISTAKES = 20
MAX_NOTES = 10

#: The one shared vocabulary (code, code_source, kind, frame, positioning). The same file is
#: copied into each repo that validates a datasheet; a unit test asserts the enums equal it.
VOCABULARY_PATH = Path(__file__).with_name("datasheet-vocabulary.json")
VOCABULARY: dict[str, tuple[str, ...]] = {
    key: tuple(values)
    for key, values in json.loads(VOCABULARY_PATH.read_text(encoding="utf-8")).items()
}
CODE_ENUM = VOCABULARY["code"]
CODE_SOURCE_ENUM = VOCABULARY["code_source"]
KIND_ENUM = VOCABULARY["kind"]
FRAME_ENUM = VOCABULARY["frame"]
POSITIONING_ENUM = VOCABULARY["positioning"]
PORT_DIR_ENUM = ("in", "out")
MAX_FITS = 8

#: Top-level keys the author may send. Anything else is rejected unless generated.
AUTHOR_TOP_KEYS = frozenset(
    {
        "format",
        "block",
        "ports",
        "host_requirements",
        "characterised_on",
        "measured",
        "bench_tests",
        "acceptance",
        "mistakes",
        "notes",
    }
)
#: Top-level keys Composer computes; accepted and ignored (never an error).
GENERATED_TOP_KEYS = frozenset({"level", "burst", "dependencies"})
#: Mandatory author keys per port: the key must be present; ``None`` means unknown and may
#: publish; an absent key blocks publish (see :func:`missing_mandatory_keys`).
MANDATORY_PORT_KEYS = (
    "function",
    "code",
    "code_source",
    "kind",
    "signed",
    "frame",
    "positioning",
    "hold",
    "zero",
    "positive",
    "if_silent",
)
_OPTIONAL_PORT_KEYS = ("quantity", "unit", "range", "min_bins_that_pass", "fits")
AUTHOR_PORT_KEYS = frozenset({"name", *MANDATORY_PORT_KEYS, *_OPTIONAL_PORT_KEYS})
GENERATED_PORT_KEYS = frozenset({"area_id", "dir", "shape", "drive", "latency_bursts", "bins"})
_PORT_TEXT_KEYS = ("function", "hold", "zero", "positive", "if_silent", "quantity", "unit", "range")
_FITS_KEYS = frozenset({"io_kind", "frame", "positioning", "min_bins", "note"})

_BLOCK_KEYS = frozenset({"name", "behavior"})
_CHARACTERISED_KEYS = frozenset(
    {"plant_class", "size", "mass", "time_constant", "dof", "control_rate_hz"}
)
_MEASURED_KEYS = frozenset(
    {
        "from",
        "to",
        "sign",
        "gain",
        "lag_bursts",
        "test",
        "bin_map",
        "latency_bursts",
        "suppression",
        "gate",
        "burst_hz",
    }
)
_BENCH_KEYS = frozenset({"description", "tool", "expect"})
_ACCEPTANCE_KEYS = frozenset({"tool", "expect", "result", "conditions"})
_NOTE_KEYS = frozenset({"body", "text"})


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_keys(obj: dict[str, Any], allowed: frozenset[str], where: str, out: list[str]) -> None:
    for key in sorted(set(obj) - allowed):
        out.append(f"{where}: unknown key {key!r}")


def _check_text(value: Any, where: str, out: list[str], *, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        out.append(f"{where}: must be a string")
    elif len(value) > MAX_TEXT_CHARS:
        out.append(f"{where}: {len(value)} chars exceeds the {MAX_TEXT_CHARS} limit")


def _check_list(value: Any, where: str, cap: int, out: list[str]) -> list[Any]:
    if not isinstance(value, list):
        out.append(f"{where}: must be a list")
        return []
    if len(value) > cap:
        out.append(f"{where}: {len(value)} entries exceeds the cap of {cap}")
    return value[:cap]


def _check_object(
    value: Any,
    allowed: frozenset[str],
    where: str,
    text_keys: tuple[str, ...],
    out: list[str],
) -> None:
    if not isinstance(value, dict):
        out.append(f"{where}: must be an object")
        return
    _check_keys(value, allowed, where, out)
    for key in text_keys:
        if key in value:
            _check_text(value[key], f"{where}.{key}", out)


def validate_author_fields(doc: Any) -> list[str]:
    """Return problems in the author and measured fields of a datasheet draft (empty = valid).

    Mirrors the ``feagi.datasheet/1`` contract: enums, text and list caps, document size, and
    unknown keys. Generated fields (``level``, ``burst`` and per port ``area_id``, ``dir``,
    ``shape``, ``drive``, ``latency_bursts``) are ignored, not validated and not an error.
    Structural agreement with the release artifact is checked by Composer, not here.
    """
    out: list[str] = []
    if not isinstance(doc, dict):
        return ["datasheet: must be an object"]
    try:
        size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return ["datasheet: not JSON-serialisable"]
    if size > MAX_DOC_BYTES:
        out.append(f"datasheet: {size} bytes exceeds the {MAX_DOC_BYTES} byte limit")

    _check_keys(doc, AUTHOR_TOP_KEYS | GENERATED_TOP_KEYS, "datasheet", out)
    if "format" in doc and doc["format"] != DATASHEET_FORMAT:
        out.append(f"format: must be {DATASHEET_FORMAT!r}")

    if "block" in doc:
        _check_object(doc["block"], _BLOCK_KEYS, "block", ("name", "behavior"), out)

    if "ports" in doc:
        for i, port in enumerate(_check_list(doc["ports"], "ports", MAX_PORTS, out)):
            _validate_port(port, f"ports[{i}]", out)

    if "host_requirements" in doc:
        for i, item in enumerate(
            _check_list(doc["host_requirements"], "host_requirements", MAX_HOST_REQUIREMENTS, out)
        ):
            _check_text(item, f"host_requirements[{i}]", out, nullable=False)

    if doc.get("characterised_on") is not None:
        co = doc["characterised_on"]
        _check_object(
            co,
            _CHARACTERISED_KEYS,
            "characterised_on",
            ("plant_class", "size", "mass", "time_constant"),
            out,
        )
        if isinstance(co, dict):
            if co.get("dof") is not None and not _is_int(co["dof"]):
                out.append("characterised_on.dof: must be an integer or null")
            if co.get("control_rate_hz") is not None and not _is_num(co["control_rate_hz"]):
                out.append("characterised_on.control_rate_hz: must be a number or null")

    if "measured" in doc:
        for i, row in enumerate(_check_list(doc["measured"], "measured", MAX_MEASURED, out)):
            where = f"measured[{i}]"
            _check_object(
                row,
                _MEASURED_KEYS,
                where,
                ("from", "to", "sign", "test", "bin_map", "suppression"),
                out,
            )
            if isinstance(row, dict):
                if row.get("gain") is not None and not _is_num(row["gain"]):
                    out.append(f"{where}.gain: must be a number or null")
                if row.get("lag_bursts") is not None and not _is_int(row["lag_bursts"]):
                    out.append(f"{where}.lag_bursts: must be an integer or null")
                if row.get("latency_bursts") is not None and not _is_int(row["latency_bursts"]):
                    out.append(f"{where}.latency_bursts: must be an integer or null")
                if row.get("burst_hz") is not None and not _is_num(row["burst_hz"]):
                    out.append(f"{where}.burst_hz: must be a number or null")
                if row.get("gate") is not None and not isinstance(row["gate"], bool):
                    out.append(f"{where}.gate: must be a boolean or null")

    if "bench_tests" in doc:
        for i, row in enumerate(
            _check_list(doc["bench_tests"], "bench_tests", MAX_BENCH_TESTS, out)
        ):
            _check_object(
                row, _BENCH_KEYS, f"bench_tests[{i}]", ("description", "tool", "expect"), out
            )

    if doc.get("acceptance") is not None:
        _check_object(
            doc["acceptance"],
            _ACCEPTANCE_KEYS,
            "acceptance",
            ("tool", "expect", "result", "conditions"),
            out,
        )

    if "mistakes" in doc:
        for i, item in enumerate(_check_list(doc["mistakes"], "mistakes", MAX_MISTAKES, out)):
            _check_text(item, f"mistakes[{i}]", out, nullable=False)

    if "notes" in doc:
        for i, row in enumerate(_check_list(doc["notes"], "notes", MAX_NOTES, out)):
            _check_object(row, _NOTE_KEYS, f"notes[{i}]", ("body", "text"), out)
    return out


def _validate_port(port: Any, where: str, out: list[str]) -> None:
    if not isinstance(port, dict):
        out.append(f"{where}: must be an object")
        return
    _check_keys(port, AUTHOR_PORT_KEYS | GENERATED_PORT_KEYS, where, out)
    name = port.get("name")
    if not isinstance(name, str) or not name.strip():
        out.append(f"{where}.name: required, the port's area name")
    elif len(name) > MAX_TEXT_CHARS:
        out.append(f"{where}.name: exceeds {MAX_TEXT_CHARS} chars")
    for key in _PORT_TEXT_KEYS:
        if key in port:
            _check_text(port[key], f"{where}.{key}", out)
    for key, allowed in (
        ("code", CODE_ENUM),
        ("code_source", CODE_SOURCE_ENUM),
        ("kind", KIND_ENUM),
        ("frame", FRAME_ENUM),
        ("positioning", POSITIONING_ENUM),
    ):
        if port.get(key) is not None and port[key] not in allowed:
            out.append(f"{where}.{key}: must be one of {list(allowed)} or null")
    signed = port.get("signed")
    if signed is not None and not isinstance(signed, bool):
        out.append(f"{where}.signed: must be a boolean or null")
    kind = port.get("kind")
    if isinstance(signed, bool) and kind in KIND_ENUM:
        if kind.startswith("SignedPercentage") and not signed:
            out.append(f"{where}.signed: kind {kind} requires signed true")
        if kind.startswith("Percentage") and signed:
            out.append(f"{where}.signed: kind {kind} requires signed false")
    bins = port.get("min_bins_that_pass")
    if bins is not None and (not _is_int(bins) or bins < 1):
        out.append(f"{where}.min_bins_that_pass: must be an integer >= 1 or null")
    if port.get("fits") is not None:
        for i, fit in enumerate(_check_list(port["fits"], f"{where}.fits", MAX_FITS, out)):
            _validate_fit(fit, f"{where}.fits[{i}]", out)


def _validate_fit(fit: Any, where: str, out: list[str]) -> None:
    _check_object(fit, _FITS_KEYS, where, ("io_kind", "note"), out)
    if not isinstance(fit, dict):
        return
    for key, allowed in (("frame", FRAME_ENUM), ("positioning", POSITIONING_ENUM)):
        if fit.get(key) is not None and fit[key] not in allowed:
            out.append(f"{where}.{key}: must be one of {list(allowed)} or null")
    mb = fit.get("min_bins")
    if mb is not None and (not _is_int(mb) or mb < 1):
        out.append(f"{where}.min_bins: must be an integer >= 1 or null")


def missing_mandatory_keys(doc: Any) -> list[str]:
    """One problem per port per absent mandatory key (``None`` is unknown, not absent).

    Composer reports and enforces this at save and publish; this is the same rule for an agent
    checking a draft before handing it over. ``validate_author_fields`` does not require keys.
    """
    out: list[str] = []
    ports = doc.get("ports") if isinstance(doc, dict) else None
    for i, port in enumerate(ports if isinstance(ports, list) else []):
        if not isinstance(port, dict):
            continue
        label = port.get("name") or f"ports[{i}]"
        out.extend(
            f"{label}: mandatory key {key!r} is absent (use null for unknown)"
            for key in MANDATORY_PORT_KEYS
            if key not in port
        )
    return out


# --------------------------------------------------------------------------------------
# Port contract check
# --------------------------------------------------------------------------------------

PASS = "pass"
FAIL = "fail"
SKIPPED = "skipped"

#: Datasheet drive scalars compared with the live area, mapped to live_area keys.
_DRIVE_KEYS: tuple[tuple[str, str], ...] = (
    ("threshold", "threshold"),
    ("psp", "psp"),
    ("leak", "leak"),
    ("refractory", "refractory"),
    ("accumulate", "accumulate"),
)


def _triplet(value: Any) -> list[int] | None:
    if isinstance(value, dict) and all(k in value for k in ("x", "y", "z")):
        return [value["x"], value["y"], value["z"]]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return list(value)
    return None


def live_area_from_properties(
    props: dict[str, Any], cortical_id: str | None = None
) -> dict[str, Any]:
    """Project ``get_area_parameters`` / ``inspect_cortical_area`` output to the live-area keys.

    Reads only what FEAGI reports. ``code`` and ``bins`` are not in the genome for custom
    areas; the caller supplies them (``live_area['code']`` / ``live_area['bins']``). For an
    IPU or OPU the kind, signed, and the flag's frame and positioning come from the decoded
    cortical id (``cortical_id``, else ``props['cortical_id']``); the live ``encoding_type``
    (frame) and ``encoding_format`` (positioning) from FEAGI confirm them. ``shape`` stays the
    total voxel size; ``per_device_shape`` is the per-device size (``dev_count`` multiplies X).
    """
    shape = _triplet(props.get("cortical_dimensions"))
    per_device = _triplet(props.get("cortical_dimensions_per_device"))
    dev_count = props.get("dev_count") if _is_int(props.get("dev_count")) else None
    if (
        per_device is None
        and shape is not None
        and dev_count
        and dev_count > 1
        and shape[0] % dev_count == 0
    ):
        per_device = [shape[0] // dev_count, shape[1], shape[2]]
    live: dict[str, Any] = {
        "shape": shape,
        "per_device_shape": per_device if per_device is not None else shape,
        "threshold": props.get("neuron_fire_threshold"),
        "psp": props.get("neuron_post_synaptic_potential"),
        "leak": props.get("neuron_leak_coefficient"),
        "refractory": props.get("neuron_refractory_period"),
        "accumulate": props.get("neuron_mp_charge_accumulation"),
        "encoding_type": props.get("encoding_type"),
        "encoding_format": props.get("encoding_format"),
    }
    cid = cortical_id or props.get("cortical_id")
    decoded = decode_cortical_id_interpretation(cid) if isinstance(cid, str) else {}
    if decoded.get("ok") and decoded.get("io_kind") in ("sensory", "motor_output"):
        live.update(
            io_kind=decoded["io_kind"],
            kind=decoded["kind"],
            signed=decoded["signed"],
            decoded_frame=decoded["frame_change_handling"],
            decoded_positioning=decoded["positioning"],
        )
    return live


def _row(
    check: str,
    status: str,
    expected: Any = None,
    observed: Any = None,
    tolerance: Any = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "check": check,
        "status": status,
        "expected": expected,
        "observed": observed,
        "tolerance": tolerance,
        "detail": detail,
    }


def _within(expected: Any, observed: Any, rel_tol: float) -> bool:
    if isinstance(expected, bool) or isinstance(observed, bool):
        return bool(expected == observed)
    if _is_num(expected) and _is_num(observed):
        return math.isclose(float(expected), float(observed), rel_tol=rel_tol, abs_tol=0.0)
    return bool(expected == observed)


def check_port_contract(
    port_row: dict[str, Any],
    live_area: dict[str, Any],
    *,
    drive_rel_tolerance: float | None = None,
    latency_tolerance_bursts: int | None = None,
) -> dict[str, Any]:
    """Compare one datasheet port row with a live area; per-check pass/fail with numbers.

    ``port_row`` is a datasheet port (``shape``, ``code``, ``dir``, ``drive``,
    ``latency_bursts``, ``min_bins_that_pass``, ...). ``live_area`` may hold ``shape``,
    ``bins`` (value bins the integrator drives or reads), ``code``, ``dir``, the drive scalars
    from :func:`live_area_from_properties`, ``observed_latency_bursts`` and ``responded``
    (probe outputs). A check whose datasheet value is null, or whose live value is missing,
    is ``skipped`` (never a silent pass). Nothing is changed or fixed.

    Tolerances: the contract has no tolerance field. A port's ``drive.tolerance_rel`` or
    ``latency_tolerance_bursts`` on the row is honoured if present, else the keyword argument,
    else exact (0). The tolerance used is reported with each check.

    Returns ``{"port", "passed", "checks": [...]}``; ``passed`` is True when no check failed
    and at least one passed, False when any failed, None when everything was skipped.
    """
    checks: list[dict[str, Any]] = []
    raw_drive = port_row.get("drive")
    drive: dict[str, Any] = raw_drive if isinstance(raw_drive, dict) else {}

    def compare(
        check: str, expected: Any, observed: Any, tol: Any = None, ok: bool | None = None
    ) -> None:
        if expected is None:
            checks.append(_row(check, SKIPPED, detail="datasheet states no value"))
        elif observed is None:
            checks.append(_row(check, SKIPPED, expected, detail="live value not available"))
        else:
            good = (expected == observed) if ok is None else ok
            checks.append(_row(check, PASS if good else FAIL, expected, observed, tol))

    is_io = live_area.get("io_kind") in ("sensory", "motor_output")
    compare("dir", port_row.get("dir"), live_area.get("dir"))
    if is_io:
        _io_checks(port_row, live_area, compare, checks)
    else:
        compare("shape", _as_list(port_row.get("shape")), _as_list(live_area.get("shape")))
    compare("code", port_row.get("code"), live_area.get("code"))

    min_bins = port_row.get("min_bins_that_pass")
    live_bins = live_area.get("bins")
    compare(
        "bins",
        min_bins,
        live_bins,
        ">= min_bins_that_pass",
        ok=(
            _is_num(min_bins) and _is_num(live_bins) and live_bins >= min_bins  # type: ignore[operator]
        ),
    )

    rel: Any = drive.get("tolerance_rel", drive_rel_tolerance)
    rel = float(rel) if _is_num(rel) else 0.0
    for sheet_key, live_key in _DRIVE_KEYS:
        expected = drive.get(sheet_key)
        observed = live_area.get(live_key)
        compare(
            f"drive.{sheet_key}",
            expected,
            observed,
            f"rel {rel}",
            ok=_within(expected, observed, rel) if expected is not None else None,
        )

    lat_tol: Any = port_row.get("latency_tolerance_bursts", latency_tolerance_bursts)
    lat_tol = int(lat_tol) if _is_int(lat_tol) else 0
    expected_lat = port_row.get("latency_bursts")
    observed_lat = live_area.get("observed_latency_bursts")
    compare(
        "latency_bursts",
        expected_lat,
        observed_lat,
        f"+/- {lat_tol} bursts",
        ok=(
            _is_num(expected_lat)
            and _is_num(observed_lat)
            and abs(observed_lat - expected_lat) <= lat_tol  # type: ignore[operator]
        ),
    )
    if live_area.get("responded") is not None:
        checks.append(
            _row(
                "path_responds",
                PASS if live_area["responded"] is True else FAIL,
                True,
                live_area["responded"],
                detail="stimulus probe: the port's path responded within the datasheet latency",
            )
        )

    failed = [c for c in checks if c["status"] == FAIL]
    passed_any = any(c["status"] == PASS for c in checks)
    result = {
        "port": port_row.get("name"),
        "passed": False if failed else (True if passed_any else None),
        "failed_checks": [c["check"] for c in failed],
        "checks": checks,
    }
    if is_io:
        result["advisory"] = _advisory(port_row, live_area)
    return result


def _as_list(value: Any) -> Any:
    return list(value) if isinstance(value, (list, tuple)) else value


def _xy(shape: Any) -> Any:
    return list(shape[:2]) if isinstance(shape, (list, tuple)) and len(shape) == 3 else None


def _live_flag(live_area: dict[str, Any], live_key: str, decoded_key: str) -> tuple[Any, str]:
    """Live frame or positioning: FEAGI's reported value, else the decoded id's."""
    live = live_area.get(live_key)
    if isinstance(live, str) and live.strip():
        return live.strip(), ""
    return live_area.get(decoded_key), "live encoding not reported; read from the cortical id"


def _io_checks(
    port_row: dict[str, Any],
    live_area: dict[str, Any],
    compare: Any,
    checks: list[dict[str, Any]],
) -> None:
    """Checks for a live IPU or OPU area playing a port: kind, signed, frame, positioning, Z.

    A device area is not the port itself: block bins and device bins differ and the adapter
    converts. So X and Y use the per-device size (``dev_count`` multiplies X) and Z depth is
    judged against the port's ``fits`` and ``min_bins_that_pass``, never as equal to the
    port's bins.
    """
    compare("kind", port_row.get("kind"), live_area.get("kind"))
    compare("signed", port_row.get("signed"), live_area.get("signed"))
    for check, port_key, live_key, decoded_key in (
        ("frame", "frame", "encoding_type", "decoded_frame"),
        ("positioning", "positioning", "encoding_format", "decoded_positioning"),
    ):
        observed, note = _live_flag(live_area, live_key, decoded_key)
        compare(check, port_row.get(port_key), observed)
        if note and checks[-1]["status"] != SKIPPED:
            checks[-1]["detail"] = note
    per_device = live_area.get("per_device_shape")
    compare("shape_xy", _xy(port_row.get("shape")), _xy(per_device))
    z = per_device[2] if isinstance(per_device, (list, tuple)) and len(per_device) == 3 else None
    fits = [f for f in (port_row.get("fits") or []) if isinstance(f, dict)]
    matching = [f for f in fits if _fit_matches(f, live_area)]
    if fits:
        compare(
            "fits",
            [f.get("note") or {k: f.get(k) for k in ("frame", "positioning")} for f in fits],
            [live_area.get("kind"), live_area.get("decoded_frame")],
            "any fits entry matches the live kind, frame and positioning",
            ok=bool(matching),
        )
    need = [f["min_bins"] for f in matching if _is_int(f.get("min_bins"))]
    if not need and _is_int(port_row.get("min_bins_that_pass")):
        need = [port_row["min_bins_that_pass"]]
    floor = min(need) if need else None
    compare(
        "z_depth",
        floor,
        z,
        ">= fits min_bins (else min_bins_that_pass)",
        ok=_is_num(floor) and _is_num(z) and z >= floor,  # type: ignore[operator]
    )


def _fit_matches(fit: dict[str, Any], live_area: dict[str, Any]) -> bool:
    """A ``fits`` entry matches when every state it makes agrees with the live area."""
    if fit.get("io_kind") is not None and fit["io_kind"] != live_area.get("kind"):
        return False
    for key, live_key, decoded_key in (
        ("frame", "encoding_type", "decoded_frame"),
        ("positioning", "encoding_format", "decoded_positioning"),
    ):
        if fit.get(key) is not None and fit[key] != _live_flag(live_area, live_key, decoded_key)[0]:
            return False
    return True


def _advisory(port_row: dict[str, Any], live_area: dict[str, Any]) -> list[str]:
    """Plain-text hints for the adapter. Advisory only: nothing is wired or changed."""
    notes = [
        "Block bins and device bins are different: the adapter converts between them "
        "(port Z is the block's bins, the device area has its own Z)."
    ]
    code = port_row.get("code")
    kind = live_area.get("kind")
    if isinstance(kind, str) and kind != port_row.get("kind") and port_row.get("kind"):
        notes.append(
            f"Device kind {kind} differs from port kind {port_row['kind']}: an adapter "
            "conversion is needed; none is applied here."
        )
    if code == "thermometer":
        notes.append(
            "A thermometer port can be fed by expanding a value into bins "
            "(expand_value_to_bins, thermometer only)."
        )
    elif code in ("binary", "one-hot", "value plane", "rate"):
        notes.append(
            f"No named conversion exists for a {code} port; measure the encoding the "
            "adapter must produce."
        )
    return notes
