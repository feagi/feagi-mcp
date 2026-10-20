"""Value-coded single-layer areas: class maps and depth planes.

Object segmentation input/output, scanner classifier outputs, and the Depth Map
are ``W x H x 1``. The payload is each firing voxel's membrane potential.
A kernel classifier output is ``1 x 1 x n`` and fires depth ``z`` for class ``z``.

* class map: ``(class_id + 1) / class_count`` (0 = unlabeled / silent)
* depth plane: ``level / depth_levels`` with ``level`` in ``1..=depth_levels``

These helpers are pure (no I/O). The client fetches FEAGI payloads and calls
them, so encode/decode, passthrough settings, bin geometry, and classifier
checks cost no extra round-trips. Values mirror
``feagi_structures::neuron_voxels::class_potential`` in feagi-core.
"""

from __future__ import annotations

from typing import Any

#: Largest class count FEAGI accepts (``class_potential::MAX_CLASS_COUNT``).
MAX_CLASS_COUNT = 9999
#: Value-coded areas are one layer deep.
VALUE_PLANE_DEPTH = 1
#: Morphology that maps equal shapes 1:1 and broadcasts a 1-deep source across a deeper column.
PROJECTOR_MORPHOLOGY = "projector"
#: Destination thresholds sit half a level below the smallest value so f32 rounding never gates it.
THRESHOLD_LEVEL_FRACTION = 0.5

CODE_CLASS_COUNT_MISSING = "class_count_missing"
CODE_CLASS_COUNT_INVALID = "class_count_invalid"
CODE_MASK_NOT_SINGLE_LAYER = "mask_not_single_layer"
CODE_TWIN_NOT_SINGLE_LAYER = "twin_not_single_layer"
CODE_TWIN_NOT_FORWARDING = "twin_not_forwarding_value"
CODE_KERNEL_OUTPUT_SHAPE = "kernel_output_shape"
CODE_KERNEL_OUTPUT_FORWARDS = "kernel_output_forwards_value"
CODE_THRESHOLD_ABOVE_SMALLEST_CLASS = "threshold_above_smallest_class"

#: Passthrough warnings that are fatal once the value is a class id: any drift is another class.
EXACT_VALUE_CODES = frozenset(
    {
        "magnitude_scaled",
        "fan_out_divides_magnitude",
        "destination_accumulates_across_bursts",
        "runtime_threshold_drift",
    }
)


def class_count_error(class_count: Any) -> str | None:
    """Return why ``class_count`` is unusable, or None when it is valid."""
    if isinstance(class_count, bool) or not isinstance(class_count, int):
        return "class_count must be an integer"
    if class_count < 1 or class_count > MAX_CLASS_COUNT:
        return f"class_count must be in 1..={MAX_CLASS_COUNT}, got {class_count}"
    return None


def encode_class_potential(class_id: int, class_count: int) -> float:
    """Potential for ``class_id``: ``(class_id + 1) / class_count``."""
    error = class_count_error(class_count)
    if error:
        raise ValueError(error)
    if class_id < 0 or class_id >= class_count:
        raise ValueError(f"class id {class_id} is outside class count {class_count}")
    return (class_id + 1) / class_count


def decode_class_potential(potential: Any, class_count: int) -> int | None:
    """Class id carried by ``potential``, or None when it names no class."""
    if class_count_error(class_count) or isinstance(potential, bool):
        return None
    if not isinstance(potential, (int, float)):
        return None
    level = round(float(potential) * class_count)
    if level < 1 or level > class_count:
        return None
    return level - 1


def smallest_value(class_count: int | None, value_levels: int | None) -> float:
    """Smallest non-zero potential the plane carries (``1 / count``)."""
    count = class_count if class_count is not None else value_levels
    if count is None:
        raise ValueError("class_count/value_levels must be an integer")
    error = class_count_error(count)
    if error:
        raise ValueError(error.replace("class_count", "class_count/value_levels"))
    return 1.0 / float(count)


