"""Deterministic FEAGI connectivity-rule authoring and validation.

Agents must call :func:`build_connectivity_proposal` before creating a custom
morphology. Enumerating exact voxel pairs for a regular transform is a judgment
error: FEAGI already has a per-axis pattern language and core vector rules.

Source of truth for expansion semantics:
``feagi-core/crates/feagi-brain-development/src/connectivity/pattern-connectivity-rules.md``
"""

from __future__ import annotations

import re
from typing import Any

from feagi_mcp.cortical_id_decode import decode_cortical_id_interpretation

# Reject exact-coordinate dumps once this many pairs collapse to one compact form.
ENUMERATED_PATTERN_REJECT_THRESHOLD = 8

DEST_KIND_CUSTOM = "custom"
DEST_KIND_POS_SERVO_ABS = "positional_servo_absolute"
DEST_KIND_POS_SERVO_INC = "positional_servo_incremental"
DEST_KIND_POS_SERVO_SPEED = "positional_servo_speed"

_OFFSET_RE = re.compile(r"^\?[+-]\d+$")
_RANGE_RE = re.compile(r"^\?[+-]\d+:\?[+-]\d+$")
_ABS_RANGE_RE = re.compile(r"^-?\d+\.\.-?\d+$")

# Tokens that select a construction. Overlap is resolved by the first matching
# branch in :func:`build_connectivity_proposal` (motor/command before offset).
_TOKENS_IDENTITY = frozenset(
    {"identity", "topographic", "one-to-one", "onetoone", "preserve", "block"}
)
_TOKENS_OFFSET = frozenset(
    {"shift", "offset", "shifter", "translate", "lateral", "z-shifter", "zshifter"}
)
_TOKENS_BROADCAST = frozenset({"broadcast", "fanout", "projector", "project", "power"})
_TOKENS_DENSE = frozenset({"dense", "all-to-all", "alltoall", "fully", "global"})
_TOKENS_MOTOR_COMMAND = frozenset(
    {
        "sit",
        "flexion",
        "flex",
        "extension",
        "extend",
        "muscle",
        "motor",
        "command",
        "excitation",
        "excite",
        "opu",
        "servo",
    }
)
_TOKENS_MAX_CMD = frozenset({"max", "full", "strongest", "peak"})
_TOKENS_MIN_CMD = frozenset({"min", "off", "silent"})

PATTERN_LANGUAGE: dict[str, Any] = {
    "rule_shape": "[src_x, src_y, src_z] -> [dst_x, dst_y, dst_z]",
    "absolute": [
        {"syntax": "*", "name": "Wildcard", "meaning": "All coordinates on this axis"},
        {"syntax": "N", "name": "Exact", "meaning": "Only coordinate N"},
        {
            "syntax": "N..M",
            "name": "Absolute range",
            "meaning": "Coordinates N through M inclusive (source filter or dest span)",
        },
    ],
    "source_relative": [
        {"syntax": "?", "name": "Pass-through", "meaning": "Same coordinate as the source neuron"},
        {"syntax": "!", "name": "Exclude", "meaning": "All coordinates except the source's"},
        {
            "syntax": "?+",
            "name": "Direction positive",
            "meaning": "All coordinates strictly greater than source",
        },
        {
            "syntax": "?-",
            "name": "Direction negative",
            "meaning": "All coordinates strictly less than source",
        },
        {
            "syntax": "?+=",
            "name": "Direction positive inclusive",
            "meaning": "All coordinates greater than or equal to source",
        },
        {
            "syntax": "?-=",
            "name": "Direction negative inclusive",
            "meaning": "All coordinates less than or equal to source",
        },
        {
            "syntax": "?+N",
            "name": "Offset positive",
            "meaning": "Single coordinate at source + N",
        },
        {
            "syntax": "?-N",
            "name": "Offset negative",
            "meaning": "Single coordinate at source - N",
        },
        {
            "syntax": "?-A:?+B",
            "name": "Range",
            "meaning": "All coordinates from source-A to source+B (inclusive)",
        },
    ],
    "constraints": [
        (
            "Source-side relative tokens (?, !, ?+, relative ranges) do not filter; "
            "only *, exact integers, and N..M filter sources."
        ),
        (
            "Offset (?+N, ?-N), relative range (?-A:?+B), and absolute range (N..M) "
            "are genome JSON strings. FFI integers cannot express them."
        ),
        (
            "Unknown pattern strings must not be sent. FEAGI treats unrecognized "
            "strings as *, which silently over-connects."
        ),
        "Do not enumerate exact (x,y,z) pairs for a regular transform. Use * / ? / ?+N.",
        (
            "Prefer an existing core morphology (block_to_block, projector, "
            "lateral_+z, all_to_all) when it already expresses the intent."
        ),
    ],
}

