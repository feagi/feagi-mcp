"""Decode canonical 8-byte FEAGI cortical IDs for MCP tooling (no live FEAGI call).

WIRE LAYOUT (IPU / OPU Cortical IDs, 8 bytes), matching Rust ``CorticalID``:

    byte 0 — ``b'i'`` (sensory) or ``b'o'`` (motor / output sensory path)
    bytes 1–3 — unit reference (ASCII, e.g. ``mot``); with byte 0 forms the 4-char subtype
        (e.g. ``omot``) used in API ``cortical_subtype``.
    bytes 4–5 — ``IOCorticalAreaConfigurationFlag`` bitmask, little-endian u16.
    bytes 6–7 — ``CorticalUnitIndex`` as little-endian u16 (device / group instance).

CONFIGURATION FLAG (u16) bit layout (Rust ``bit_indexes``):

    bits 0–3  — variant discriminant
    bits 4–7  — ``CorticalSubUnitIndex`` (0–15); this is BV / connectome ``subunit_id``
    bit  8    — frame-change handling: absolute = 0, incremental = 1
    bit  9    — percentage neuron positioning: linear = 0, fractional = 1
    bits 10–12 — pose schema (PoseEstimation only)

Brain Visualizer ``unit_id`` and the Python SDK motor decoder both use the u16 unit
index in bytes 6–7. ``subunit_id`` is **not** byte 6.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

_SUBUNIT_SHIFT = 4
_SUBUNIT_MASK = 0x0F
_FRAME_CHANGE_SHIFT = 8


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

    flags = int.from_bytes(raw[4:6], "little")
    subunit = (flags >> _SUBUNIT_SHIFT) & _SUBUNIT_MASK
    unit_index = int.from_bytes(raw[6:8], "little")
    frame_change = (
        "Incremental" if ((flags >> _FRAME_CHANGE_SHIFT) & 0x01) == 1 else "Absolute"
    )

    base.update(
        {
            "ok": True,
            "byte_length": 8,
            "bytes_hex": " ".join(f"{x:02x}" for x in raw),
            "io_kind": io_kind,
            "subtype_4char": subtype_4,
            "config_bytes_4_5": [int(raw[4]), int(raw[5])],
            "cortical_subunit_index": subunit,
            "cortical_unit_index": unit_index,
            "frame_change_handling": frame_change,
            "mapping_hints": {
                "bv_unit_id": unit_index,
                "bv_subunit_id": subunit,
                "ros_connector_device_group_id": unit_index,
                "python_motor_group_from_xyzp_key": unit_index,
            },
            "notes": (
                "cortical_subunit_index is flag bits 4-7 of bytes 4-5 (connectome "
                "subunit_id / title suffix). cortical_unit_index is little-endian u16 "
                "in bytes 6-7 (BV unit_id / device group). Bit 8 of the flag is "
                "Absolute vs Incremental frame handling."
            ),
        }
    )
    return base
