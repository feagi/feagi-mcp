"""Build a circuit (region, areas, morphologies, mappings) from one JSON spec.

:func:`expand_spec` is pure: it validates the spec, expands the named templates into plain
areas, morphologies and mappings, sizes the synaptic gains from the stated neuron
parameters, and returns the plan plus the ``calls`` a real run would make.
:func:`execute_plan` runs a plan through the existing client create/mapping paths.

Spec::

    {"region": {"title", "coordinates_2d", "coordinates_3d", "parent_region_id"?}
               | {"region_id"},
     "defaults": {"origin": [x, y, z]?, "step": 40?},
     "areas": [{"name", "dimensions", "position"?, "neurons_per_voxel"?, "properties"?,
                "cortical_type"?: "CUSTOM"|"MEMORY", "mp_encoding"?, "modulators"?: [ids]}],
     "morphologies": [{"name", "type", "parameters"}],
     "mappings": [{"src", "dst", "rules": [...], "replace"?, "modulators"?: [ids],
                   "frozen"?: bool}],
     "delete": [{"src", "dst"}],
     "edit_areas": [{"name", "properties"}],
     "templates": [{"template": "port|onset_pulse|ring_cpg|servo_channel_two_rest|"
                                "phase_window_gate", "name": str, ...}]}

``delete`` removes the mappings between two live areas (run before the new mappings, so a pair
may be deleted and rebuilt in one spec). ``edit_areas`` changes ``properties`` of live areas
that are members of the existing ``region.region_id`` (new areas in that region are ordinary
``areas`` with a ``position``). A mapping with ``frozen: true`` is written as given, then frozen
through ``PUT /v1/cortical_mapping/plasticity_frozen`` and read back with the GET route; the
rules keep their ``plasticity_flag`` and mode, and FEAGI keeps the synapses and weights. The
mapping must hold a plastic rule, or FEAGI rejects the freeze and the run stops there.

Names in ``src``/``dst`` are spec areas or live areas (resolved when run). Membrane model used
for sizing (feagi-core ``neural_dynamics``): ``V <- V * (1 - leak) + I``, fire at ``V >= T``,
reset to 0 on fire; an area's PSP times a mapping's PSC multiplier is the input a spike adds.
"""

from __future__ import annotations

import base64
import binascii
import math
from collections.abc import Callable
from typing import Any

from feagi_mcp.connectivity_rules import validate_morphology_parameters
from feagi_mcp.stance_mapping import compile_stance_offset_rows, value_to_z_bin

GRID_COLUMNS = 6
DEFAULT_STEP = 40
EPS = 1e-9

_MISSING = object()


class SpecError(ValueError):
    """A spec or template parameter is invalid; the message names the field."""


