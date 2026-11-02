"""Pure genome helpers: prune unreferenced morphologies and read a genome file.

A genome stores mappings under ``blueprint["<area prefix>-cx-dstmap-d"]`` as
``{dst_cortical_id: [rule, ...]}`` where each rule names its ``morphology_id``. A region
export carries every morphology of the brain; :func:`prune_unreferenced_morphologies`
keeps only the ones the exported mappings use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from feagi_mcp.compact_views import area_name, compact_rule
from feagi_mcp.genome_artifact import decode_genome_artifact, encode_genome_artifact
from feagi_mcp.region_circuit import collect_member_areas

DSTMAP_KEY_MARKER = "dstmap-d"


def referenced_morphology_ids(genome: dict[str, Any]) -> set[str]:
    """Morphology ids named by any mapping rule in the genome blueprint."""
    names: set[str] = set()
    blueprint = genome.get("blueprint")
    if not isinstance(blueprint, dict):
        return names
    for key, dst_map in blueprint.items():
        if DSTMAP_KEY_MARKER not in str(key) or not isinstance(dst_map, dict):
            continue
        for rules in dst_map.values():
            if not isinstance(rules, list):
                continue
            for rule in rules:
                if isinstance(rule, dict) and isinstance(rule.get("morphology_id"), str):
                    names.add(rule["morphology_id"])
    return names


def entering_mappings(
    regions: dict[str, Any],
    cortical_map: dict[str, Any],
    geometry: dict[str, Any],
    region_id: str,
) -> list[dict[str, Any]]:
    """Mappings from areas outside the region subtree into its areas.

    A region export strips them (they live in the source areas' destination maps), so they
    must be re-created when the region is merged. Each row is
    ``{src, dst, src_id, dst_id, rules}`` with compact rules (``rule`` is the morphology id).

    Raises:
        KeyError: ``region_id`` is not a known region.
    """
    members, _ = collect_member_areas(regions, region_id.strip(), True)
    inside = set(members)
    rows: list[dict[str, Any]] = []
    for src_id in sorted(cortical_map):
        dst_map = cortical_map[src_id]
        if src_id in inside or not isinstance(dst_map, dict):
            continue
        for dst_id in sorted(dst_map):
            rules = dst_map[dst_id]
            if dst_id not in inside or not isinstance(rules, list) or not rules:
                continue
            rows.append(
                {
                    "src": area_name(geometry, src_id),
                    "dst": area_name(geometry, dst_id),
                    "src_id": src_id,
                    "dst_id": dst_id,
                    "rules": [compact_rule(r) for r in rules],
                }
            )
    return rows


def entering_morphology_ids(entering: list[dict[str, Any]]) -> set[str]:
    """Morphology ids named by the rules of ``entering_mappings`` rows."""
    return {r["rule"] for row in entering for r in row["rules"] if isinstance(r.get("rule"), str)}


def prune_unreferenced_morphologies(
    genome: dict[str, Any], extra_keep: set[str] | None = None
) -> tuple[dict[str, Any], int]:
    """Copy of ``genome`` whose ``neuron_morphologies`` holds only referenced morphologies.

    ``extra_keep`` names morphologies to keep besides those the exported mappings use
    (e.g. the ones of mappings entering a region export). Returns
    ``(genome, removed_count)``. A genome without a ``neuron_morphologies`` object is
    returned unchanged.
    """
    morphologies = genome.get("neuron_morphologies")
    if not isinstance(morphologies, dict):
        return genome, 0
    keep = referenced_morphology_ids(genome) | (extra_keep or set())
    pruned = {name: body for name, body in morphologies.items() if name in keep}
    out = dict(genome)
    out["neuron_morphologies"] = pruned
    return out, len(morphologies) - len(pruned)


def read_genome_file(file_path: str) -> dict[str, Any]:
    """Decode the genome JSON at ``file_path`` (``~`` expanded).

    Raises:
        ValueError: the path is missing, unreadable, or does not hold a JSON object.
    """
    path = Path(file_path).expanduser()
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ValueError(f"cannot read genome file {path}: {e.strerror or e}") from e
    try:
        return decode_genome_artifact(data)
    except ValueError as e:
        raise ValueError(f"genome file {path} is not a JSON object: {e}") from e


def summarize_genome(genome: dict[str, Any]) -> dict[str, Any]:
    """Short description of a genome: title, area, morphology and region counts."""
    blueprint = genome.get("blueprint")
    areas = (
        sum(1 for k in blueprint if str(k).endswith("__name-t"))
        if isinstance(blueprint, dict)
        else 0
    )
    morphologies = genome.get("neuron_morphologies")
    regions = genome.get("brain_regions")
    return {
        "genome_title": genome.get("genome_title"),
        "areas": areas,
        "morphologies": len(morphologies) if isinstance(morphologies, dict) else 0,
        "brain_regions": len(regions) if isinstance(regions, dict) else 0,
    }


def write_genome_file(genome: dict[str, Any], file_path: str) -> dict[str, Any]:
    """Write ``genome`` to ``file_path`` and return ``{file_path, bytes, summary}``."""
    path = Path(file_path).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = encode_genome_artifact(genome)
        path.write_bytes(data)
    except OSError as e:
        return {"error": f"cannot write genome file {path}: {e.strerror or e}"}
    return {
        "file_path": str(path.resolve()),
        "bytes": len(data),
        "summary": summarize_genome(genome),
    }
