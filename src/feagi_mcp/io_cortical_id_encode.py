"""Encode canonical 8-byte FEAGI IPU/OPU cortical IDs for MCP tooling (no live FEAGI call).

This is the inverse of :mod:`feagi_mcp.cortical_id_decode`. It mirrors the Rust source of
truth (``feagi-structures`` ``IOCorticalAreaConfigurationFlag::to_data_type_configuration_flag``
and ``CorticalID::as_io_cortical_id``) so MCP callers can derive the exact wire id a
sensorimotor IO unit resolves to *without* probing a live brain or reverse-engineering bytes.

WIRE LAYOUT (8 bytes), identical to the decoder:
    byte 0     — ``b'i'`` (sensory / input) or ``b'o'`` (motor / output)
    bytes 1-3  — 3-char ASCII unit identifier (e.g. ``cnt``); with byte 0 forms the 4-char
                 ``cortical_subtype`` (e.g. ``icnt``).
    bytes 4-5  — ``IOCorticalAreaConfigurationFlag`` bitmask, little-endian.
    bytes 6-7  — ``CorticalUnitIndex`` as little-endian u16 (device / group instance).

CONFIGURATION FLAG (u16) bit layout (Rust ``bit_indexes``):
    bits 0-3   — variant discriminant (see ``_VARIANT_CODES``).
    bits 4-7   — ``CorticalSubUnitIndex`` (0-15).
    bit  8     — frame-change handling: ``absolute`` = 0, ``incremental`` = 1.
    bit  9     — percentage neuron positioning: ``linear`` = 0, ``fractional`` = 1.
    bits 10-12 — pose schema (only used by the ``pose_estimation`` variant; unsupported here).
"""

from __future__ import annotations

import base64
from typing import Any

# Variant discriminants (bits 0-7), mirroring the Rust enum ordering.
_VARIANT_CODES: dict[str, int] = {
    "boolean": 0,
    "percentage": 1,
    "percentage_2d": 2,
    "percentage_3d": 3,
    "percentage_4d": 4,
    "signed_percentage": 5,
    "signed_percentage_2d": 6,
    "signed_percentage_3d": 7,
    "signed_percentage_4d": 8,
    "cartesian_plane": 9,
    "misc": 10,
}

# Variants whose flag carries a frame-change-handling bit.
_FRAMING_VARIANTS = set(_VARIANT_CODES) - {"boolean"}
# Variants whose flag carries a percentage-positioning bit.
_POSITIONING_VARIANTS = {
    "percentage",
    "percentage_2d",
    "percentage_3d",
    "percentage_4d",
    "signed_percentage",
    "signed_percentage_2d",
    "signed_percentage_3d",
    "signed_percentage_4d",
}

_FRAMING_BITS: dict[str, int] = {"absolute": 0, "incremental": 1}
_POSITIONING_BITS: dict[str, int] = {"linear": 0, "fractional": 1}

_FRAME_CHANGE_HANDLING_SHIFT = 8
_PERCENTAGE_NEURON_POSITIONING_SHIFT = 9
_SUBUNIT_SHIFT = 4
_SUBUNIT_MASK = 0x0F

_BYTE_MAX = 0xFF
_UNIT_INDEX_MAX = 0xFFFF
_SUBUNIT_INDEX_MAX = _SUBUNIT_MASK


def configuration_flag(
    variant: str,
    framing: str,
    positioning: str,
) -> tuple[int | None, str | None]:
    """Compute the ``IOCorticalAreaConfigurationFlag`` u16 bitmask for an IO variant.

    Returns ``(flag, None)`` on success or ``(None, error_message)`` on an unsupported
    combination. Framing/positioning that a variant does not carry must be left at their
    neutral values (``absolute`` / ``linear``); passing a non-neutral value for an axis the
    variant ignores is an explicit error rather than a silent coercion.
    """
    variant_key = variant.strip().lower()
    if variant_key not in _VARIANT_CODES:
        return None, (f"unsupported variant '{variant}'; supported: {sorted(_VARIANT_CODES)}")

    framing_key = framing.strip().lower()
    if framing_key not in _FRAMING_BITS:
        return None, f"framing must be one of {sorted(_FRAMING_BITS)}; got '{framing}'"

    positioning_key = positioning.strip().lower()
    if positioning_key not in _POSITIONING_BITS:
        return None, (
            f"positioning must be one of {sorted(_POSITIONING_BITS)}; got '{positioning}'"
        )

    if variant_key not in _FRAMING_VARIANTS and framing_key != "absolute":
        return None, (
            f"variant '{variant_key}' has no frame-change axis; framing must be 'absolute'"
        )
    if variant_key not in _POSITIONING_VARIANTS and positioning_key != "linear":
        return None, (
            f"variant '{variant_key}' has no positioning axis; positioning must be 'linear'"
        )

    variant_code = _VARIANT_CODES[variant_key]
    frame_bits = _FRAMING_BITS[framing_key] if variant_key in _FRAMING_VARIANTS else 0
    pos_bits = _POSITIONING_BITS[positioning_key] if variant_key in _POSITIONING_VARIANTS else 0

    flag = (
        variant_code
        | (frame_bits << _FRAME_CHANGE_HANDLING_SHIFT)
        | (pos_bits << _PERCENTAGE_NEURON_POSITIONING_SHIFT)
    )
    return flag, None