def _fnum(
    t: dict[str, Any],
    key: str,
    default: Any = _MISSING,
    *,
    positive: bool = False,
    minimum: float | None = None,
) -> float:
    value = t.get(key, default)
    if value is _MISSING or value is None:
        raise SpecError(f"{t.get('template', 'spec')} '{t.get('name', '?')}': '{key}' is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SpecError(f"'{t.get('name', '?')}': '{key}' must be a finite number")
    if positive and value <= 0:
        raise SpecError(f"'{t.get('name', '?')}': '{key}' must be > 0")
    if minimum is not None and value < minimum:
        raise SpecError(f"'{t.get('name', '?')}': '{key}' must be >= {minimum}")
    return float(value)


def _inum(t: dict[str, Any], key: str, default: Any = _MISSING, *, minimum: int = 0) -> int:
    value = t.get(key, default)
    if value is _MISSING or value is None:
        raise SpecError(f"{t.get('template', 'spec')} '{t.get('name', '?')}': '{key}' is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"'{t.get('name', '?')}': '{key}' must be an integer")
    if value < minimum:
        raise SpecError(f"'{t.get('name', '?')}': '{key}' must be >= {minimum}")
    return value


def _name(t: dict[str, Any]) -> str:
    name = t.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SpecError(f"template '{t.get('template')}': 'name' must be a non-empty string")
    return name.strip()


def _ref(t: dict[str, Any], key: str, *, required: bool = True) -> str | None:
    value = t.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"'{t.get('name', '?')}': '{key}' must be an area name")
    return value.strip()


def _clean(x: float) -> int | float:
    """Integral floats as ints so the rules read like hand-written ones."""
    return int(x) if float(x).is_integer() else x


def rule(morphology: str, psc: float, delay: int = 1) -> dict[str, Any]:
    """One mapping rule (the fields the live genome stores for a non-plastic rule)."""
    return {
        "morphology_id": morphology,
        "morphology_scalar": [1, 1, 1],
        "postSynapticCurrent_multiplier": _clean(psc),
        "plasticity_flag": False,
        "synaptic_delay_bursts": delay,
    }


def neuron_props(
    threshold: float,
    psp: float,
    leak: float = 0.0,
    refractory: int = 0,
    accumulate: bool = True,
    psp_uniform: bool | None = None,
) -> dict[str, Any]:
    """Neuron parameters for ``create_cortical_area`` (API names)."""
    props: dict[str, Any] = {
        "neuron_fire_threshold": threshold,
        "neuron_post_synaptic_potential": psp,
        "neuron_leak_coefficient": leak,
        "neuron_refractory_period": refractory,
        "neuron_mp_charge_accumulation": accumulate,
    }
    if psp_uniform is not None:
        props["neuron_psp_uniform_distribution"] = psp_uniform
    return props


# Spec shorthand -> the keys FEAGI's mapping API stores.
RULE_KEY_ALIASES = {
    "morphology": "morphology_id",
    "psc": "postSynapticCurrent_multiplier",
    "psc_multiplier": "postSynapticCurrent_multiplier",
    "delay": "synaptic_delay_bursts",
    "plastic": "plasticity_flag",
    "scalar": "morphology_scalar",
}
RULE_KEYS = frozenset(
    {
        "morphology_id",
        "morphology_scalar",
        "postSynapticCurrent_multiplier",
        "plasticity_flag",
        "plasticity_constant",
        "ltp_multiplier",
        "ltd_multiplier",
        "plasticity_window",
        "synaptic_delay_bursts",
        "plasticity_mode",
        "eligibility_decay_bursts",
        "modulators",
        "max_weight",
        "plasticity_eta",
    }
)


def normalize_rule(raw: Any) -> dict[str, Any]:
    """Translate a spec rule to the payload the mapping API takes, or raise ``SpecError``.

    Accepts the shorthand keys of ``RULE_KEY_ALIASES`` (``morphology``, ``psc``, ``delay``,
    ``plastic``, ``scalar``) as well as the API keys, fills the defaults a non-plastic rule needs
    (``morphology_scalar`` [1,1,1], ``synaptic_delay_bursts`` 1, ``plasticity_flag`` false) and
    checks the result, so the dry run and the real run validate the same payload.
    """
    if not isinstance(raw, dict):
        raise SpecError(f"mapping rule {raw!r} must be an object")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        target = RULE_KEY_ALIASES.get(str(key), str(key))
        if target in out:
            raise SpecError(f"rule {raw!r} sets '{target}' twice (alias and API key)")
        out[target] = value
    unknown = sorted(set(out) - RULE_KEYS)
    if unknown:
        raise SpecError(f"rule {raw!r}: unknown key(s) {unknown}; allowed: {sorted(RULE_KEYS)}")
    morph = out.get("morphology_id")
    if not isinstance(morph, str) or not morph.strip():
        raise SpecError(f"rule {raw!r}: 'morphology_id' (or 'morphology') must be a string")
    psc = out.get("postSynapticCurrent_multiplier")
    if isinstance(psc, bool) or not isinstance(psc, (int, float)) or not math.isfinite(psc):
        raise SpecError(f"rule for '{morph}': 'postSynapticCurrent_multiplier' (or 'psc') needed")
    delay = out.setdefault("synaptic_delay_bursts", 1)
    if isinstance(delay, bool) or not isinstance(delay, int) or delay < 1:
        raise SpecError(f"rule for '{morph}': synaptic_delay_bursts must be an integer >= 1")
    scalar = out.setdefault("morphology_scalar", [1, 1, 1])
    if not (isinstance(scalar, list) and len(scalar) == 3):
        raise SpecError(f"rule for '{morph}': morphology_scalar must be [x, y, z]")
    out.setdefault("plasticity_flag", False)
    validate_plasticity(out)
    return out


PLASTICITY_MODES = ("off", "stdp", "rstdp")
MEMORY_MORPHOLOGIES = ("episodic_memory", "associative_memory")
MEMORY_KEYS = frozenset(
    {
        "temporal_depth",
        "neuron_init_lifespan",
        "neuron_lifespan_growth_rate",
        "neuron_longterm_mem_threshold",
        "memory_neuron_cap",
        "ltm_eviction",
        "mp_learning_enabled",
        "mp_change_mode",
        "mp_delta_quantization",
        "mp_ratio_quantization",
    }
)
_MP_QUANT_KEY = {"mp_differential": "mp_delta_quantization", "mp_ratio": "mp_ratio_quantization"}


# Spec/skill names for neuron parameters -> the API key the area endpoints take.
PROPERTY_ALIASES = {
    "firing_threshold": "neuron_fire_threshold",
    "postsynaptic_current": "neuron_post_synaptic_potential",
    "psp": "neuron_post_synaptic_potential",
}
MEMORY_PSP_DEFAULT_WARNING = (
    "area '{name}': MEMORY area without neuron_post_synaptic_potential gets the core default "
    "(postsynaptic_current 500); set it explicitly"
)


def is_memory_cortical_id(cortical_id: Any) -> bool:
    """True when the id is a MEMORY area id: byte 0 of the decoded 8-byte id is ``m``.

    Live ids are base64 of 8 bytes, so the type is never read from the base64 text itself.
    """
    if not isinstance(cortical_id, str) or not cortical_id.strip():
        return False
    try:
        raw = base64.b64decode(cortical_id.strip(), validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw) == 8 and raw[0] == ord("m")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_plasticity(rule_: dict[str, Any]) -> None:
    """Check the plastic fields of a normalized rule; raise ``SpecError`` on an illegal mix.

    ``plasticity_mode`` stdp/rstdp switches ``plasticity_flag`` on; ``off`` with the flag on is a
    contradiction. rstdp needs a ``modulators`` list (R(t) would stay 0 and the core rejects it).
    ``eligibility_decay_bursts`` is rstdp-only (on other rules the update returns HTTP 500).
    """
    m = rule_["morphology_id"]
    mode = rule_.get("plasticity_mode")
    if mode is not None and mode not in PLASTICITY_MODES:
        raise SpecError(f"rule for '{m}': plasticity_mode must be one of {list(PLASTICITY_MODES)}")
    if mode in ("stdp", "rstdp"):
        rule_["plasticity_flag"] = True
    elif mode == "off" and rule_.get("plasticity_flag"):
        raise SpecError(f"rule for '{m}': plasticity_mode off contradicts plasticity_flag true")
    plastic_fields = (
        "plasticity_constant",
        "ltp_multiplier",
        "ltd_multiplier",
        "plasticity_window",
        "max_weight",
        "plasticity_eta",
        "eligibility_decay_bursts",
    )
    given = [k for k in plastic_fields if k in rule_]
    if given and not rule_.get("plasticity_flag"):
        raise SpecError(
            f"rule for '{m}': {given} need plasticity_mode stdp/rstdp (or plasticity_flag true)"
        )
    for key in ("ltp_multiplier", "ltd_multiplier"):
        if key in rule_ and not (_is_int(rule_[key]) and -128 <= rule_[key] <= 127):
            raise SpecError(f"rule for '{m}': {key} must be an integer in -128..127")
    for key in ("plasticity_constant", "plasticity_window"):
        if key in rule_ and not (_is_int(rule_[key]) and rule_[key] >= 1):
            raise SpecError(f"rule for '{m}': {key} must be an integer >= 1")
    if "plasticity_eta" in rule_ and not (
        _is_num(rule_["plasticity_eta"]) and 0 < rule_["plasticity_eta"] <= 1
    ):
        raise SpecError(f"rule for '{m}': plasticity_eta must be in (0, 1]")
    if "max_weight" in rule_ and not (_is_num(rule_["max_weight"]) and rule_["max_weight"] > 0):
        raise SpecError(f"rule for '{m}': max_weight must be a number > 0")
    if "eligibility_decay_bursts" in rule_:
        if mode != "rstdp":
            raise SpecError(f"rule for '{m}': eligibility_decay_bursts needs plasticity_mode rstdp")
        v = rule_["eligibility_decay_bursts"]
        if not (_is_int(v) and v >= 0):
            raise SpecError(f"rule for '{m}': eligibility_decay_bursts must be an integer >= 0")
    mods = rule_.get("modulators")
    if mods is not None and not (
        isinstance(mods, list) and all(isinstance(x, str) and x.strip() for x in mods)
    ):
        raise SpecError(f"rule for '{m}': modulators must be a list of modulator ids")
    if mode == "rstdp" and not mods:
        raise SpecError(
            f"rule for '{m}': plasticity_mode rstdp needs a synaptic.reward id in modulators"
        )


def memory_properties(
    name: str, cortical_type: str, props: dict[str, Any], mp_encoding: Any
) -> dict[str, Any]:
    """Validate a MEMORY area's parameters; fold ``mp_encoding`` into the API keys.

    ``mp_encoding`` is a mode string or ``{mode, delta_quantization?, ratio_quantization?}`` with
    the modes of ``set_memory_mp_encoding``. Change modes need ``temporal_depth`` >= 2.
    """
    out = dict(props)
    for alias, key in PROPERTY_ALIASES.items():
        if alias in out:
            if key in out:
                raise SpecError(f"area '{name}': sets both '{alias}' and '{key}'")
            out[key] = out.pop(alias)
    if cortical_type != "MEMORY":
        bad = sorted(set(out) & MEMORY_KEYS)
        if bad or mp_encoding is not None:
            raise SpecError(
                f"area '{name}': {bad or ['mp_encoding']} are memory parameters; "
                "set cortical_type MEMORY"
            )
        return out
    for key in ("temporal_depth", "neuron_init_lifespan", "neuron_longterm_mem_threshold"):
        if key in out and not (_is_int(out[key]) and out[key] >= 1):
            raise SpecError(f"area '{name}': {key} must be an integer >= 1")
    if "neuron_lifespan_growth_rate" in out and not (
        _is_int(out["neuron_lifespan_growth_rate"]) and out["neuron_lifespan_growth_rate"] >= 0
    ):
        raise SpecError(f"area '{name}': neuron_lifespan_growth_rate must be an integer >= 0")
    if "memory_neuron_cap" in out and not (
        _is_int(out["memory_neuron_cap"]) and out["memory_neuron_cap"] >= 0
    ):
        raise SpecError(f"area '{name}': memory_neuron_cap must be an integer >= 0")
    if "ltm_eviction" in out:
        ev = out["ltm_eviction"]
        if not (isinstance(ev, str) and ev.strip().lower() in ("lru", "none")):
            raise SpecError(f"area '{name}': ltm_eviction must be 'lru' or 'none'")
        out["ltm_eviction"] = ev.strip().lower()
    if mp_encoding is not None:
        enc: Any = {"mode": mp_encoding} if isinstance(mp_encoding, str) else mp_encoding
        mode = enc.get("mode") if isinstance(enc, dict) else None
        if mode not in ("none", "mp_learning", "mp_differential", "mp_ratio"):
            raise SpecError(
                f"area '{name}': mp_encoding mode must be none, mp_learning, mp_differential "
                "or mp_ratio"
            )
        out["mp_learning_enabled"] = mode == "mp_learning"
        out["mp_change_mode"] = mode if mode in _MP_QUANT_KEY else "none"
        for qk, ek in (
            ("mp_delta_quantization", "delta_quantization"),
            ("mp_ratio_quantization", "ratio_quantization"),
        ):
            if ek in enc:
                if _MP_QUANT_KEY.get(mode) != qk:
                    raise SpecError(f"area '{name}': {ek} does not apply to mode {mode}")
                quant = enc[ek]
                if not (_is_num(quant) and quant > 0):
                    raise SpecError(f"area '{name}': {ek} must be a number > 0")
                out[qk] = float(quant)
        depth = out.get("temporal_depth")
        if mode in _MP_QUANT_KEY and not (isinstance(depth, int) and depth >= 2):
            raise SpecError(f"area '{name}': mp_encoding {mode} needs temporal_depth >= 2")
    return out


def check_memory_wiring(plan: Plan) -> None:
    """Legal memory mappings for spec-defined areas (live areas are checked when run).

    ``episodic_memory`` must end in a MEMORY area; ``associative_memory`` must start in one.
    Rules reach here with ``synaptic_delay_bursts`` >= 1 already (delay 0 returns HTTP 500).
    """
    kind = {a["name"]: a["cortical_type"] for a in plan.areas}
    for (src, dst), mp in plan.mappings.items():
        for r in mp["rules"]:
            morph = r["morphology_id"]
            if morph == "episodic_memory" and kind.get(dst, "MEMORY") != "MEMORY":
                raise SpecError(f"{src} -> {dst}: episodic_memory must end in a MEMORY area")
            if morph == "associative_memory" and kind.get(src, "MEMORY") != "MEMORY":
                raise SpecError(
                    f"{src} -> {dst}: associative_memory is legal only FROM a MEMORY area"
                )


def apply_property_schema(
    plan: Plan, parameters: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Check (and normalize) every area's ``properties`` against FEAGI's parameter schema.

    ``parameters`` is the ``parameters`` list of ``GET /v1/cortical_area/parameter_schema``
    (``key``, ``aliases``, ``type``, ``min``, ``max``, ``unit``). Unknown keys and out-of-range
    numbers are errors. A ``fraction`` parameter given as a percent (above its max, up to 100,
    the form inspect returns for some existing areas) is divided by 100 with a warning.
    Returns ``(errors, warnings)``; values are normalized in place.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for param in parameters:
        by_key[param["key"]] = param
        for alias in param.get("aliases") or []:
            by_key[alias] = param
    errors: list[str] = []
    warnings: list[str] = []
    for area in [*plan.areas, *plan.edits]:
        for key, value in list(area["properties"].items()):
            known = by_key.get(key)
            if known is None:
                errors.append(
                    f"area '{area['name']}': unknown property '{key}'; valid keys: {sorted(by_key)}"
                )
                continue
            spec_param = known
            if known["key"] != key:
                area["properties"][known["key"]] = area["properties"].pop(key)
                key = known["key"]
            if spec_param.get("type") != "number":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"area '{area['name']}': '{key}' must be a number")
                continue
            lo, hi = spec_param.get("min"), spec_param.get("max")
            if (
                spec_param.get("unit") == "fraction"
                and isinstance(hi, (int, float))
                and hi < value <= 100
            ):
                area["properties"][key] = value / 100
                warnings.append(
                    f"area '{area['name']}': '{key}' {value:g} read as a percent "
                    f"(the API takes a fraction 0..{hi:g}); sent {value / 100:g}"
                )
                continue
            if (isinstance(lo, (int, float)) and value < lo) or (
                isinstance(hi, (int, float)) and value > hi
            ):
                errors.append(
                    f"area '{area['name']}': '{key}' {value:g} is outside the API range {lo}..{hi}"
                )
    return errors, warnings


def auto_region_2d(regions: dict[str, Any], parent_region_id: str | None) -> list[int]:
    """Brain-map position one step past the sibling regions, in the same row.

    ``regions`` is the ``regions_members`` payload. Siblings share ``parent_region_id`` (the
    root when None). The step is the gap between the two largest distinct sibling x values
    (400 with fewer than two); the row is the y of the right-most sibling.
    """
    root = next((rid for rid, r in regions.items() if r.get("parent_region_id") is None), None)
    parent = parent_region_id or root
    sibs = [
        r["coordinate_2d"]
        for r in regions.values()
        if r.get("parent_region_id") == parent
        and isinstance(r.get("coordinate_2d"), list)
        and len(r["coordinate_2d"]) == 2
    ]
    if not sibs:
        return [0, 0]
    xs = sorted({int(c[0]) for c in sibs})
    step = xs[-1] - xs[-2] if len(xs) > 1 else 400
    row_y = min(int(c[1]) for c in sibs if int(c[0]) == xs[-1])
    return [xs[-1] + step, row_y]


class Plan:
    """Areas, morphologies and mappings collected while expanding a spec."""

    def __init__(self) -> None:
        self.region: dict[str, Any] | None = None
        self.areas: list[dict[str, Any]] = []
        self.morphologies: list[dict[str, Any]] = []
        self.mappings: dict[tuple[str, str], dict[str, Any]] = {}
        self.deletions: list[tuple[str, str]] = []
        self.edits: list[dict[str, Any]] = []
        self.sizing: dict[str, Any] = {}
        self.warnings: list[str] = []

    def add_area(
        self,
        name: str,
        dims: list[int],
        props: dict[str, Any] | None = None,
        neurons_per_voxel: int = 1,
        position: list[int] | None = None,
        cortical_type: str = "CUSTOM",
        modulators: list[str] | None = None,
    ) -> None:
        if cortical_type not in ("CUSTOM", "MEMORY"):
            raise SpecError(f"area '{name}': cortical_type must be CUSTOM or MEMORY")
        mods = modulators
        if mods is not None and not (
            isinstance(mods, list) and all(isinstance(x, str) and x.strip() for x in mods)
        ):
            raise SpecError(f"area '{name}': modulators must be a list of modulator ids")
        if any(a["name"] == name for a in self.areas):
            raise SpecError(f"area '{name}' is defined twice")
        self.areas.append(
            {
                "name": name,
                "dimensions": [int(d) for d in dims],
                "position": position,
                "neurons_per_voxel": neurons_per_voxel,
                "properties": dict(props or {}),
                "cortical_type": cortical_type,
                "modulators": list(modulators or []),
            }
        )

    def add_morphology(self, name: str, mtype: str, parameters: dict[str, Any]) -> None:
        if any(m["name"] == name for m in self.morphologies):
            raise SpecError(f"morphology '{name}' is defined twice")
        judgment = validate_morphology_parameters(mtype, parameters)
        if judgment.get("reject"):
            raise SpecError(f"morphology '{name}' rejected: {'; '.join(judgment['errors'])}")
        self.morphologies.append({"name": name, "type": mtype, "parameters": parameters})

    def add_patterns(self, name: str, rows: list[Any]) -> None:
        self.add_morphology(name, "patterns", {"patterns": rows})

    def add_rules(
        self,
        src: str,
        dst: str,
        rules: list[dict[str, Any]],
        replace: bool = False,
        modulators: list[str] | None = None,
        frozen: bool = False,
    ) -> None:
        entry = self.mappings.setdefault(
            (src, dst), {"src": src, "dst": dst, "rules": [], "replace": False, "frozen": False}
        )
        for raw in rules:
            if modulators and isinstance(raw, dict) and "modulators" not in raw:
                raw = {**raw, "modulators": list(modulators)}
            entry["rules"].append(normalize_rule(raw))
        entry["replace"] = entry["replace"] or replace
        # Frozen through feagi-core's plasticity_frozen route after the rules are written;
        # the rules keep their plasticity_flag and mode.
        entry["frozen"] = entry["frozen"] or frozen


# ---------------------------------------------------------------- templates


def _tpl_port(t: dict[str, Any], plan: Plan) -> None:
    """A ``[1,1,N]`` leaky integrator with an optional self-hold mapping."""
    name = _name(t)
    bins = _inum(t, "bins", minimum=1)
    threshold = _fnum(t, "threshold", positive=True)
    psp = _fnum(t, "psp", positive=True)
    leak = _fnum(t, "leak", 0.0, minimum=0.0)
    refractory = _inum(t, "refractory", 0)
    plan.add_area(name, [1, 1, bins], neuron_props(threshold, psp, leak, refractory))
    sizing: dict[str, Any] = {"threshold": threshold, "psp": psp}
    if t.get("self_hold", True):
        inp = _fnum(t, "input", positive=True)
        if inp >= threshold:
            plan.warnings.append(
                f"port '{name}': input {inp:g} >= threshold {threshold:g}; the port already "
                "fires on every input burst, self-hold skipped"
            )
        else:
            low = threshold - inp
            if t.get("hold_psc") is not None:
                psc = _fnum(t, "hold_psc")
            else:
                psc = round((threshold - inp / 2) / psp, 4)
            s = psp * psc
            if not (low - EPS <= s < threshold):
                raise SpecError(
                    f"port '{name}': self-hold s = psp x psc = {s:g} must satisfy "
                    f"{low:g} <= s < {threshold:g} (threshold - input <= s < threshold)"
                )
            plan.add_rules(name, name, [rule("block_to_block", psc)])
            sizing.update(
                {
                    "input": inp,
                    "hold_interval": [low, threshold],
                    "self_hold_s": round(s, 6),
                    "hold_psc": _clean(psc),
                }
            )
    plan.sizing[name] = {"template": "port", **sizing}


def _tpl_onset_pulse(t: dict[str, Any], plan: Plan) -> None:
    """gate -> Onset; a one-burst Delay copy of the gate inhibits Onset from the next burst."""
    name = _name(t)
    gate = _ref(t, "gate")
    assert gate is not None
    threshold = _fnum(t, "threshold", 1.0, positive=True)
    psp = _fnum(t, "psp", 1.0, positive=True)
    gate_psp = _fnum(t, "gate_psp", 1.0, positive=True)
    exc = _fnum(t, "exc_psc", 1.0, positive=True)
    if gate_psp * exc < threshold:
        raise SpecError(
            f"onset_pulse '{name}': gate_psp x exc_psc = {gate_psp * exc:g} is below the "
            f"threshold {threshold:g}; Onset would never fire"
        )
    inh_default = math.ceil(gate_psp * exc / psp - EPS)
    inh = _fnum(t, "inh_psc", float(inh_default), positive=True)
    if psp * inh < gate_psp * exc - EPS:
        raise SpecError(
            f"onset_pulse '{name}': inhibition {psp * inh:g} is smaller than the gate input "
            f"{gate_psp * exc:g}; Onset would keep firing"
        )
    onset, delay = f"{name}_Onset", f"{name}_Delay"
    props = neuron_props(threshold, psp, accumulate=False)
    plan.add_area(onset, [1, 1, 1], props)
    plan.add_area(delay, [1, 1, 1], props)
    plan.add_rules(gate, onset, [rule("all_to_0-0-0", exc)])
    plan.add_rules(gate, delay, [rule("all_to_0-0-0", exc)])
    plan.add_rules(delay, onset, [rule("block_to_block", -inh)])
    plan.sizing[name] = {
        "template": "onset_pulse",
        "gate_input": gate_psp * exc,
        "inhibition": psp * inh,
        "net_second_burst": gate_psp * exc - psp * inh,
    }


def predicted_step_bursts(p_plus_d: float, leak: float, threshold: float) -> int | None:
    """Bursts for a bin to reach threshold under constant input: V_n = sum (p+d)(1-g)^i."""
    if p_plus_d <= 0:
        return None
    if leak <= 0:
        return math.ceil(threshold / p_plus_d - EPS)
    ceiling = p_plus_d / leak
    if ceiling < threshold - EPS:
        return None
    ratio = 1 - threshold * leak / p_plus_d
    if ratio <= 0:
        return 1
    n = math.log(ratio) / math.log(1 - leak)
    return max(1, math.ceil(n - EPS))


def _shift_rows(bins: int, shift: int) -> list[Any]:
    return [
        [["*", "*", f"0..{bins - shift - 1}"], ["?", "?", f"?+{shift}"]],
        [["*", "*", f"{bins - shift}..{bins - 1}"], ["?", "?", f"?-{bins - shift}"]],
    ]


def _tpl_ring_cpg(t: dict[str, Any], plan: Plan) -> None:
    """A self-holding ring: lateral excitation steps the active bin, inhibition clears it."""
    name = _name(t)
    bins = _inum(t, "bins", minimum=2)
    threshold = _fnum(t, "threshold", positive=True)
    psp = _fnum(t, "psp", positive=True)
    leak = _fnum(t, "leak", 0.0, minimum=0.0)
    refractory = _inum(t, "refractory", 0)
    drive = _ref(t, "drive")
    assert drive is not None
    d = _fnum(t, "drive_d", positive=True)
    drive_psp = _fnum(t, "drive_psp", 1.0, positive=True)
    lateral = _fnum(t, "lateral_psc")
    if lateral <= 0:
        raise SpecError(f"ring_cpg '{name}': lateral_psc must be > 0")
    inhibit = _fnum(t, "inhibit_psc", -abs(lateral))
    if inhibit >= 0:
        raise SpecError(f"ring_cpg '{name}': inhibit_psc must be negative")
    low = threshold - d
    if t.get("hold_psc") is not None:
        hold_psc = _fnum(t, "hold_psc")
    else:
        hold_psc = round((threshold - d / 2) / psp, 4)
    s = psp * hold_psc
    if not (low - EPS <= s < threshold):
        raise SpecError(
            f"ring_cpg '{name}': self-hold s = {s:g} must satisfy {low:g} <= s < {threshold:g}"
        )
    plan.add_area(
        name,
        [1, 1, bins],
        neuron_props(threshold, psp, leak, refractory, psp_uniform=True),
        neurons_per_voxel=1,
    )
    plan.add_rules(
        name,
        name,
        [
            rule("block_to_block", hold_psc),
            rule("lateral_+z", lateral),
            rule("last_to_first", lateral),
            rule("lateral_-z", inhibit),
            rule("first_to_last", inhibit),
        ],
    )
    plan.add_rules(drive, name, [rule("0-0-0_to_all", d / drive_psp)])
    predicted = predicted_step_bursts(psp * lateral + d, leak, threshold)
    sizing: dict[str, Any] = {
        "template": "ring_cpg",
        "hold_interval": [low, threshold],
        "self_hold_s": round(s, 6),
        "hold_psc": _clean(hold_psc),
        "drive_psc": _clean(d / drive_psp),
        "predicted_step_bursts": predicted,
        "predicted_step_status": "uncalibrated: check the period with record_spikes",
    }
    want = t.get("step_bursts")
    if want is not None and predicted != want:
        plan.warnings.append(
            f"ring_cpg '{name}': step_bursts {want} requested, model predicts {predicted} "
            "from lateral_psc, drive_d, leak and threshold; verify with record_spikes"
        )
    seed = t.get("seed")
    if seed is not None:
        seed_area = _ref(seed, "area")
        assert seed_area is not None
        b = _inum(seed, "bin", 0, minimum=0)
        if b >= bins:
            raise SpecError(f"ring_cpg '{name}': seed bin {b} is outside 0..{bins - 1}")
        seed_psp = _fnum(seed, "psp", 1.0, positive=True)
        seed_psc = _fnum(seed, "psc", float(math.ceil(threshold / seed_psp - EPS)), positive=True)
        morph = f"{name}_seed_bin{b}"
        plan.add_patterns(morph, [[["*", "*", "*"], [0, 0, b]]])
        plan.add_rules(seed_area, name, [rule(morph, seed_psc)])
        sizing["seed_psc"] = _clean(seed_psc)
    for ro in t.get("readouts") or []:
        ro_name = _ref(ro, "name")
        assert ro_name is not None
        shift = _inum(ro, "shift", 0, minimum=0)
        if shift >= bins:
            raise SpecError(f"ring_cpg '{name}': readout shift {shift} must be < bins {bins}")
        ro_thr = _fnum(ro, "threshold", 1.0, positive=True)
        ro_psc = _fnum(ro, "psc", float(math.ceil(ro_thr / psp - EPS)), positive=True)
        plan.add_area(ro_name, [1, 1, bins], neuron_props(ro_thr, 1.0, accumulate=False))
        if shift == 0:
            plan.add_rules(name, ro_name, [rule("block_to_block", ro_psc)])
        else:
            morph = f"{name}_readout_{ro_name}_shift{shift}"
            plan.add_patterns(morph, _shift_rows(bins, shift))
            plan.add_rules(name, ro_name, [rule(morph, ro_psc)])
    plan.sizing[name] = sizing


def _runs(bins: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for b in sorted(bins):
        if runs and b == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], b)
        else:
            runs.append((b, b))
    return runs


