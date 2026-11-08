"""Convert between an I/O channel's z bin, fraction and physical value (local, no HTTP).

The bin <-> fraction rule is FEAGI's own coder, reached through the registered unit's
:class:`~feagi_mcp.percentage_coding.UnitCoding` (``feagi_rust_py_libs`` bindings); this module
never restates the arithmetic. The physical value comes only from the channel's registered
``physical_range``; a channel that states none reports unit ``unknown`` and value ``null``.
"""

from __future__ import annotations

from typing import Any

from feagi_mcp.registration_units import ChannelRegistration, channel_count

UNKNOWN_UNIT = "unknown"


def validate_conversion_input(bin_value: Any, fraction: Any, value: Any) -> str | None:
    """An error message unless exactly one of ``bin`` / ``fraction`` / ``value`` is valid."""
    given = [v for v in (bin_value, fraction, value) if v is not None]
    if len(given) != 1:
        return "pass exactly one of bin, fraction or value"
    if bin_value is not None and (
        isinstance(bin_value, bool) or not isinstance(bin_value, int) or bin_value < 0
    ):
        return "bin must be an integer >= 0"
    for name, v in (("fraction", fraction), ("value", value)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return f"{name} must be a number"
    return None


def physical_fields(reg: ChannelRegistration, fraction: float) -> dict[str, Any]:
    """``value`` and ``unit`` at ``fraction``: physical when the channel states a range."""
    rng = reg.physical_range
    if rng is None:
        return {"value": None, "unit": UNKNOWN_UNIT}
    return {"value": rng.to_value(fraction), "unit": rng.unit}


def range_dict(reg: ChannelRegistration) -> dict[str, Any] | None:
    """The channel's ``physical_range`` as stated, or ``None``."""
    rng = reg.physical_range
    if rng is None:
        return None
    return {"value_at_0": rng.value_at_0, "value_at_1": rng.value_at_1, "unit": rng.unit}


def convert_channel_value(
    area: dict[str, Any],
    channel: int,
    reg: ChannelRegistration,
    *,
    bin_value: int | None = None,
    fraction: float | None = None,
    value: float | None = None,
) -> dict[str, Any]:
    """Convert one channel's bin, fraction or physical value with the registered unit coding.

    ``area`` is the cortical-area record; ``reg`` the channel's registration (coding and
    optional ``physical_range``). A bin gives the fraction it decodes to; a fraction (or a
    physical value, through the range) gives the bin that decodes nearest to it, with the
    fraction and value that bin decodes to (``requested_*`` keeps what was asked). Two-lobe
    variants have no single bin: a fraction gives the encoder's ``z_positive`` / ``z_negative``
    and a bare bin is an error.
    """
    coding = reg.coding
    count = channel_count(area)
    base: dict[str, Any] = {
        "area_id": area.get("cortical_id"),
        "area_name": area.get("cortical_name"),
        "kind": str(area.get("cortical_group", "")).upper(),
        "channel": channel,
        "channel_count": count,
        "depth": coding.depth,
        "variant": coding.variant,
        "physical_range": range_dict(reg),
    }
    if count is not None and channel >= count:
        return {**base, "error": f"channel {channel} out of range (area has {count} channels)"}
    if bin_value is not None:
        if bin_value >= coding.depth:
            return {**base, "error": f"bin {bin_value} out of range (depth {coding.depth})"}
        if coding.two_lobe:
            return {
                **base,
                "error": f"variant {coding.variant} needs a lobe; a bare bin has no single value",
            }
        decoded = coding.decode_fraction([bin_value])
        return {**base, "bin": bin_value, "fraction": decoded, **physical_fields(reg, decoded)}
    clamped = False
    if value is not None:
        if reg.physical_range is None:
            return {
                **base,
                "error": "value needs the channel's physical_range, which the registration does "
                "not state; pass bin or fraction",
            }
        fraction = reg.physical_range.to_fraction(float(value))
        clamped = not 0.0 <= fraction <= 1.0
        fraction = min(max(fraction, 0.0), 1.0)
    if fraction is None:
        return {**base, "error": "pass exactly one of bin, fraction or value"}
    out: dict[str, Any] = {**base, "requested_fraction": fraction}
    if value is not None:
        out["requested_value"] = value
    if clamped:
        out["clamped"] = True
    if coding.two_lobe:
        positive, negative = coding.encode_fraction(fraction)
        return {**out, "z_positive": positive, "z_negative": negative}
    z = coding.bin_for_fraction(fraction)
    decoded = coding.decode_fraction([z])
    return {**out, "bin": z, "fraction": decoded, **physical_fields(reg, decoded)}


def validate_command_input(fraction: Any, value: Any) -> str | None:
    """An error message unless exactly one of ``fraction`` / ``value`` is a valid number."""
    if (fraction is None) == (value is None):
        return "pass exactly one of fraction (0..1) or value (physical units)"
    for name, v in (("fraction", fraction), ("value", value)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return f"{name} must be a number"
    return None


def plan_channel_command(
    area: dict[str, Any],
    reg: ChannelRegistration,
    *,
    fraction: float | None = None,
    value: float | None = None,
) -> dict[str, Any]:
    """The OPU voxels that command one channel to ``fraction`` or a physical ``value``.

    A ``fraction`` is always accepted (0..1); a ``value`` needs the channel's registered
    ``physical_range`` and is clamped to it (``clamped`` is then true). Voxels are
    ``[channel * x_per_channel (+ 1 on the negative lobe), 0, z]``. Raises ``ValueError`` with
    the reason (missing range, out-of-range fraction or channel, binding error).
    """
    coding = reg.coding
    count = channel_count(area)
    per_device = area.get("cortical_dimensions_per_device")
    if count is None or not (isinstance(per_device, list) and isinstance(per_device[0], int)):
        raise ValueError("area dimensions do not state the channel count and x per channel")
    if reg.channel >= count:
        raise ValueError(f"channel {reg.channel} out of range (area has {count} channels)")
    out: dict[str, Any] = {"variant": coding.variant, "depth": coding.depth}
    if value is not None:
        if reg.physical_range is None:
            raise ValueError(
                f"channel {reg.channel} states no physical_range in its device registration, so "
                "a physical value cannot be commanded; pass fraction (0..1)"
            )
        fraction = reg.physical_range.to_fraction(float(value))
        out["requested_value"] = value
        if not 0.0 <= fraction <= 1.0:
            out["clamped"] = True
            fraction = min(max(fraction, 0.0), 1.0)
    if fraction is None:
        raise ValueError("pass exactly one of fraction (0..1) or value (physical units)")
    out["requested_fraction"] = fraction
    x0 = reg.channel * per_device[0]
    if coding.two_lobe:
        positive, negative = coding.encode_fraction(fraction)
        out["z_positive"], out["z_negative"] = positive, negative
        out["voxels"] = [[x0, 0, z] for z in positive] + [[x0 + 1, 0, z] for z in negative]
        decoded = coding.decode_fraction(positive, negative)
    else:
        z = coding.bin_for_fraction(fraction)
        out["bin"] = z
        out["voxels"] = [[x0, 0, z]]
        decoded = coding.decode_fraction([z])
    out["fraction"] = decoded
    out.update(physical_fields(reg, decoded))
    return out
