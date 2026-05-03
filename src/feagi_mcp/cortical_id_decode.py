"""Decode canonical 8-byte FEAGI cortical IDs for MCP tooling (no live FEAGI call).

WIRE LAYOUT (IPU / OPU Cortical IDs, 8 bytes):
    byte 0 — ``b'i'`` (sensory) or ``b'o'`` (motor / output sensory path)
    bytes 1–3 — unit reference (ASCII, e.g. ``mot``); with byte 0 forms the 4-char subtype
        (e.g. ``omot``) used in API ``cortical_subtype``.
    bytes 4–5 — configuration / encoding payload (see Rust ``IOCorticalAreaConfigurationFlag``).
    byte 6 — ``CorticalSubUnitIndex`` (which area within a multi-area unit).
    byte 7 — ``CorticalUnitIndex`` (which instance of that unit type: device / group index).

Brain Visualizer ``unit_id`` and the Python SDK motor decoder both use byte 7 for grouping
(deviceGroupId alignment). Byte 6 is ``subunit_id``.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any


def _raw_from_cortical_id_string(cortical_id: str) -> tuple[bytes | None, str | None]:
    """Resolve wire bytes from base64 (preferred) or legacy 8-byte latin-1 key."""
    cid = cortical_id.strip()
    if not cid:
        return None, "empty cortical_id"

    try:
        raw = base64.b64decode(cid, validate=True)
    except (binascii.Error, ValueError):
        raw = None
    if raw is not None and len(raw) == 8:
        return raw, None

    if len(cid) == 8:
        try:
            latin = cid.encode("latin-1")
        except UnicodeEncodeError:
            latin = b""
        if len(latin) == 8:
            return latin, None

    return (
        None,
        "could not decode 8-byte cortical id (expect base64 of 8 bytes or 8 latin-1 chars)",
    )


def decode_cortical_id_interpretation(cortical_id: str) -> dict[str, Any]:
    """Structured interpretation of a cortical ID string.

    Returns a JSON-serializable dict suitable for MCP tool output.
    Always includes ``cortical_id_input``. On failure, ``ok`` is False and ``error`` is set.
    """
    raw, err = _raw_from_cortical_id_string(cortical_id)
    base: dict[str, Any] = {
        "cortical_id_input": cortical_id.strip(),
        "ok": False,
        "error": None,
    }
    if err is not None or raw is None:
        base["error"] = err or "decode failed"
        return base

    b0 = raw[0]
    if b0 == ord(b"i"):
        io_kind = "sensory"
    elif b0 == ord(b"o"):
        io_kind = "motor_output"
    else:
        io_kind = "non_io"

    try:
        subtype_4 = raw[0:4].decode("ascii")
    except UnicodeDecodeError:
        subtype_4 = raw[0:4].hex()

    base.update(
        {
            "ok": True,
            "byte_length": 8,
            "bytes_hex": " ".join(f"{x:02x}" for x in raw),
            "io_kind": io_kind,
            "subtype_4char": subtype_4,
            "config_bytes_4_5": [int(raw[4]), int(raw[5])],
            "cortical_subunit_index": int(raw[6]),
            "cortical_unit_index": int(raw[7]),
            "mapping_hints": {
                "bv_unit_id": int(raw[7]),
                "bv_subunit_id": int(raw[6]),
                "ros_connector_device_group_id": int(raw[7]),
                "python_motor_group_from_xyzp_key": int(raw[7]),
            },
            "notes": (
                "cortical_unit_index (byte 7) is the instance / device group used by BV unit_id, "
                "ROS connector deviceGroupId, and feagi-python-sdk motor decode keys. "
                "cortical_subunit_index (byte 6) is the sub-area within a unit (BV subunit_id)."
            ),
        }
    )
    return base