def _tpl_servo_two_rest(t: dict[str, Any], plan: Plan) -> None:
    """Two rest voxels per channel (stance z+1 / z-1) from a tonic area, plus offset sources."""
    name = _name(t)
    opu = _ref(t, "opu")
    tonic = _ref(t, "tonic")
    assert opu is not None and tonic is not None
    depth = _inum(t, "depth", minimum=4)
    z0_is_max = bool(t.get("z0_is_max", True))
    channels = t.get("channels")
    if not isinstance(channels, list) or not channels:
        raise SpecError(f"servo_channel_two_rest '{name}': 'channels' must be a non-empty list")
    by_channel: dict[int, dict[str, Any]] = {}
    for ch in channels:
        if not isinstance(ch, dict) or "channel" not in ch or "reference" not in ch:
            raise SpecError(f"'{name}': each channel needs 'channel' and 'reference'")
        rng = ch.get("range")
        if not isinstance(rng, list) or len(rng) != 2:
            raise SpecError(f"'{name}': channel {ch.get('channel')} needs range [min, max]")
        by_channel[int(ch["channel"])] = ch
    n_channels = _inum(t, "opu_channels", max(by_channel) + 1, minimum=max(by_channel) + 1)
    tonic_psp = _fnum(t, "tonic_psp", 1.0, positive=True)
    tonic_psc = _fnum(t, "tonic_psc", positive=True)
    rest_thr = _fnum(t, "rest_threshold", 1.0, positive=True)
    rest_psp = _fnum(t, "rest_psp", 1.0, positive=True)
    opu_psc = _fnum(t, "opu_psc", 1.0, positive=True)
    allow_clamp = bool(t.get("allow_clamp", False))
    tonic_mp = tonic_psp * tonic_psc
    if tonic_mp < rest_thr:
        raise SpecError(
            f"servo_channel_two_rest '{name}': tonic input {tonic_mp:g} is below the rest "
            f"threshold {rest_thr:g}; the rest neurons would not fire"
        )
    stance: dict[int, int] = {}
    for c, ch in by_channel.items():
        lo, hi = float(ch["range"][0]), float(ch["range"][1])
        z = value_to_z_bin(float(ch["reference"]), lo, hi, depth, z0_is_max)
        if z < 1 or z > depth - 2:
            raise SpecError(
                f"'{name}': channel {c} stance z={z} leaves no room for rest voxels at z+1 / z-1"
            )
        stance[c] = z
    rest = {"reflex": f"{name}_RestReflex", "pattern": f"{name}_RestPattern"}
    rest_z = {
        "reflex": {c: z + 1 for c, z in stance.items()},
        "pattern": {c: z - 1 for c, z in stance.items()},
    }
    props = neuron_props(rest_thr, rest_psp, accumulate=False, psp_uniform=True)
    for role, rest_area in rest.items():
        plan.add_area(rest_area, [n_channels, 1, depth], props)
        morph = f"{name}_tonic_to_rest_{role}"
        plan.add_patterns(
            morph, [[["*", "*", "*"], [c, 0, rest_z[role][c]]] for c in sorted(stance)]
        )
        plan.add_rules(tonic, rest_area, [rule(morph, tonic_psc)])
    to_opu = f"{name}_rest_to_opu"
    plan.add_patterns(to_opu, [[["*", "*", "*"], ["?", "?", "?"]]])
    for rest_area in rest.values():
        plan.add_rules(rest_area, opu, [rule(to_opu, opu_psc)])
    sources = t.get("sources") or []
    if not isinstance(sources, list):
        raise SpecError(f"'{name}': 'sources' must be a list")
    sizing: dict[str, Any] = {
        "template": "servo_channel_two_rest",
        "stance_z": {str(c): z for c, z in sorted(stance.items())},
        "rest_z_reflex": {str(c): z for c, z in sorted(rest_z["reflex"].items())},
        "rest_z_pattern": {str(c): z for c, z in sorted(rest_z["pattern"].items())},
        "sources": [],
    }
    for src in sources:
        role = src.get("role")
        if role not in rest:
            raise SpecError(f"'{name}': source role must be 'reflex' or 'pattern'")
        area = _ref(src, "area")
        assert area is not None
        c = _inum(src, "channel", minimum=0)
        if c not in by_channel:
            raise SpecError(f"'{name}': source '{area}' uses channel {c} not in 'channels'")
        other = "pattern" if role == "reflex" else "reflex"
        src_psp = _fnum(src, "psp", 1.0, positive=True)
        compiled = compile_stance_offset_rows(
            src_axis=str(src.get("src_axis", "z")),
            src_bins=_inum(src, "src_bins", minimum=1),
            src_fixed=list(src.get("src_fixed") or ["*", "*", "*"]),
            channels=[
                {
                    "channel": c,
                    "reference": by_channel[c]["reference"],
                    "range": by_channel[c]["range"],
                }
            ],
            depth=depth,
            gain=_fnum(src, "gain"),
            deadband=_fnum(src, "deadband", 0.0, minimum=0.0),
            max_offset=src.get("max_offset"),
            z0_is_max=z0_is_max,
            coactive_z={c: rest_z[other][c]},
        )
        clamped = [w for w in compiled["warnings"] if "clamped" in w]
        if clamped and not allow_clamp:
            raise SpecError(f"'{name}' source '{area}': {clamped[0]}")
        plan.warnings.extend(f"'{name}' source '{area}': {w}" for w in compiled["warnings"])
        if not compiled["voxel_mappings"]:
            raise SpecError(f"'{name}' source '{area}': every source bin is in the deadband")
        off = f"{name}_{area}_offset"
        plan.add_patterns(off, [[vm["src"], vm["dst"]] for vm in compiled["voxel_mappings"]])
        plan.add_rules(area, opu, [rule(off, opu_psc)])
        axis = {"x": 0, "y": 1, "z": 2}[str(src.get("src_axis", "z")).lower()]
        fixed = list(src.get("src_fixed") or ["*", "*", "*"])
        inhibit_rows = []
        for a, b in _runs([r["src_bin"] for r in compiled["table"] if r["dst_z"] is not None]):
            row_src = list(fixed)
            row_src[axis] = a if a == b else f"{a}..{b}"
            inhibit_rows.append([row_src, [c, 0, rest_z[role][c]]])
        inh = math.ceil(tonic_mp / src_psp - EPS)
        inh_morph = f"{name}_{area}_inhibit_rest"
        plan.add_patterns(inh_morph, inhibit_rows)
        plan.add_rules(area, rest[role], [rule(inh_morph, -inh)])
        sizing["sources"].append(
            {
                "area": area,
                "role": role,
                "channel": c,
                "offset_rows": len(compiled["voxel_mappings"]),
                "coactive_z": rest_z[other][c],
                "inhibit_psc": -inh,
            }
        )
    plan.sizing[name] = sizing


