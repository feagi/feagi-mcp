"""Magnitude-preserving passthrough checks between two cortical areas.

Graded encoders (audio spectrum, analog sensors) carry magnitude as membrane
potential. Copying that onto an output area only works when the source hands
its firing-time potential to the synapse, the destination does not gate or
rescale it, and both areas cover the same voxels. Any one broken setting turns
graded input into saturated or truncated output, and none of them fail loudly.

``evaluate_magnitude_passthrough`` is pure: it takes the two area property
records plus one sampled voxel from each side and returns findings. The server
tool fetches those four payloads in parallel and calls it.
"""

from __future__ import annotations

import math
from typing import Any

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

CODE_MAPPING_MISSING = "mapping_missing"
CODE_MAGNITUDE_DISCARDED = "magnitude_discarded"
CODE_OUTPUT_THRESHOLD_GATES = "output_threshold_gates_magnitude"
CODE_MAGNITUDE_SCALED = "magnitude_scaled"
CODE_FAN_OUT_DIVIDES = "fan_out_divides_magnitude"
CODE_DIMENSION_MISMATCH = "dimension_mismatch"
CODE_ACCUMULATION = "destination_accumulates_across_bursts"
CODE_REFRACTORY = "destination_refractory_drops_bursts"
CODE_SNOOZE = "destination_snooze_drops_bursts"
CODE_EXCITABILITY = "destination_excitability_drops_spikes"
CODE_SOURCE_SILENCED = "source_dynamics_drop_spikes"
CODE_EDGE_VOXEL_UNWIRED = "edge_voxel_unwired"
CODE_RUNTIME_THRESHOLD_DRIFT = "runtime_threshold_drift"

#: A synapse gain that leaves magnitude unchanged.
IDENTITY_GAIN = 1.0
#: Full excitability: every above-threshold neuron fires.
FULL_EXCITABILITY = 1.0
#: Thresholds and weights round-trip through f32, so compare with tolerance.
FLOAT_REL_TOL = 1e-6


def _close(a: float, b: float) -> bool:
    """Compare two f32-derived floats."""
    return math.isclose(a, b, rel_tol=FLOAT_REL_TOL)


def _finding(severity: str, code: str, message: str, fix: dict[str, Any] | None) -> dict[str, Any]:
    """Build one finding row. ``fix`` is an ``update_cortical_area`` payload or None."""
    return {"severity": severity, "code": code, "message": message, "fix": fix}