def passthrough_threshold(class_count: int | None, value_levels: int | None) -> float:
    """Destination fire threshold that lets the smallest value through with f32 margin."""
    return smallest_value(class_count, value_levels) * THRESHOLD_LEVEL_FRACTION


def identity_projector_rule() -> dict[str, Any]:
    """Mapping rule that copies each voxel unchanged (weight/PSC 1, not plastic)."""
    return {
        "morphology_id": PROJECTOR_MORPHOLOGY,
        "morphology_scalar": [1, 1, 1],
        "postSynapticCurrent_multiplier": 1.0,
        "plasticity_flag": False,
    }


def value_source_updates() -> dict[str, Any]:
    """Source settings: forward the firing-time potential, never divide it across fan-out."""
    return {"neuron_mp_driven_psp": True, "neuron_psp_uniform_distribution": True}


def value_destination_updates(threshold: float) -> dict[str, Any]:
    """Destination settings: fire on every value, keep it exact, one frame per burst."""
    return {
        "neuron_fire_threshold": threshold,
        "neuron_leak_coefficient": 0.0,
        "neuron_mp_charge_accumulation": False,
        "neuron_refractory_period": 0,
        "neuron_snooze_period": 0,
        "neuron_excitability": 1.0,
    }


def bins_geometry(levels: int, value_max: float) -> dict[str, float]:
    """Threshold ramp for a ``W x H x levels`` bin area fed from a value plane.

    Bin ``z`` fires when the value is at least ``(z + 0.5) * value_max / levels``,
    so a value in level ``k`` (1-based) fires bins ``0..k-1``: a cumulative
    (thermometer) code. Class value ``(c + 1) / N`` with ``levels == N`` fires
    bins ``0..=c``.
    """
    error = class_count_error(levels)
    if error:
        raise ValueError(error.replace("class_count", "levels"))
    if not isinstance(value_max, (int, float)) or value_max <= 0:
        raise ValueError("value_max must be > 0")
    step = float(value_max) / float(levels)
    return {"base_threshold": step * THRESHOLD_LEVEL_FRACTION, "threshold_increment_z": step}


def escalate_for_exact_values(report: dict[str, Any], class_count: int) -> dict[str, Any]:
    """Tighten a magnitude-passthrough report for class ids.

    Depth tolerates small drift; a class id does not (``round(p * N) - 1`` lands on a
    different class). Warnings that alter the value become errors, and the destination
    threshold must admit the smallest class ``1 / class_count``.
    """
    findings = list(report.get("findings", []))
    for finding in findings:
        if finding.get("code") in EXACT_VALUE_CODES and finding.get("severity") == "warning":
            finding["severity"] = "error"
            finding["message"] = (
                f"{finding.get('message', '')} Class ids must arrive exact, so this is fatal."
            ).strip()
    report["findings"] = findings
    report["class_count"] = class_count
    report["error_count"] = sum(1 for f in findings if f.get("severity") == "error")
    report["warning_count"] = sum(1 for f in findings if f.get("severity") == "warning")
    report["passes"] = report["error_count"] == 0
    return report


def destination_threshold_finding(
    dst_record: dict[str, Any], dst_id: str, class_count: int
) -> dict[str, Any] | None:
    """Error when the destination threshold would silence the lowest class."""
    threshold = float(dst_record.get("neuron_fire_threshold", 0.0))
    smallest = 1.0 / class_count
    if threshold < smallest:
        return None
    return {
        "severity": "error",
        "code": CODE_THRESHOLD_ABOVE_SMALLEST_CLASS,
        "message": (
            f"Destination fire threshold {threshold} is not below the smallest class value "
            f"{smallest} (class 0 of {class_count}); low classes never fire."
        ),
        "fix": {
            "cortical_id": dst_id,
            "updates": {"neuron_fire_threshold": passthrough_threshold(class_count, None)},
        },
    }