def _bins_of(t: dict[str, Any], key: str, size: int) -> set[int]:
    """Bins from a list of integers or an inclusive ``"a..b"`` string, inside ``0..size-1``."""
    value = t.get(key)
    if isinstance(value, str) and ".." in value:
        lo, _, hi = value.partition("..")
        try:
            bins = set(range(int(lo), int(hi) + 1))
        except ValueError:
            bins = set()
    elif isinstance(value, list) and all(
        isinstance(v, int) and not isinstance(v, bool) for v in value
    ):
        bins = set(value)
    else:
        bins = set()
    if not bins or min(bins) < 0 or max(bins) >= size:
        raise SpecError(
            f"'{t.get('name', '?')}': '{key}' must be bins inside 0..{size - 1} "
            '(a list like [3, 4, 5] or "3..5")'
        )
    return bins


def _level(current: float, leak: float, accumulate: bool) -> float:
    """Steady-state membrane potential under a constant per-burst input ``current``.

    ``V <- V * (1 - leak) + I`` with accumulation gives ``I / leak`` (unbounded without leak);
    without accumulation the potential is the input of the burst itself.
    """
    if not accumulate:
        return current
    if leak > 0:
        return current / leak
    return math.copysign(math.inf, current) if current else 0.0


def _tpl_phase_window_gate(t: dict[str, Any], plan: Plan) -> None:
    """A gate that passes a pulse to ``target`` only while the phase is inside ``window``.

    ``pulse`` (and the optional tonic ``enable``) excite the gate area; every phase bin outside
    ``window`` inhibits it. Sized from the stated PSPs and checked, with ``V <- V (1 - leak) + I``
    and fire at ``V >= T``: enable alone < T; pulse alone < T when ``enable`` is used (>= T when
    not); enable + pulse >= T; enable + pulse + inhibition < T.
    """
    name = _name(t)
    pulse = _ref(t, "pulse")
    phase = _ref(t, "phase")
    target = _ref(t, "target")
    enable = _ref(t, "enable", required=False)
    assert pulse is not None and phase is not None and target is not None
    phase_bins = _inum(t, "phase_bins", minimum=2)
    window = _bins_of(t, "window", phase_bins)
    out_of_window = [b for b in range(phase_bins) if b not in window]
    if not out_of_window:
        raise SpecError(f"phase_window_gate '{name}': 'window' covers every phase bin")
    threshold = _fnum(t, "threshold", positive=True)
    leak = _fnum(t, "leak", 0.0, minimum=0.0)
    refractory = _inum(t, "refractory", 0)
    accumulate = bool(t.get("accumulate", False))
    gate_psp = _fnum(t, "psp", 1.0, positive=True)
    pulse_psc = _fnum(t, "pulse_psc", 1.0, positive=True)
    pulse_in = _fnum(t, "pulse_psp", 1.0, positive=True) * pulse_psc
    phase_psp = _fnum(t, "phase_psp", 1.0, positive=True)
    enable_in = 0.0
    enable_psc = 0.0
    if enable is not None:
        enable_psc = _fnum(t, "enable_psc", 1.0, positive=True)
        enable_in = _fnum(t, "enable_psp", 1.0, positive=True) * enable_psc
    # inhibition (a magnitude) that keeps level(enable - inhibition) + pulse below the threshold
    if not accumulate:
        need = enable_in + pulse_in - threshold
    elif leak > 0:
        need = enable_in + leak * (pulse_in - threshold)
    else:
        need = 0.0
    if t.get("inhibit_psc") is not None:
        inh_psc = abs(_fnum(t, "inhibit_psc"))
    else:
        inh_psc = float(max(1, math.ceil(need / phase_psp + EPS)))
    inhibition = phase_psp * inh_psc
    checks = {
        "enable_alone": _level(enable_in, leak, accumulate),
        "pulse_alone": pulse_in,
        "enable_plus_pulse": _level(enable_in, leak, accumulate) + pulse_in,
        "enable_plus_pulse_minus_inhibition": _level(enable_in - inhibition, leak, accumulate)
        + pulse_in,
    }
    problems: list[str] = []
    if enable is not None:
        if checks["enable_alone"] >= threshold - EPS:
            problems.append(
                f"enable alone reaches {checks['enable_alone']:g} >= threshold {threshold:g}"
                + ("" if leak > 0 or not accumulate else " (an accumulating gate needs leak > 0)")
            )
        if checks["pulse_alone"] >= threshold - EPS:
            problems.append(f"pulse alone gives {pulse_in:g} >= threshold {threshold:g}")
    elif pulse_in < threshold - EPS:
        problems.append(f"pulse alone gives {pulse_in:g}, below threshold {threshold:g}")
    if checks["enable_plus_pulse"] < threshold - EPS:
        problems.append(
            f"enable + pulse gives {checks['enable_plus_pulse']:g} < threshold {threshold:g}"
        )
    if checks["enable_plus_pulse_minus_inhibition"] >= threshold - EPS:
        problems.append(
            "enable + pulse - inhibition gives "
            f"{checks['enable_plus_pulse_minus_inhibition']:g} >= threshold {threshold:g} "
            f"(inhibition {inhibition:g})"
        )
    if problems:
        raise SpecError(f"phase_window_gate '{name}': " + "; ".join(problems))
    plan.add_area(name, [1, 1, 1], neuron_props(threshold, gate_psp, leak, refractory, accumulate))
    plan.add_rules(pulse, name, [rule("all_to_0-0-0", pulse_psc)])
    if enable is not None:
        plan.add_rules(enable, name, [rule("all_to_0-0-0", enable_psc)])
    inhibit_morph = f"{name}_out_of_window_inhibit"
    rows = []
    for a, b in _runs(out_of_window):
        rows.append([["*", "*", a if a == b else f"{a}..{b}"], [0, 0, 0]])
    plan.add_patterns(inhibit_morph, rows)
    plan.add_rules(phase, name, [rule(inhibit_morph, -inh_psc)])
    target_psc = _fnum(t, "target_psc", 1.0, positive=True)
    plan.add_rules(
        name, target, [rule(str(t.get("target_morphology", "0-0-0_to_all")), target_psc)]
    )
    plan.sizing[name] = {
        "template": "phase_window_gate",
        "threshold": threshold,
        "leak": leak,
        "accumulate": accumulate,
        "window_bins": sorted(window),
        "inhibited_bins": out_of_window,
        "inhibit_psc": -_clean(inh_psc),
        "inhibition": inhibition,
        "levels": {k: round(v, 6) for k, v in checks.items()},
        "model": "steady state of V <- V (1 - leak) + I; settling after a phase change ~ 1/leak",
    }


