"""Exact synapse counts per mapping from realized synapse edges.

``GET /v1/connectome/{id}/synapses[/incoming]`` returns edges with neuron ids only (no
target area), but neuron ids are global. The synapses of the mapping ``src -> dst`` are the
outgoing edges of ``src`` whose target is a neuron that receives input in ``dst``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

# Above this many listed edges the pair counting is skipped (the lists are fetched whole).
MAX_EDGES_LISTED = 200_000


def count_edges_between(outgoing_src: list[Any], incoming_dst: list[Any]) -> int:
    """Synapses from the source area into the destination area."""
    targets = {e.get("target_neuron_id") for e in incoming_dst if isinstance(e, dict)}
    return sum(
        1 for e in outgoing_src if isinstance(e, dict) and e.get("target_neuron_id") in targets
    )


async def edge_synapse_counts(
    pairs: list[tuple[str, str]],
    fetch_edges: Callable[[str, str], Awaitable[list[Any] | None]],
) -> tuple[dict[tuple[str, str], int | None], str | None]:
    """Synapse count for each ``(src_id, dst_id)`` pair.

    ``fetch_edges(area_id, "outgoing" | "incoming")`` returns the raw edge list, or None when
    it cannot be read. Each area list is fetched once. Returns ``(counts, note)``; a pair that
    cannot be counted maps to None, and ``note`` says why the counting stopped early.
    """
    out_ids = sorted({s for s, _ in pairs})
    in_ids = sorted({d for _, d in pairs})
    out_lists, in_lists = await asyncio.gather(
        asyncio.gather(*(fetch_edges(a, "outgoing") for a in out_ids)),
        asyncio.gather(*(fetch_edges(a, "incoming") for a in in_ids)),
    )
    outgoing = dict(zip(out_ids, out_lists, strict=True))
    incoming = dict(zip(in_ids, in_lists, strict=True))
    total = sum(len(v) for v in outgoing.values() if v) + sum(
        len(v) for v in incoming.values() if v
    )
    if total > MAX_EDGES_LISTED:
        return dict.fromkeys(pairs), f"skipped: {total} listed edges exceed {MAX_EDGES_LISTED}"
    counts: dict[tuple[str, str], int | None] = {}
    for src, dst in pairs:
        o, i = outgoing.get(src), incoming.get(dst)
        counts[(src, dst)] = None if o is None or i is None else count_edges_between(o, i)
    return counts, None