def decode_fire_queue_classes(
    fire_queue: dict[str, Any],
    area_id: str,
    class_count: int,
    max_pixels: int,
) -> dict[str, Any]:
    """Decode one area's last-burst fire queue into class ids.

    Returns a histogram plus at most ``max_pixels`` pixel rows so a 512x256 map does not
    flood the caller. ``undecodable`` counts voxels whose potential names no class
    (drift, or a non-value-coded area).
    """
    areas = fire_queue.get("cortical_areas")
    entry = areas.get(area_id) if isinstance(areas, dict) else None
    if not isinstance(entry, dict):
        return {
            "area_id": area_id,
            "class_count": class_count,
            "fired": 0,
            "timestep": fire_queue.get("timestep"),
            "class_histogram": {},
            "undecodable": 0,
            "pixels": [],
            "truncated": False,
        }
    xs = entry.get("coordinates_x") or []
    ys = entry.get("coordinates_y") or []
    potentials = entry.get("membrane_potentials") or []
    histogram: dict[int, int] = {}
    pixels: list[dict[str, Any]] = []
    undecodable = 0
    for x, y, potential in zip(xs, ys, potentials, strict=False):
        class_id = decode_class_potential(potential, class_count)
        if class_id is None:
            undecodable += 1
            continue
        histogram[class_id] = histogram.get(class_id, 0) + 1
        if len(pixels) < max_pixels:
            pixels.append({"x": x, "y": y, "class_id": class_id})
    decoded = sum(histogram.values())
    return {
        "area_id": area_id,
        "class_count": class_count,
        "fired": len(potentials),
        "timestep": fire_queue.get("timestep"),
        "class_histogram": {str(k): histogram[k] for k in sorted(histogram)},
        "undecodable": undecodable,
        "pixels": pixels,
        "truncated": decoded > len(pixels),
    }


def _dimensions(area: dict[str, Any] | None) -> list[int] | None:
    if not isinstance(area, dict):
        return None
    dims = area.get("cortical_dimensions") or area.get("dimensions")
    if isinstance(dims, (list, tuple)) and len(dims) == 3:
        try:
            return [int(dims[0]), int(dims[1]), int(dims[2])]
        except (TypeError, ValueError):
            return None
    return None


def _depth_of(area: dict[str, Any] | None) -> int | None:
    dims = _dimensions(area)
    if dims is None:
        return None
    return dims[2]


def _forwards_value(area: dict[str, Any]) -> bool | None:
    for key in ("neuron_mp_driven_psp", "mp_driven_psp"):
        value = area.get(key)
        if isinstance(value, bool):
            return value
    props = area.get("properties")
    if isinstance(props, dict):
        flag = props.get("mp_driven_psp")
        if isinstance(flag, bool):
            return flag
    return None


CODE_CLASS_OUTPUT_SHAPE = "class_output_shape"
CODE_CLASS_OUTPUT_FORWARDS = "class_output_forwards_value"


def classifier_value_findings(
    classifier: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Class output must match its class input and must not forward potential."""
    findings: list[dict[str, Any]] = []
    bindings = classifier.get("class_bindings")
    if not isinstance(bindings, list):
        return findings
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        class_id = str(binding.get("class_area_id") or "").strip()
        output_id = str(binding.get("class_output_area_id") or "").strip()
        class_dims = _dimensions(catalog.get(class_id)) if class_id else None
        output_dims = _dimensions(catalog.get(output_id)) if output_id else None
        if class_dims is not None and output_dims is not None and class_dims != output_dims:
            findings.append(
                {
                    "severity": "error",
                    "code": CODE_CLASS_OUTPUT_SHAPE,
                    "message": (
                        f"Class output {output_id} is {output_dims}; "
                        f"class input {class_id} is {class_dims}."
                    ),
                }
            )
        output = catalog.get(output_id) if output_id else None
        if isinstance(output, dict) and _forwards_value(output) is True:
            findings.append(
                {
                    "severity": "error",
                    "code": CODE_CLASS_OUTPUT_FORWARDS,
                    "message": f"Class output {output_id} forwards membrane potential.",
                }
            )
    return findings