TEMPLATES: dict[str, Callable[[dict[str, Any], Plan], None]] = {
    "port": _tpl_port,
    "onset_pulse": _tpl_onset_pulse,
    "ring_cpg": _tpl_ring_cpg,
    "servo_channel_two_rest": _tpl_servo_two_rest,
    "phase_window_gate": _tpl_phase_window_gate,
}


# ------------------------------------------------------------------ expansion


def _expand_region(spec: dict[str, Any]) -> dict[str, Any] | None:
    region = spec.get("region")
    if region is None:
        return None
    if not isinstance(region, dict):
        raise SpecError("'region' must be an object")
    if region.get("region_id"):
        return {"region_id": str(region["region_id"])}
    title = region.get("title")
    c2, c3 = region.get("coordinates_2d"), region.get("coordinates_3d")
    if not isinstance(title, str) or not title.strip():
        raise SpecError("region needs 'title' (or an existing 'region_id')")
    if not (isinstance(c3, list) and len(c3) == 3):
        raise SpecError("region needs coordinates_3d [x, y, z]")
    if c2 is not None and not (isinstance(c2, list) and len(c2) == 2):
        raise SpecError("region coordinates_2d must be [x, y] (omit it to place after siblings)")
    out = {"title": title.strip(), "coordinates_2d": c2, "coordinates_3d": c3}
    if region.get("parent_region_id"):
        out["parent_region_id"] = str(region["parent_region_id"])
    return out