POSITIONAL_SERVO_DECODE: dict[str, Any] = {
    "layout": (
        "X is device channel, Y is 1, Z is command depth (absolute area is 1-wide per channel)."
    ),
    "linear_unsigned": (
        "z=0 decodes to maximum command (1.0). z=depth-1 decodes to near-zero. "
        "Multiple firing Z voxels are averaged, then flipped: "
        "value = 1 - mean(z)/(depth-1)."
    ),
    "do_not": (
        "Do not map babble/command sources to high destination Z (for example ?+17) "
        "when the destination is a PositionalServo OPU. That yields ~0.05 excitation "
        "if z=17,18,19 all fire in a depth-20 strip."
    ),
    "max_command_pattern": [["*", "*", "*"], ["?", "?", 0]],
    "channel_subset_pattern": [[0, "*", "*"], ["?", "?", 0]],
    "channel_range_pattern": [["1..98", "*", "*"], ["?", "?", 0]],
}


def normalize_intent_tokens(intent: str) -> set[str]:
    """Normalize natural-language intent into lowercase alphanumeric tokens."""
    return {tok for tok in re.split(r"[^a-z0-9+\-]+", intent.lower()) if tok}


def dest_kind_from_cortical_id(cortical_id: str | None) -> str:
    """Classify a destination area from its 8-byte cortical id (local, no HTTP)."""
    if not cortical_id or not str(cortical_id).strip():
        return DEST_KIND_CUSTOM
    decoded = decode_cortical_id_interpretation(str(cortical_id).strip())
    if not decoded.get("ok"):
        return DEST_KIND_CUSTOM
    subtype = str(decoded.get("subtype_4char") or "")
    if subtype != "opse":
        return DEST_KIND_CUSTOM
    subunit = int(decoded.get("cortical_subunit_index") or 0)
    if subunit == 1:
        return DEST_KIND_POS_SERVO_INC
    if subunit == 2:
        return DEST_KIND_POS_SERVO_SPEED
    return DEST_KIND_POS_SERVO_ABS


def is_positional_servo_absolute(dest_kind: str) -> bool:
    """True when destination is the absolute PositionalServo command strip."""
    return dest_kind == DEST_KIND_POS_SERVO_ABS


def validate_pattern_element(value: Any) -> str | None:
    """Return an error string if ``value`` is not a legal pattern token."""
    if isinstance(value, bool):
        return "boolean is not a pattern token"
    if isinstance(value, int):
        return None
    if isinstance(value, float) and value.is_integer():
        return None
    if not isinstance(value, str):
        return f"unsupported pattern token type {type(value).__name__}"
    token = value.strip()
    if token in {"*", "?", "!", "?+", "?-", "?+=", "?-="}:
        return None
    if _OFFSET_RE.fullmatch(token) or _RANGE_RE.fullmatch(token) or _ABS_RANGE_RE.fullmatch(token):
        return None
    if re.fullmatch(r"-?\d+", token):
        return None
    return f"unknown pattern token {value!r}; FEAGI would silently treat this as *"


def validate_pattern_triple(triple: Any, label: str) -> list[str]:
    """Validate one [x, y, z] pattern side."""
    if not isinstance(triple, list) or len(triple) != 3:
        return [f"{label} must be a list of 3 pattern tokens"]
    errors: list[str] = []
    for axis, token in zip(("x", "y", "z"), triple, strict=True):
        err = validate_pattern_element(token)
        if err is not None:
            errors.append(f"{label}.{axis}: {err}")
    return errors