def encode_io_cortical_id(
    subtype: str,
    variant: str = "percentage",
    framing: str = "absolute",
    positioning: str = "linear",
    unit_index: int = 0,
    subunit_index: int = 0,
) -> dict[str, Any]:
    """Encode the canonical wire id for an IPU/OPU sensorimotor area.

    Args:
        subtype: 4-char ``cortical_subtype`` whose first char selects the IO direction
            (``i`` input / ``o`` output), e.g. ``icnt`` (count input), ``ocnt`` (count output).
        variant: ``IOCorticalAreaConfigurationFlag`` variant (default ``percentage`` — the
            count IO family the trainer's population encoder / class decoder bind to).
        framing: ``absolute`` or ``incremental``.
        positioning: ``linear`` or ``fractional``.
        unit_index: Device / group instance index (bytes 6-7 little-endian u16), 0-65535.
        subunit_index: Sub-area index within the unit (flag bits 4-7), 0-15.

    Returns:
        ``{"ok": True, "cortical_id": <base64>, "config_flag": <int>, ...}`` on success, or
        ``{"ok": False, "error": <message>}`` on invalid input. Never raises.
    """
    result: dict[str, Any] = {"ok": False, "error": None}

    sub = subtype.strip()
    if len(sub) != 4:
        result["error"] = f"subtype must be exactly 4 chars (e.g. 'icnt'); got '{subtype}'"
        return result
    if not sub.isascii():
        result["error"] = f"subtype must be ASCII; got '{subtype}'"
        return result
    direction = sub[0].lower()
    if direction not in ("i", "o"):
        result["error"] = f"subtype must start with 'i' (input) or 'o' (output); got '{sub}'"
        return result

    if not (0 <= int(unit_index) <= _UNIT_INDEX_MAX):
        result["error"] = f"unit_index must be in 0..{_UNIT_INDEX_MAX}; got {unit_index}"
        return result
    if not (0 <= int(subunit_index) <= _SUBUNIT_INDEX_MAX):
        result["error"] = (
            f"subunit_index must be in 0..{_SUBUNIT_INDEX_MAX}; got {subunit_index}"
        )
        return result

    flag, flag_err = configuration_flag(variant, framing, positioning)
    if flag_err is not None or flag is None:
        result["error"] = flag_err
        return result

    packed_flag = flag | ((int(subunit_index) & _SUBUNIT_MASK) << _SUBUNIT_SHIFT)
    unit_bytes = int(unit_index).to_bytes(2, "little")
    raw = bytes(
        [
            ord(direction),
            ord(sub[1]),
            ord(sub[2]),
            ord(sub[3]),
            packed_flag & _BYTE_MAX,
            (packed_flag >> 8) & _BYTE_MAX,
            unit_bytes[0],
            unit_bytes[1],
        ]
    )

    result.update(
        {
            "ok": True,
            "error": None,
            "cortical_id": base64.b64encode(raw).decode("ascii"),
            "cortical_subtype": sub,
            "io_kind": "sensory" if direction == "i" else "motor_output",
            "config_flag": packed_flag,
            "config_bytes_4_5": [packed_flag & _BYTE_MAX, (packed_flag >> 8) & _BYTE_MAX],
            "bytes_hex": " ".join(f"{x:02x}" for x in raw),
            "cortical_unit_index": int(unit_index),
            "cortical_subunit_index": int(subunit_index),
        }
    )
    return result