def _place(plan: Plan, spec: dict[str, Any]) -> None:
    defaults = spec.get("defaults") or {}
    origin = defaults.get("origin") or (plan.region or {}).get("coordinates_3d")
    step = int(defaults.get("step", DEFAULT_STEP))
    for i, area in enumerate(plan.areas):
        if area["position"] is not None:
            continue
        if not (isinstance(origin, list) and len(origin) == 3):
            raise SpecError(
                f"area '{area['name']}' has no position and there is no origin: give the "
                "area a 'position', or 'defaults.origin', or a new region with coordinates_3d"
            )
        area["position"] = [
            int(origin[0]) + (i % GRID_COLUMNS) * step,
            int(origin[1]) + (i // GRID_COLUMNS) * step,
            int(origin[2]),
        ]


def calls_for(plan: Plan) -> list[dict[str, Any]]:
    """The ordered client calls a real run makes (area references by name)."""
    calls: list[dict[str, Any]] = []
    if plan.region and "title" in plan.region:
        region_args = dict(plan.region)
        if region_args.get("coordinates_2d") is None:
            region_args["coordinates_2d"] = "<one step past the sibling regions>"
        calls.append({"call": "create_brain_region", "args": region_args})
    region_ref = (plan.region or {}).get("region_id", "<region_id from create_brain_region>")
    for a in plan.areas:
        calls.append(
            {
                "call": "create_cortical_area",
                "args": {
                    "name": a["name"],
                    "cortical_type": a["cortical_type"],
                    "dimensions": a["dimensions"],
                    "position": a["position"],
                    "neurons_per_voxel": a["neurons_per_voxel"],
                    "properties": a["properties"],
                    "brain_region_id": region_ref,
                },
            }
        )
    for a in plan.areas:
        if a["modulators"]:
            calls.append(
                {
                    "call": "update_cortical_area",
                    "args": {"area": a["name"], "updates": {"modulators": a["modulators"]}},
                }
            )
    for m in plan.morphologies:
        calls.append(
            {
                "call": "create_morphology",
                "args": {
                    "morphology_name": m["name"],
                    "morphology_type": m["type"],
                    "morphology_parameters": m["parameters"],
                },
            }
        )
    for e in plan.edits:
        calls.append(
            {
                "call": "update_cortical_area",
                "args": {"area": e["name"], "updates": e["properties"]},
            }
        )
    for src, dst in plan.deletions:
        calls.append(
            {"call": "delete_cortical_mapping", "args": {"src_area": src, "dst_area": dst}}
        )
    for mp in plan.mappings.values():
        calls.append(
            {
                "call": "update_cortical_mapping",
                "args": {
                    "src_area": mp["src"],
                    "dst_area": mp["dst"],
                    "mapping_rules": mp["rules"],
                    "replace": mp["replace"],
                },
            }
        )
        if mp["frozen"]:
            calls.append(
                {
                    "call": "set_mapping_plasticity_frozen",
                    "args": {"src_area": mp["src"], "dst_area": mp["dst"], "frozen": True},
                }
            )
    for i, c in enumerate(calls, start=1):
        c["n"] = i
    return calls


def expand_spec(spec: Any) -> tuple[dict[str, Any], Plan]:
    """Validate and expand a spec into ``(report, plan)``; errors come back in ``report``."""
    errors: list[str] = []
    plan = Plan()
    if not isinstance(spec, dict):
        return {"valid": False, "errors": ["spec must be a JSON object"], "warnings": []}, plan
    unknown = sorted(
        set(spec)
        - {
            "region",
            "defaults",
            "areas",
            "morphologies",
            "mappings",
            "templates",
            "delete",
            "edit_areas",
        }
    )
    if unknown:
        errors.append(f"unknown spec keys: {unknown}")
    try:
        plan.region = _expand_region(spec)
    except SpecError as e:
        errors.append(str(e))
    for t in spec.get("templates") or []:
        kind = t.get("template") if isinstance(t, dict) else None
        expander = TEMPLATES.get(kind) if isinstance(kind, str) else None
        if expander is None:
            errors.append(f"unknown template {kind!r}; known: {sorted(TEMPLATES)}")
            continue
        try:
            expander(t, plan)
        except SpecError as e:
            errors.append(str(e))
    try:
        for a in spec.get("areas") or []:
            dims = a.get("dimensions")
            if not (isinstance(a.get("name"), str) and isinstance(dims, list) and len(dims) == 3):
                raise SpecError(f"area {a!r} needs 'name' and 'dimensions' [x, y, z]")
            ctype = str(a.get("cortical_type", "CUSTOM")).upper()
            area_props = memory_properties(
                a["name"], ctype, a.get("properties") or {}, a.get("mp_encoding")
            )
            if ctype == "MEMORY" and "neuron_post_synaptic_potential" not in area_props:
                plan.warnings.append(MEMORY_PSP_DEFAULT_WARNING.format(name=a["name"]))
            plan.add_area(
                a["name"],
                dims,
                area_props,
                int(a.get("neurons_per_voxel", 1)),
                a.get("position"),
                ctype,
                a.get("modulators"),
            )
        for m in spec.get("morphologies") or []:
            plan.add_morphology(str(m.get("name")), str(m.get("type")), m.get("parameters"))
        for mp in spec.get("mappings") or []:
            if not (
                isinstance(mp.get("src"), str)
                and isinstance(mp.get("dst"), str)
                and isinstance(mp.get("rules"), list)
                and mp["rules"]
            ):
                raise SpecError(f"mapping {mp!r} needs 'src', 'dst' and a non-empty 'rules' list")
            plan.add_rules(
                mp["src"],
                mp["dst"],
                mp["rules"],
                bool(mp.get("replace", False)),
                mp.get("modulators"),
                bool(mp.get("frozen", False)),
            )
        for d in spec.get("delete") or []:
            if not (
                isinstance(d, dict)
                and isinstance(d.get("src"), str)
                and isinstance(d.get("dst"), str)
            ):
                raise SpecError(f"delete entry {d!r} needs 'src' and 'dst' area names")
            pair = (d["src"].strip(), d["dst"].strip())
            if pair in plan.deletions:
                raise SpecError(f"delete {pair[0]} -> {pair[1]} is listed twice")
            plan.deletions.append(pair)
        for item in spec.get("edit_areas") or []:
            props = item.get("properties") if isinstance(item, dict) else None
            if not (
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and isinstance(props, dict)
                and props
            ):
                raise SpecError(
                    f"edit_areas entry {item!r} needs 'name' and non-empty 'properties'"
                )
            if any(x["name"] == item["name"] for x in plan.edits):
                raise SpecError(f"edit_areas lists '{item['name']}' twice")
            plan.edits.append({"name": item["name"].strip(), "properties": dict(props)})
        if plan.edits and not (plan.region and plan.region.get("region_id")):
            raise SpecError(
                "edit_areas needs 'region': {region_id} of the region holding the areas"
            )
        check_memory_wiring(plan)
        _place(plan, spec)
    except (SpecError, AttributeError, TypeError) as e:
        errors.append(str(e))
    own = {a["name"] for a in plan.areas}
    morph_names = {m["name"] for m in plan.morphologies}
    touched = {n for pair in [*plan.mappings, *plan.deletions] for n in pair}
    touched.update(e["name"] for e in plan.edits)
    external = sorted(touched - own)
    if plan.areas and not plan.region:
        plan.warnings.append(
            "no 'region': areas need a parent region; the real run requires 'region'"
        )
    report = {
        "valid": not errors,
        "errors": errors,
        "warnings": plan.warnings,
        "summary": {
            "areas": len(plan.areas),
            "morphologies": len(morph_names),
            "mappings": len(plan.mappings),
            "deletions": len(plan.deletions),
            "edits": len(plan.edits),
        },
        "sizing": plan.sizing,
        "external": external,
        "calls": calls_for(plan) if not errors else [],
    }
    return report, plan


# ------------------------------------------------------------------ execution


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and ("error" in result or result.get("success") is False)


def _already_exists(result: Any) -> bool:
    text = f"{result.get('error', '')} {result.get('message', '')}".lower()
    return "409" in text or "already exists" in text


async def _confirm_region_2d(
    client: Any, region_id: str, requested: list[int], created: dict[str, Any]
) -> dict[str, Any]:
    """Compare the region's stored brain-map position with the requested one; fix a mismatch.

    The create answer carries ``coordinate_2d``. When it differs from the request (something
    between the spec and the genome moved the region) the region is updated once and re-read.
    """
    actual = created.get("coordinate_2d")
    out: dict[str, Any] = {"requested": requested, "actual": actual}
    if actual == requested:
        return out
    out["mismatch"] = True
    fixed = await client.update_brain_region(region_id, {"coordinate_2d": requested})
    out["update"] = "ok" if not _is_error(fixed) else fixed
    regions = await client.get_regions_members()
    entry = regions.get(region_id) if isinstance(regions, dict) else None
    out["after_update"] = entry.get("coordinate_2d") if isinstance(entry, dict) else None
    return out


async def execute_plan(client: Any, plan: Plan) -> dict[str, Any]:
    """Run a plan through the client's create and mapping paths, then verify it.

    Stops at the first failure and rolls back what this call created (its areas, then its
    region); morphologies stay and are listed. Returns ``{created, failed, verification}``
    plus ``rolled_back`` after a failure that had created something.
    """
    created: dict[str, Any] = {
        "region_id": None,
        "areas": {},
        "morphologies": [],
        "morphologies_reused": [],
        "mappings": [],
        "edits": [],
        "deleted_mappings": [],
        "frozen_mappings": [],
    }
    outcome = await _run_plan(client, plan, created)
    if outcome.get("failed") and (created["areas"] or created["region_id"]):
        outcome["rolled_back"] = await _rollback(client, plan, created)
    return outcome


async def _rollback(client: Any, plan: Plan, created: dict[str, Any]) -> dict[str, Any]:
    """Delete the areas (newest first) and then the region this call created."""
    errors: list[str] = []
    removed: list[str] = []
    for name, cid in reversed(list(created["areas"].items())):
        res = await client.delete_cortical_area(cid)
        if _is_error(res):
            errors.append(f"area {name}: {res.get('message') or res.get('error')}")
        else:
            removed.append(name)
    region_removed = False
    made_region = bool(plan.region and "title" in plan.region and created["region_id"])
    if made_region and not errors:
        res = await client.delete_brain_region(created["region_id"])
        if _is_error(res):
            errors.append(f"region: {res.get('message') or res.get('error')}")
        else:
            region_removed = True
    return {
        "areas_removed": removed,
        "region_removed": region_removed,
        "leftover_morphologies": list(created["morphologies"]),
        "errors": errors,
    }


async def _run_plan(client: Any, plan: Plan, created: dict[str, Any]) -> dict[str, Any]:
    from feagi_mcp.synapse_counts import edge_synapse_counts

    live = await client.get_cortical_id_name_mapping()
    if not isinstance(live, dict) or live.get("error"):
        return {"created": created, "failed": {"step": "read live areas", "detail": live}}
    by_name: dict[str, list[str]] = {}
    for cid, nm in live.items():
        if isinstance(nm, str):
            by_name.setdefault(nm.strip(), []).append(cid)
    conflicts = sorted(a["name"] for a in plan.areas if a["name"] in by_name)
    if conflicts:
        return {
            "created": created,
            "failed": {
                "step": "preflight",
                "error": "area names already exist",
                "names": conflicts,
            },
        }
    own = {a["name"] for a in plan.areas}
    ids: dict[str, str] = {}
    needed = [n for pair in [*plan.mappings, *plan.deletions] for n in pair]
    needed += [e["name"] for e in plan.edits]
    for n in needed:
        if n in own or n in ids:
            continue
        hits = by_name.get(n) or ([n] if n in live else [])
        if len(hits) != 1:
            return {
                "created": created,
                "failed": {
                    "step": "preflight",
                    "error": "external area not found or ambiguous",
                    "name": n,
                    "matches": len(hits),
                },
            }
        ids[n] = hits[0]
    for (src, dst), mp in plan.mappings.items():
        for r in mp["rules"]:
            morph = r["morphology_id"]
            bad_src = morph == "associative_memory" and src not in own
            bad_dst = morph == "episodic_memory" and dst not in own
            if (bad_src and not is_memory_cortical_id(ids[src])) or (
                bad_dst and not is_memory_cortical_id(ids[dst])
            ):
                return {
                    "created": created,
                    "failed": {
                        "step": "preflight",
                        "error": f"{morph} needs a MEMORY area at the "
                        f"{'source' if morph == 'associative_memory' else 'destination'}",
                        "mapping": f"{src} -> {dst}",
                    },
                }
    if plan.edits:
        regions = await client.get_regions_members()
        entry = (
            regions.get((plan.region or {}).get("region_id")) if isinstance(regions, dict) else None
        )
        members = set(entry.get("areas") or []) if isinstance(entry, dict) else None
        outside = [
            e["name"] for e in plan.edits if members is None or ids[e["name"]] not in members
        ]
        if outside:
            return {
                "created": created,
                "failed": {
                    "step": "preflight",
                    "error": "edit_areas names are not members of the region",
                    "names": outside,
                },
            }
    region_id = (plan.region or {}).get("region_id")
    if plan.region and "title" in plan.region:
        res = await client.create_brain_region(**plan.region)
        if _is_error(res) or not res.get("region_id"):
            return {"created": created, "failed": {"step": "create_brain_region", "detail": res}}
        region_id = res["region_id"]
        created["region_coordinates_2d"] = await _confirm_region_2d(
            client, region_id, plan.region["coordinates_2d"], res
        )
    created["region_id"] = region_id
    if plan.areas and not region_id:
        return {
            "created": created,
            "failed": {"step": "preflight", "error": "areas need a 'region' in the spec"},
        }
    for a in plan.areas:
        res = await client.create_cortical_area(
            name=a["name"],
            cortical_type=a["cortical_type"],
            dimensions=a["dimensions"],
            position=a["position"],
            neurons_per_voxel=a["neurons_per_voxel"],
            properties=a["properties"] or None,
            brain_region_id=region_id,
        )
        cid = res.get("cortical_id") if isinstance(res, dict) else None
        if cid:
            # record before any check so a rollback also removes an area created with a failure
            created["areas"][a["name"]] = cid
            ids[a["name"]] = cid
        if _is_error(res) or not cid:
            return {
                "created": created,
                "failed": {"step": f"create_cortical_area {a['name']}", "detail": res},
            }
        if a["cortical_type"] == "MEMORY" and not is_memory_cortical_id(cid):
            return {
                "created": created,
                "failed": {
                    "step": f"create_cortical_area {a['name']}",
                    "error": "MEMORY area got a non-memory id (decoded byte 0 must be 'm')",
                    "cortical_id": cid,
                },
            }
        rejected = res.get("rejected_properties")
        if rejected:
            return {
                "created": created,
                "failed": {"step": f"neuron properties of {a['name']}", "rejected": rejected},
            }
    for m in plan.morphologies:
        res = await client.create_morphology(m["name"], m["type"], m["parameters"])
        if _is_error(res):
            if _already_exists(res):
                created["morphologies_reused"].append(m["name"])
                continue
            return {
                "created": created,
                "failed": {"step": f"create_morphology {m['name']}", "detail": res},
            }
        created["morphologies"].append(m["name"])
    for e in plan.edits:
        res = await client.update_cortical_area(ids[e["name"]], e["properties"])
        if _is_error(res):
            return {
                "created": created,
                "failed": {"step": f"update_cortical_area {e['name']}", "detail": res},
            }
        created["edits"].append(e["name"])
    for a in plan.areas:
        if a["modulators"]:
            res = await client.update_cortical_area(ids[a["name"]], {"modulators": a["modulators"]})
            if _is_error(res):
                return {
                    "created": created,
                    "failed": {"step": f"set modulators of {a['name']}", "detail": res},
                }
    for src, dst in plan.deletions:
        res = await client.delete_cortical_mapping(ids[src], ids[dst])
        if _is_error(res):
            return {
                "created": created,
                "failed": {"step": f"delete_cortical_mapping {src} -> {dst}", "detail": res},
            }
        created["deleted_mappings"].append({"src": src, "dst": dst})
    for mp in plan.mappings.values():
        src_id, dst_id = ids[mp["src"]], ids[mp["dst"]]
        rules = list(mp["rules"])
        if not mp["replace"] and (mp["src"] not in own or mp["dst"] not in own):
            current = await client.get_cortical_mapping(src_id, dst_id)
            old = current.get("rules") if isinstance(current, dict) else None
            if isinstance(old, list):
                rules = [r for r in old if isinstance(r, dict)] + rules
        res = await client.update_cortical_mapping(src_id, dst_id, rules)
        if _is_error(res):
            return {
                "created": created,
                "failed": {
                    "step": f"update_cortical_mapping {mp['src']} -> {mp['dst']}",
                    "detail": res,
                },
            }
        if mp["frozen"]:
            frozen_step = f"freeze {mp['src']} -> {mp['dst']}"
            res = await client.set_mapping_plasticity_frozen(src_id, dst_id, True)
            if _is_error(res):
                return {"created": created, "failed": {"step": frozen_step, "detail": res}}
            read = await client.get_mapping_plasticity_frozen(src_id, dst_id)
            if _is_error(read) or not (isinstance(read, dict) and read.get("frozen") is True):
                return {"created": created, "failed": {"step": frozen_step, "detail": read}}
            created["frozen_mappings"].append({"src": mp["src"], "dst": mp["dst"]})
        created["mappings"].append({"src": mp["src"], "dst": mp["dst"], "rules": len(mp["rules"])})
    verification = await _verify(client, plan, ids, edge_synapse_counts)
    return {"created": created, "failed": None, "verification": verification}


async def _verify(client: Any, plan: Plan, ids: dict[str, str], count_fn: Any) -> dict[str, Any]:
    live = await client.get_cortical_id_name_mapping()
    live_ids = set(live) if isinstance(live, dict) else set()
    own_ids = {a["name"]: ids[a["name"]] for a in plan.areas if a["name"] in ids}
    cmap = await client.get_cortical_map_detailed()
    pairs = [(ids[m["src"]], ids[m["dst"]]) for m in plan.mappings.values()]

    counts, note = await count_fn(pairs, client.fetch_synapse_edges)
    rows = []
    zero = []
    for m in plan.mappings.values():
        key = (ids[m["src"]], ids[m["dst"]])
        found = None
        if isinstance(cmap, dict) and isinstance(cmap.get(key[0]), dict):
            found = len(cmap[key[0]].get(key[1]) or [])
        n = counts.get(key)
        rows.append(
            {
                "src": m["src"],
                "dst": m["dst"],
                "rules_expected": len(m["rules"]),
                "rules_found": found,
                "synapses": n,
            }
        )
        if n == 0:
            zero.append(f"{m['src']} -> {m['dst']}")
    out: dict[str, Any] = {
        "areas": {
            "expected": len(own_ids),
            "found": sum(1 for cid in own_ids.values() if cid in live_ids),
        },
        "mappings": rows,
        "zero_synapse": zero,
    }
    if note:
        out["synapse_count_note"] = note
    return out