def _as_int(value: Any) -> int | None:
    """Return int if ``value`` is an exact coordinate, otherwise None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def _pattern_pair(entry: Any) -> tuple[list[Any], list[Any]] | None:
    """Extract [src, dst] from a patterns-morphology row."""
    if not isinstance(entry, list) or len(entry) != 2:
        return None
    src, dst = entry
    if not isinstance(src, list) or not isinstance(dst, list):
        return None
    if len(src) != 3 or len(dst) != 3:
        return None
    return src, dst


def analyze_patterns(patterns: Any) -> dict[str, Any]:
    """Validate pattern rows and detect compactable exact-coordinate dumps.

    Returns ``ok``, ``errors``, ``warnings``, and when a dump collapses,
    ``compact_form`` plus ``reject`` True.
    """
    result: dict[str, Any] = {
        "ok": False,
        "errors": [],
        "warnings": [],
        "reject": False,
        "compact_form": None,
        "pattern_count": 0,
    }
    if not isinstance(patterns, list) or not patterns:
        result["errors"].append("patterns must be a non-empty list of [src, dst] pairs")
        return result

    offsets: list[tuple[int, int, int]] = []
    unique_src_x: set[int] = set()
    all_exact = True
    for idx, row in enumerate(patterns):
        pair = _pattern_pair(row)
        if pair is None:
            result["errors"].append(
                f"patterns[{idx}] must be [[src_x, src_y, src_z], [dst_x, dst_y, dst_z]]"
            )
            continue
        src, dst = pair
        result["errors"].extend(validate_pattern_triple(src, f"patterns[{idx}].src"))
        result["errors"].extend(validate_pattern_triple(dst, f"patterns[{idx}].dst"))
        src_nums = [_as_int(v) for v in src]
        dst_nums = [_as_int(v) for v in dst]
        if any(v is None for v in src_nums + dst_nums):
            all_exact = False
            continue
        assert src_nums[0] is not None and dst_nums[0] is not None
        assert src_nums[1] is not None and dst_nums[1] is not None
        assert src_nums[2] is not None and dst_nums[2] is not None
        offsets.append(
            (
                dst_nums[0] - src_nums[0],
                dst_nums[1] - src_nums[1],
                dst_nums[2] - src_nums[2],
            )
        )
        unique_src_x.add(src_nums[0])

    result["pattern_count"] = len(patterns)
    if result["errors"]:
        result["reject"] = True
        return result

    result["ok"] = True
    if (
        all_exact
        and len(offsets) >= ENUMERATED_PATTERN_REJECT_THRESHOLD
        and offsets
        and all(off == offsets[0] for off in offsets)
    ):
        dx, dy, dz = offsets[0]
        compact_patterns = [
            [
                [_source_x_filter_token(lo, hi), "*", "*"],
                [_relative_token(dx), _relative_token(dy), _relative_token(dz)],
            ]
            for lo, hi in _contiguous_int_runs(sorted(unique_src_x))
        ]
        reason = (
            f"all {len(offsets)} pairs share offset ({dx},{dy},{dz}) on "
            f"{len(unique_src_x)} source X channels; collapse contiguous X into N..M. "
            "Do not use ['*', '*', '*'] unless every channel in the area should connect"
        )
        result["compact_form"] = {
            "type": "patterns",
            "parameters": {"patterns": compact_patterns},
            "reason": reason,
        }
        result["reject"] = True
        result["ok"] = False
        result["errors"].append(
            "enumerated exact voxel pairs are not a valid way to express a regular "
            f"transform ({reason})"
        )
        return result

    source_x_compact = compact_source_x_filter_patterns(patterns)
    if source_x_compact is not None and len(patterns) >= ENUMERATED_PATTERN_REJECT_THRESHOLD:
        reason = (
            f"{len(patterns)} source-X filter rows collapse to "
            f"{len(source_x_compact)} exact/N..M rows; use absolute ranges"
        )
        result["compact_form"] = {
            "type": "patterns",
            "parameters": {"patterns": source_x_compact},
            "reason": reason,
        }
        result["reject"] = True
        result["ok"] = False
        result["errors"].append(
            "enumerated per-channel source-X rows are not a valid way to express "
            f"contiguous filters ({reason})"
        )
    return result


def _contiguous_int_runs(values: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted unique integers into inclusive [lo, hi] runs."""
    if not values:
        return []
    ordered = sorted(set(values))
    runs: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        runs.append((start, prev))
        start = prev = value
    runs.append((start, prev))
    return runs