def _first_neuron(voxel: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the first neuron of a ``get_voxel_neurons`` summary, if any."""
    if not isinstance(voxel, dict):
        return None
    neurons = voxel.get("neurons")
    if isinstance(neurons, list) and neurons and isinstance(neurons[0], dict):
        return neurons[0]
    return None


def edge_voxel(src: dict[str, Any], dst: dict[str, Any]) -> tuple[int, int, int]:
    """Farthest voxel both areas should share: last column, last row, z=0.

    Sampling this corner catches truncated mappings and stale resizes, which
    leave the far edge unwired while the origin still looks correct.
    """
    src_dims = src.get("cortical_dimensions") or [1, 1, 1]
    dst_dims = dst.get("cortical_dimensions") or [1, 1, 1]
    x = max(0, min(int(src_dims[0]), int(dst_dims[0])) - 1)
    y = max(0, min(int(src_dims[1]), int(dst_dims[1])) - 1)
    return x, y, 0


def _mapping_rules(src: dict[str, Any], dst_id: str) -> list[dict[str, Any]]:
    """Rules stored on the source record for ``dst_id``."""
    props = src.get("properties")
    bag = props.get("cortical_mapping_dst") if isinstance(props, dict) else None
    if not isinstance(bag, dict):
        bag = src.get("cortical_mapping_dst")
    rules = bag.get(dst_id) if isinstance(bag, dict) else None
    return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []


def _check_source(src: dict[str, Any], src_id: str) -> list[dict[str, Any]]:
    """Source must hand its firing-time potential to the synapse on every burst it is driven."""
    findings: list[dict[str, Any]] = []
    if src.get("neuron_mp_driven_psp") is not True:
        psp = src.get("neuron_post_synaptic_potential")
        findings.append(
            _finding(
                SEVERITY_ERROR,
                CODE_MAGNITUDE_DISCARDED,
                f"neuron_mp_driven_psp is off on the source, so every spike delivers the "
                f"fixed PSP {psp} and the encoded magnitude is lost.",
                {"cortical_id": src_id, "updates": {"neuron_mp_driven_psp": True}},
            )
        )
    # A sensory voxel written on consecutive frames must fire on each of them. Refractory
    # or snooze on the source drops those frames before any mapping sees them.
    silencing: dict[str, Any] = {}
    reasons: list[str] = []
    refractory = int(src.get("neuron_refractory_period", 0))
    if refractory > 0:
        silencing["neuron_refractory_period"] = 0
        reasons.append(f"refractory period {refractory}")
    snooze = int(src.get("neuron_snooze_period", 0))
    if snooze > 0:
        silencing["neuron_snooze_period"] = 0
        reasons.append(f"snooze period {snooze}")
    excitability = float(src.get("neuron_excitability", FULL_EXCITABILITY))
    if excitability < FULL_EXCITABILITY and not _close(excitability, FULL_EXCITABILITY):
        silencing["neuron_excitability"] = FULL_EXCITABILITY
        reasons.append(f"excitability {excitability}")
    if silencing:
        findings.append(
            _finding(
                SEVERITY_ERROR,
                CODE_SOURCE_SILENCED,
                f"Source has {', '.join(reasons)}, so a voxel written on consecutive frames "
                f"does not fire on every one and those columns never reach the output.",
                {"cortical_id": src_id, "updates": silencing},
            )
        )
    return findings


def _check_destination(
    src: dict[str, Any], dst: dict[str, Any], dst_id: str
) -> list[dict[str, Any]]:
    """Destination must fire for every magnitude the source fires for, once per burst."""
    findings: list[dict[str, Any]] = []
    src_threshold = float(src.get("neuron_fire_threshold", 0.0))
    dst_threshold = float(dst.get("neuron_fire_threshold", 0.0))
    if dst_threshold > src_threshold and not _close(dst_threshold, src_threshold):
        findings.append(
            _finding(
                SEVERITY_ERROR,
                CODE_OUTPUT_THRESHOLD_GATES,
                f"Destination fire threshold {dst_threshold} is above the source threshold "
                f"{src_threshold}; magnitudes between them fire the source but never reach "
                f"the output.",
                {"cortical_id": dst_id, "updates": {"neuron_fire_threshold": src_threshold}},
            )
        )
    if dst.get("neuron_mp_charge_accumulation") is True:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                CODE_ACCUMULATION,
                "Destination accumulates membrane potential across bursts, so magnitudes "
                "from consecutive frames add together.",
                {"cortical_id": dst_id, "updates": {"neuron_mp_charge_accumulation": False}},
            )
        )
    refractory = int(dst.get("neuron_refractory_period", 0))
    if refractory > 0:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                CODE_REFRACTORY,
                f"Destination refractory period is {refractory} bursts, so a voxel stays "
                f"silent for that many frames after each spike.",
                {"cortical_id": dst_id, "updates": {"neuron_refractory_period": 0}},
            )
        )
    snooze = int(dst.get("neuron_snooze_period", 0))
    if snooze > 0:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                CODE_SNOOZE,
                f"Destination snooze period is {snooze} bursts, so a voxel stays silent for "
                f"that many frames after each spike.",
                {"cortical_id": dst_id, "updates": {"neuron_snooze_period": 0}},
            )
        )
    excitability = float(dst.get("neuron_excitability", FULL_EXCITABILITY))
    if excitability < FULL_EXCITABILITY and not _close(excitability, FULL_EXCITABILITY):
        findings.append(
            _finding(
                SEVERITY_WARNING,
                CODE_EXCITABILITY,
                f"Destination excitability is {excitability}, so above-threshold voxels "
                f"randomly fail to fire.",
                {"cortical_id": dst_id, "updates": {"neuron_excitability": FULL_EXCITABILITY}},
            )
        )
    return findings


def _check_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mapping must not rescale the delivered potential."""
    findings: list[dict[str, Any]] = []
    for rule in rules:
        psc = float(rule.get("postSynapticCurrent_multiplier", IDENTITY_GAIN))
        if not _close(psc, IDENTITY_GAIN):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    CODE_MAGNITUDE_SCALED,
                    f"Mapping '{rule.get('morphology_id')}' has postSynapticCurrent_multiplier "
                    f"{psc}; output magnitude is input times {psc}.",
                    None,
                )
            )
    return findings


def _check_dimensions(src: dict[str, Any], dst: dict[str, Any]) -> list[dict[str, Any]]:
    """Both areas must cover the same X/Y voxels for a one-to-one copy."""
    src_dims = list(src.get("cortical_dimensions") or [])
    dst_dims = list(dst.get("cortical_dimensions") or [])
    if src_dims[:2] == dst_dims[:2]:
        return []
    return [
        _finding(
            SEVERITY_ERROR,
            CODE_DIMENSION_MISMATCH,
            f"Source is {src_dims} and destination is {dst_dims}; only the overlapping "
            f"voxels are copied, so columns land in the wrong place or are dropped.",
            None,
        )
    ]


