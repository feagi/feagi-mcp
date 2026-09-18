"""Circuit (brain-region) naming policy for MCP.

In Brain Visualizer a "circuit" is a named brain region that holds cortical
areas — not a CUSTOM/MEMORY voxel block. Untitled genomes get a placeholder
region titled ``Autogen Circuit`` (see FEAGI ``autogen_subregion_display_name``).
MCP must not create regions with placeholder titles and must not parent new
CUSTOM/MEMORY areas (or clones) into those placeholders.

The title must name the circuit's function (Sit, Walk CPG, OR Gate), not the
tool, a UUID, or a generic container word.
"""

from __future__ import annotations

import re
from typing import Any

# Exact titles FEAGI or agents use as unnamed containers.
PLACEHOLDER_CIRCUIT_TITLES: frozenset[str] = frozenset(
    {
        "autogen circuit",
        "untitled",
        "untitled circuit",
        "new circuit",
        "new region",
        "circuit",
        "region",
        "custom circuit",
        "custom region",
        "mcp circuit",
        "default",
        "default circuit",
        "unnamed",
        "unnamed circuit",
        "placeholder",
    }
)

# If every token is in this set, the title does not name a function.
NON_FUNCTIONAL_WORDS: frozenset[str] = frozenset(
    {
        "autogen",
        "circuit",
        "region",
        "area",
        "custom",
        "test",
        "temp",
        "tmp",
        "new",
        "default",
        "untitled",
        "unnamed",
        "mcp",
        "feagi",
        "placeholder",
        "group",
        "container",
    }
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TOOL_PREFIX_RE = re.compile(r"^(mcp|feagi)", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[\s_\-]+")

CIRCUIT_NAMING_WORKFLOW = (
    "Call create_brain_region with a title that names the circuit function "
    "(e.g. Sit, Walk CPG, OR Gate), then pass that region_id as "
    "brain_region_id / parent_region_id. Do not parent areas into Autogen "
    "Circuit or Untitled."
)


def normalize_circuit_title(title: str) -> str:
    """Collapse surrounding and internal whitespace."""
    return " ".join(title.strip().split())


def _title_tokens(normalized: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT_RE.split(normalized.lower()) if token]


def validate_circuit_title(title: str) -> str | None:
    """Return an error if ``title`` is not a function-based circuit name.

    Args:
        title: Proposed brain-region display name.

    Returns:
        Error string, or ``None`` when the title is acceptable.
    """
    normalized = normalize_circuit_title(title)
    if not normalized:
        return (
            "circuit title must be non-empty and name the circuit function "
            f"(e.g. Sit, Walk CPG). {CIRCUIT_NAMING_WORKFLOW}"
        )
    if len(normalized) < 2:
        return (
            "circuit title must be at least 2 characters and name the function "
            f"(e.g. Sit, OR Gate). {CIRCUIT_NAMING_WORKFLOW}"
        )
    if _UUID_RE.fullmatch(normalized):
        return f"circuit title must name the function, not a UUID. {CIRCUIT_NAMING_WORKFLOW}"
    if _TOOL_PREFIX_RE.match(normalized):
        return (
            "circuit title must not start with Mcp or FEAGI; name the function "
            f"(e.g. Sit, Walk CPG). {CIRCUIT_NAMING_WORKFLOW}"
        )
    folded = normalized.lower()
    if folded in PLACEHOLDER_CIRCUIT_TITLES:
        return (
            f"circuit title '{normalized}' is a placeholder (Autogen Circuit / "
            f"Untitled / generic container). {CIRCUIT_NAMING_WORKFLOW}"
        )
    tokens = _title_tokens(normalized)
    if tokens and all(token in NON_FUNCTIONAL_WORDS for token in tokens):
        return f"circuit title '{normalized}' does not name a function. {CIRCUIT_NAMING_WORKFLOW}"
    if not any(character.isalpha() for character in normalized):
        return (
            "circuit title must include a letter so it names the function. "
            f"{CIRCUIT_NAMING_WORKFLOW}"
        )
    return None


def extract_region_title(regions_members: dict[str, Any], region_id: str) -> str | None:
    """Return the region's ``title`` from a ``regions_members`` payload.

    Args:
        regions_members: Flat ``region_id`` → region dict from FEAGI.
        region_id: Parent brain-region UUID.

    Returns:
        Stripped title, or ``None`` if the region or ``title`` field is missing.
    """
    raw = regions_members.get(region_id.strip())
    if not isinstance(raw, dict):
        return None
    title = raw.get("title")
    if not isinstance(title, str):
        return None
    stripped = title.strip()
    if not stripped:
        return None
    return stripped


def parent_circuit_naming_error(title: str | None, region_id: str) -> str | None:
    """Return an error if the parent region is missing or has a placeholder title.

    Args:
        title: Display title looked up from ``get_brain_regions``, or ``None``.
        region_id: Parent brain-region UUID the agent supplied.

    Returns:
        Error string, or ``None`` when the parent is a functionally named circuit.
    """
    rid = region_id.strip()
    if title is None:
        return f"brain_region_id {rid} was not found as a titled region. {CIRCUIT_NAMING_WORKFLOW}"
    title_error = validate_circuit_title(title)
    if title_error is None:
        return None
    return (
        f"parent region {rid} is titled '{title}', which is not a functional "
        f"circuit name. {CIRCUIT_NAMING_WORKFLOW}"
    )