def _source_x_filter_token(lo: int, hi: int) -> int | str:
    """Exact X when lo==hi, otherwise the absolute range token ``N..M``."""
    if lo == hi:
        return lo
    return f"{lo}..{hi}"


def _expand_abs_x_token(token: Any) -> list[int] | None:
    """Expand an exact X or ``N..M`` token into inclusive integers."""
    exact = _as_int(token)
    if exact is not None:
        return [exact]
    if not isinstance(token, str):
        return None
    stripped = token.strip()
    match = _ABS_RANGE_RE.fullmatch(stripped)
    if match is None:
        return None
    lo_s, hi_s = stripped.split("..", 1)
    lo_i, hi_i = int(lo_s), int(hi_s)
    if lo_i > hi_i:
        return []
    return list(range(lo_i, hi_i + 1))


def _token_fingerprint(value: Any) -> tuple[str, Any]:
    """Stable group key for a pattern token."""
    exact = _as_int(value)
    if exact is not None:
        return ("i", exact)
    if isinstance(value, str):
        return ("s", value.strip())
    return ("o", repr(value))


def compact_source_x_filter_patterns(patterns: Any) -> list[list[Any]] | None:
    """Collapse ``[[X, y, z], dest]`` rows that share y/z/dest into ``N..M``.

    ``X`` may be an exact integer or an existing ``N..M`` token. Returns a new
    list when at least one run was merged; otherwise ``None``.
    """
    if not isinstance(patterns, list) or not patterns:
        return None

    leftovers: list[list[Any]] = []
    groups: dict[tuple[Any, ...], list[int]] = {}
    group_meta: dict[tuple[Any, ...], tuple[Any, Any, list[Any]]] = {}

    for row in patterns:
        pair = _pattern_pair(row)
        if pair is None:
            leftovers.append(row if isinstance(row, list) else [row])
            continue
        src, dst = pair
        xs = _expand_abs_x_token(src[0])
        if xs is None:
            leftovers.append([src, dst])
            continue
        key = (
            _token_fingerprint(src[1]),
            _token_fingerprint(src[2]),
            _token_fingerprint(dst[0]),
            _token_fingerprint(dst[1]),
            _token_fingerprint(dst[2]),
        )
        groups.setdefault(key, []).extend(xs)
        group_meta[key] = (src[1], src[2], dst)

    compacted: list[list[Any]] = []
    for key, xs in groups.items():
        src_y, src_z, dst = group_meta[key]
        for lo, hi in _contiguous_int_runs(xs):
            compacted.append([[_source_x_filter_token(lo, hi), src_y, src_z], dst])

    result = leftovers + compacted
    if len(result) >= len(patterns):
        return None
    return result


def _relative_token(delta: int) -> Any:
    """Encode a constant axis offset as `?`, `?+N`, or `?-N`."""
    if delta > 0:
        return f"?+{delta}"
    if delta < 0:
        return f"?{delta}"
    return "?"


def validate_morphology_parameters(morphology_type: str, parameters: Any) -> dict[str, Any]:
    """Validate create_morphology parameters. Patterns are judged for compactness."""
    if not isinstance(parameters, dict):
        return {
            "ok": False,
            "reject": True,
            "errors": ["morphology_parameters must be an object"],
            "warnings": [],
            "compact_form": None,
        }
    kind = morphology_type.strip().lower()
    if kind == "patterns":
        return analyze_patterns(parameters.get("patterns"))
    if kind == "vectors":
        vectors = parameters.get("vectors")
        if not isinstance(vectors, list) or not vectors:
            return {
                "ok": False,
                "reject": True,
                "errors": ["vectors must be a non-empty list of [dx, dy, dz]"],
                "warnings": [],
                "compact_form": None,
            }
        errors: list[str] = []
        for idx, vec in enumerate(vectors):
            if not isinstance(vec, list) or len(vec) != 3:
                errors.append(f"vectors[{idx}] must be [dx, dy, dz]")
                continue
            if any(_as_int(v) is None for v in vec):
                errors.append(f"vectors[{idx}] must be three integers")
        return {
            "ok": not errors,
            "reject": bool(errors),
            "errors": errors,
            "warnings": [],
            "compact_form": None,
        }
    return {"ok": True, "reject": False, "errors": [], "warnings": [], "compact_form": None}


