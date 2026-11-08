"""Percentage coding through ``feagi_rust_py_libs`` (the single source of the bin rule).

The z-bin <-> value rule lives in FEAGI's own coder (``feagi_sensorimotor``), exposed to Python
by ``feagi_rust_py_libs.connector_core``. This module only forwards to it: every function takes
the unit exactly as the agent registration JSON carries it, and every failure is the binding's
``ValueError``. Nothing here restates the coding arithmetic.

Two conventions are Python-side and documented as such:

* ``fraction`` is the decoded value normalized to 0..1. Unsigned variants decode to 0..1
  already; signed variants decode to -1..1 and are mapped by ``(v + 1) / 2`` (the convention of
  FEAGI's single-voxel decoder, ``value_0_1``).
* A ``physical_range`` of a registered channel ties the physical value at fraction 0 and 1
  (``value_at_0`` / ``value_at_1``); the value in between is linear in the fraction.

@cursor:ffi-safe - no dynamic behavior beyond the binding calls.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: Lowest ``feagi_rust_py_libs`` release that carries the percentage coding bindings.
MIN_BINDINGS_VERSION = "0.0.122"

#: ``connector_core`` functions this package forwards to.
REQUIRED_BINDINGS = (
    "decode_percentage_from_z_indexes",
    "encode_percentage_to_z_indexes",
    "target_to_z_bin",
    "percentage_coding_variant",
    "validate_physical_range",
)


def _load_connector_core() -> Any:
    """Import ``connector_core`` and check the percentage coding functions exist.

    Raises ``ImportError`` naming the needed release; there is no fallback implementation.
    """
    need = f"feagi_rust_py_libs >= {MIN_BINDINGS_VERSION} is required for percentage coding"
    try:
        from feagi_rust_py_libs import connector_core  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError(f"{need}: the package could not be imported ({e})") from e
    missing = [name for name in REQUIRED_BINDINGS if not hasattr(connector_core, name)]
    if missing:
        raise ImportError(f"{need}: the installed build lacks {missing}")
    return connector_core


_core = _load_connector_core()

#: Registration section that lists motor units (decoder side).
OUTPUT_SECTION = "output_units_and_decoder_properties"
#: Registration section that lists sensory units (encoder side).
INPUT_SECTION = "input_units_and_encoder_properties"

#: Variants that carry a positive and a negative lobe in two x columns of a channel.
TWO_LOBE_VARIANTS = frozenset({"SignedLinearTwoLobe", "SignedFractional"})

#: Keys of a registration unit definition the binding reads.
_UNIT_KEYS = ("cortical_unit_index", "io_configuration_flags")


def is_signed(variant: str) -> bool:
    """Whether a coding variant decodes to -1..1 (its name starts with ``Signed``)."""
    return variant.startswith("Signed")


def native_to_fraction(variant: str, native: float) -> float:
    """Decoded value in the variant's native range as a 0..1 fraction."""
    return (native + 1.0) / 2.0 if is_signed(variant) else native


def fraction_to_native(variant: str, fraction: float) -> float:
    """A 0..1 fraction as a value in the variant's native range."""
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        raise ValueError("fraction must be a number")
    if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be within 0..1, got {fraction}")
    return fraction * 2.0 - 1.0 if is_signed(variant) else float(fraction)


@dataclass(frozen=True)
class PhysicalRange:
    """Physical value at decoded fraction 0 and 1, as one registered channel states it."""

    value_at_0: float
    value_at_1: float
    unit: str

    def to_value(self, fraction: float) -> float:
        """Physical value at ``fraction`` (linear between the two end values)."""
        return self.value_at_0 + (self.value_at_1 - self.value_at_0) * fraction

    def to_fraction(self, value: float) -> float:
        """Fraction at which the channel decodes to ``value`` (not clamped)."""
        return (value - self.value_at_0) / (self.value_at_1 - self.value_at_0)


def parse_physical_range(raw: Any) -> PhysicalRange | None:
    """The channel's ``physical_range`` validated by FEAGI's rules; ``None`` when absent.

    Raises ``ValueError`` for a range the binding rejects (non-finite, equal ends, no unit).
    """
    if raw is None:
        return None
    value_at_0, value_at_1, unit = _core.validate_physical_range(json.dumps(raw))
    return PhysicalRange(value_at_0, value_at_1, unit)


@dataclass(frozen=True)
class UnitCoding:
    """The coding of one cortical area of a registered unit at a given z depth."""

    section: str
    unit_key: str
    unit_json: str
    area_index: int
    depth: int
    variant: str

    @classmethod
    def build(
        cls,
        section: str,
        unit_key: str,
        unit_definition: dict[str, Any],
        area_index: int,
        depth: int,
    ) -> UnitCoding:
        """Bind a registration unit definition; raises ``ValueError`` from the binding."""
        unit_json = json.dumps({k: unit_definition[k] for k in _UNIT_KEYS if k in unit_definition})
        variant = _core.percentage_coding_variant(section, unit_key, unit_json, area_index)
        return cls(section, unit_key, unit_json, area_index, depth, variant)

    @property
    def two_lobe(self) -> bool:
        """Whether a value needs a positive and a negative x column."""
        return self.variant in TWO_LOBE_VARIANTS

    def same_coding(self, other: UnitCoding) -> bool:
        """Whether two bindings decode identically (same section, area index and variant)."""
        return (self.section, self.area_index, self.variant) == (
            other.section,
            other.area_index,
            other.variant,
        )

    def decode_native(
        self, z_positive: Sequence[int], z_negative: Sequence[int] | None = None
    ) -> float:
        """Decoded value in the variant's native range from the active z indexes."""
        return float(
            _core.decode_percentage_from_z_indexes(
                self.section,
                self.unit_key,
                self.unit_json,
                self.depth,
                list(z_positive),
                list(z_negative) if z_negative else None,
                self.area_index,
            )
        )

    def decode_fraction(
        self, z_positive: Sequence[int], z_negative: Sequence[int] | None = None
    ) -> float:
        """Decoded value as a 0..1 fraction from the active z indexes."""
        return native_to_fraction(self.variant, self.decode_native(z_positive, z_negative))

    def bin_for_fraction(self, fraction: float) -> int:
        """The z bin whose decode is nearest to ``fraction`` (the decoder's inverse)."""
        target = fraction_to_native(self.variant, fraction)
        return int(
            _core.target_to_z_bin(
                self.section, self.unit_key, self.unit_json, self.depth, target, self.area_index
            )
        )

    def encode_fraction(self, fraction: float) -> tuple[list[int], list[int]]:
        """Active z indexes ``(positive, negative)`` the encoder places for ``fraction``."""
        value = fraction_to_native(self.variant, fraction)
        positive, negative = _core.encode_percentage_to_z_indexes(
            self.section, self.unit_key, self.unit_json, self.depth, value, self.area_index
        )
        return list(positive), list(negative)