def _check_topology(
    src_id: str,
    dst: dict[str, Any],
    src_voxel: dict[str, Any] | None,
    dst_voxel: dict[str, Any] | None,
    edge: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Realized synapses at the shared edge voxel: wired, unscaled, not fanned out."""
    findings: list[dict[str, Any]] = []
    dst_neuron = _first_neuron(dst_voxel)
    incoming = dst_neuron.get("incoming") if dst_neuron else None
    sources = incoming.get("unique_cortical_ids", []) if isinstance(incoming, dict) else []
    if src_id not in sources:
        findings.append(
            _finding(
                SEVERITY_ERROR,
                CODE_EDGE_VOXEL_UNWIRED,
                f"Destination voxel {list(edge)} has no synapse from the source. The mapping "
                f"does not reach the far edge; resize or rebuild the mapping.",
                None,
            )
        )
    elif isinstance(incoming, dict):
        for weight in incoming.get("unique_weights", []):
            if not _close(float(weight), IDENTITY_GAIN):
                findings.append(
                    _finding(
                        SEVERITY_WARNING,
                        CODE_MAGNITUDE_SCALED,
                        f"Sampled synapse weight is {weight}; output magnitude is input "
                        f"times {weight}.",
                        None,
                    )
                )
    if dst_neuron is not None:
        runtime = float(dst_neuron.get("threshold", 0.0))
        stored = float(dst.get("neuron_fire_threshold", 0.0))
        if not _close(runtime, stored):
            findings.append(
                _finding(
                    SEVERITY_WARNING,
                    CODE_RUNTIME_THRESHOLD_DRIFT,
                    f"Stored destination threshold is {stored} but the runtime neuron at "
                    f"{list(edge)} uses {runtime}.",
                    None,
                )
            )
    src_neuron = _first_neuron(src_voxel)
    outgoing = int(src_neuron.get("outgoing_synapse_count", 0)) if src_neuron else 0
    if outgoing > 1:
        findings.append(
            _finding(
                SEVERITY_WARNING,
                CODE_FAN_OUT_DIVIDES,
                f"Source voxel {list(edge)} has {outgoing} outgoing synapses; with "
                f"neuron_psp_uniform_distribution off each receives 1/{outgoing} of the "
                f"magnitude.",
                None,
            )
        )
    return findings


def evaluate_magnitude_passthrough(
    src_id: str,
    dst_id: str,
    src: dict[str, Any],
    dst: dict[str, Any],
    src_voxel: dict[str, Any] | None,
    dst_voxel: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return every setting that stops ``src`` magnitudes from reaching ``dst`` intact.

    Args:
        src_id: Source cortical id (base64).
        dst_id: Destination cortical id (base64).
        src: Source ``cortical_area_properties`` record.
        dst: Destination ``cortical_area_properties`` record.
        src_voxel: ``get_voxel_neurons`` summary at :func:`edge_voxel` in the source.
        dst_voxel: Same voxel in the destination.

    Returns:
        ``passes`` (no errors), ``findings`` with an ``update_cortical_area``
        ``fix`` where one exists, and the sampled ``edge_voxel``.
    """
    edge = edge_voxel(src, dst)
    rules = _mapping_rules(src, dst_id)
    findings: list[dict[str, Any]] = []
    if not rules:
        findings.append(
            _finding(
                SEVERITY_ERROR,
                CODE_MAPPING_MISSING,
                "The source has no mapping rule to the destination.",
                None,
            )
        )
    findings.extend(_check_source(src, src_id))
    findings.extend(_check_destination(src, dst, dst_id))
    findings.extend(_check_rules(rules))
    findings.extend(_check_dimensions(src, dst))
    if rules:
        findings.extend(_check_topology(src_id, dst, src_voxel, dst_voxel, edge))
    return {
        "src_area": src_id,
        "dst_area": dst_id,
        "src_name": src.get("cortical_name"),
        "dst_name": dst.get("cortical_name"),
        "passes": not any(f["severity"] == SEVERITY_ERROR for f in findings),
        "error_count": sum(1 for f in findings if f["severity"] == SEVERITY_ERROR),
        "warning_count": sum(1 for f in findings if f["severity"] == SEVERITY_WARNING),
        "edge_voxel": list(edge),
        "findings": findings,
    }