def motor_z_errors_for_patterns(patterns: Any, dest_kind: str) -> list[str]:
    """Reject high-Z exact / offset dest tokens on a PositionalServo absolute OPU."""
    if not is_positional_servo_absolute(dest_kind):
        return []
    errors: list[str] = []
    if not isinstance(patterns, list):
        return errors
    for idx, row in enumerate(patterns):
        pair = _pattern_pair(row)
        if pair is None:
            continue
        _src, dst = pair
        dest_z = dst[2]
        dest_z_int = _as_int(dest_z)
        if dest_z_int is not None and dest_z_int > 0:
            errors.append(
                f"patterns[{idx}].dst.z={dest_z_int} on a PositionalServo absolute OPU "
                "decodes as a weak command (z=0 is max). Use dest z=0."
            )
        if isinstance(dest_z, str) and dest_z.strip().startswith("?+") and dest_z.strip() != "?+":
            errors.append(
                f"patterns[{idx}].dst.z={dest_z!r} shifts command away from z=0 "
                "on a PositionalServo absolute OPU. Use 0, not ?+N."
            )
    return errors


def build_connectivity_proposal(
    intent: str,
    *,
    src_dimensions: list[int] | None = None,
    dst_dimensions: list[int] | None = None,
    dest_kind: str = DEST_KIND_CUSTOM,
    source_x_channels: list[int] | None = None,
    z_offset: int | None = None,
) -> dict[str, Any]:
    """Return a reuse-or-author plan for one src->dst mapping intent.

    Local only. Does not guess missing channel lists or invert motor Z.
    """
    tokens = normalize_intent_tokens(intent)
    payload: dict[str, Any] = {
        "intent": intent,
        "tokens": sorted(tokens),
        "src_dimensions": src_dimensions,
        "dst_dimensions": dst_dimensions,
        "dest_kind": dest_kind,
        "pattern_language": PATTERN_LANGUAGE,
        "reuse": None,
        "custom": None,
        "do_not": [
            "Do not expand a regular transform into hundreds of exact voxel pairs.",
            "Do not invent even/odd or modulo filters; the pattern language has no modulo.",
        ],
        "error": None,
    }
    if is_positional_servo_absolute(dest_kind):
        payload["motor_decode"] = POSITIONAL_SERVO_DECODE
        payload["do_not"].append(POSITIONAL_SERVO_DECODE["do_not"])

    if not tokens:
        payload["error"] = "intent must contain alphanumeric tokens"
        return payload

    channels = _unique_nonneg_ints(source_x_channels)

    if tokens & _TOKENS_MOTOR_COMMAND or (
        is_positional_servo_absolute(dest_kind) and (tokens & _TOKENS_MAX_CMD)
    ):
        if is_positional_servo_absolute(dest_kind) and z_offset is not None and z_offset != 0:
            payload["error"] = (
                "z_offset is inverted on a PositionalServo absolute OPU; "
                "max command is dest z=0, not source+N"
            )
            return payload
        dest_z = 0
        if tokens & _TOKENS_MIN_CMD and not (tokens & _TOKENS_MAX_CMD):
            if dst_dimensions and len(dst_dimensions) == 3:
                dest_z = int(dst_dimensions[2]) - 1
            else:
                payload["error"] = "min command on a motor OPU requires dst_dimensions[2]"
                return payload
        if channels:
            patterns = [
                [[_source_x_filter_token(lo, hi), "*", "*"], ["?", "?", dest_z]]
                for lo, hi in _contiguous_int_runs(channels)
            ]
            payload["custom"] = {
                "type": "patterns",
                "parameters": {"patterns": patterns},
                "rationale": (
                    "Source X uses exact N or N..M for contiguous channels; dest Z is "
                    f"the linear command bin ({dest_z}; 0 is max on PositionalServo)."
                ),
            }
            return payload
        if is_positional_servo_absolute(dest_kind):
            payload["error"] = (
                "source_x_channels is required for a subset motor/sit mapping; "
                "refusing to wildcard every muscle channel"
            )
            payload["full_area_form"] = {
                "type": "patterns",
                "parameters": {"patterns": [[["*", "*", "*"], ["?", "?", dest_z]]]},
                "rationale": "Only if every destination channel should receive this command.",
            }
            return payload
        payload["custom"] = {
            "type": "patterns",
            "parameters": {"patterns": [[["*", "*", "*"], ["?", "?", dest_z]]]},
            "rationale": "Topographic map onto dest Z command bin for a non-OPU destination.",
        }
        return payload

    if tokens & _TOKENS_IDENTITY:
        payload["reuse"] = {
            "morphology_id": "block_to_block",
            "why": "Core vector [0,0,0] is identity when dimensions are compatible.",
        }
        payload["custom"] = {
            "type": "patterns",
            "parameters": {"patterns": [[["*", "*", "*"], ["?", "?", "?"]]]},
            "rationale": "Equivalent identity using pass-through tokens.",
        }
        return payload

    if tokens & _TOKENS_OFFSET:
        if is_positional_servo_absolute(dest_kind):
            payload["error"] = (
                "A Z offset toward a PositionalServo absolute OPU weakens or inverts "
                "the command. Use dest z=0 (and source_x_channels for a subset)."
            )
            return payload
        if z_offset is None:
            payload["error"] = "z_offset is required for a shift/offset intent"
            return payload
        z_token = f"?+{z_offset}" if z_offset > 0 else (f"?{z_offset}" if z_offset < 0 else "?")
        payload["reuse"] = None
        if z_offset == 1:
            payload["reuse"] = {
                "morphology_id": "lateral_+z",
                "why": "Core vector [0,0,1] already is +Z shift.",
            }
        elif z_offset == -1:
            payload["reuse"] = {
                "morphology_id": "lateral_-z",
                "why": "Core vector [0,0,-1] already is -Z shift.",
            }
        payload["custom"] = {
            "type": "vectors",
            "parameters": {"vectors": [[0, 0, z_offset]]},
            "pattern_equivalent": {
                "type": "patterns",
                "parameters": {"patterns": [[["*", "*", "*"], ["?", "?", z_token]]]},
            },
            "rationale": "One vector/offset rule; do not list every source voxel.",
        }
        return payload

    if tokens & _TOKENS_BROADCAST:
        payload["reuse"] = {
            "morphology_id": "projector",
            "why": "Core projector maps a source volume into the destination volume.",
        }
        if src_dimensions == [1, 1, 1]:
            payload["reuse"] = {
                "morphology_id": "0-0-0_to_all",
                "why": "Single source voxel broadcasting into the destination.",
            }
        return payload

    if tokens & _TOKENS_DENSE:
        payload["reuse"] = {
            "morphology_id": "all_to_all",
            "why": "Core all-to-all is the dense coupling rule.",
        }
        return payload

    payload["error"] = (
        "No construction matched the intent. Use identity, offset+z_offset, "
        "broadcast, dense, or motor/sit with source_x_channels."
    )
    return payload


def _unique_nonneg_ints(values: list[int] | None) -> list[int]:
    """Deduplicate non-negative channel indices, preserving sorted order."""
    if not values:
        return []
    seen: set[int] = set()
    out: list[int] = []
    for raw in values:
        if isinstance(raw, bool):
            continue
        if not isinstance(raw, int) or raw < 0:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        out.append(raw)
    out.sort()
    return out


def proposal_to_create_payload(proposal: dict[str, Any]) -> dict[str, Any] | None:
    """Extract morphology type/parameters from a successful custom proposal."""
    custom = proposal.get("custom")
    if not isinstance(custom, dict):
        return None
    morph_type = custom.get("type")
    params = custom.get("parameters")
    if not isinstance(morph_type, str) or not isinstance(params, dict):
        return None
    return {"morphology_type": morph_type, "morphology_parameters": params}
