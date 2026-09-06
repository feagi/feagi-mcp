#!/usr/bin/env python3
"""Reproduce amalgamation host-vs-guest cortical ID overlap (debug aid).

Steps (requires a running feagi-api HTTP server):
  1. POST base genome JSON to /v1/genome/upload
  2. POST guest genome to /v1/genome/amalgamation_by_payload
  3. GET /v1/system/health_check (amalgamation_pending)
  4. POST /v1/genome/amalgamation_destination with origin + brain_region_id

Environment:
  FEAGI_HOST (default 127.0.0.1), FEAGI_PORT (default 8000)

Example:
  python scripts/reproduce_amalgamation_debug.py \\
    --base /path/to/scan-angle.genome \\
    --guest /path/to/curve-detection.genome \\
    --origin 0 -350 0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx


def _cortical_ids_from_blueprint_v3(genome: dict) -> set[str]:
    """Extract unique cortical area ids from flat blueprint keys (one __name-t row per area)."""
    bp = genome.get("blueprint") or {}
    ids: set[str] = set()
    prefix = "_____10c-"
    marker = "=-cx-"
    for key in bp:
        if not key.startswith(prefix) or "__name-t" not in key:
            continue
        rest = key[len(prefix) :]
        if marker not in rest:
            continue
        cid = rest.split(marker, 1)[0]
        ids.add(cid)
    return ids


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, required=True, help="Host .genome file")
    p.add_argument("--guest", type=Path, required=True, help="Genome to amalgamate")
    p.add_argument("--origin", nargs=3, type=int, default=[0, -350, 0], help="circuit_origin x y z")
    p.add_argument("--rewire", default="rewire_all")
    args = p.parse_args()
    for genome_path in (args.base, args.guest):
        if genome_path.suffix.lower() != ".genome":
            p.error(f"Genome files must use the .genome extension: {genome_path}")

    host = os.environ.get("FEAGI_HOST", "127.0.0.1")
    port = os.environ.get("FEAGI_PORT", "8000")
    base_url = f"http://{host}:{port}"

    base_obj = json.loads(args.base.read_text(encoding="utf-8"))
    guest_obj = json.loads(args.guest.read_text(encoding="utf-8"))

    base_ids = _cortical_ids_from_blueprint_v3(base_obj)
    guest_ids = _cortical_ids_from_blueprint_v3(guest_obj)
    overlap = base_ids & guest_ids
    only_guest = guest_ids - base_ids

    print("--- ID overlap analysis (blueprint __name-t keys) ---")
    print(f"base areas:   {len(base_ids)}")
    print(f"guest areas:  {len(guest_ids)}")
    print(f"intersection: {len(overlap)}  (these will be SKIPPED on import — same cortical id)")
    print(f"guest-only:   {len(only_guest)}  (expect these as NEW cortical areas)")
    if len(only_guest) <= 30:
        for x in sorted(only_guest):
            print(f"  guest-only id: {x}")

    with httpx.Client(timeout=120.0) as client:
        r = client.post(f"{base_url}/v1/genome/upload", json=base_obj)
        print(f"\nPOST /v1/genome/upload -> {r.status_code}")
        if r.status_code != 200:
            print(r.text[:2000])
            return 1
        print(r.json())

        r = client.post(f"{base_url}/v1/genome/amalgamation_by_payload", json=guest_obj)
        print(f"\nPOST /v1/genome/amalgamation_by_payload -> {r.status_code}")
        if r.status_code != 200:
            print(r.text[:2000])
            return 1
        q = r.json()
        print(q)
        amid = q.get("amalgamation_id")
        if not amid:
            print("No amalgamation_id in response", file=sys.stderr)
            return 1

        r = client.get(f"{base_url}/v1/system/health_check")
        print(f"\nGET /v1/system/health_check -> {r.status_code}")
        hc = r.json()
        print("amalgamation_pending:", json.dumps(hc.get("amalgamation_pending"), indent=2))
        root = hc.get("brain_regions_root")
        if not root:
            print("brain_regions_root missing; set parent manually", file=sys.stderr)
            return 1

        ox, oy, oz = args.origin
        r = client.post(
            f"{base_url}/v1/genome/amalgamation_destination",
            params={
                "amalgamation_id": amid,
                "circuit_origin_x": ox,
                "circuit_origin_y": oy,
                "circuit_origin_z": oz,
                "rewire_mode": args.rewire,
            },
            json={"brain_region_id": root},
        )
        print(f"\nPOST /v1/genome/amalgamation_destination -> {r.status_code}")
        try:
            body = r.json()
        except Exception:
            print(r.text[:4000])
            return 1
        print(json.dumps(body, indent=2)[:8000])
        skipped = body.get("skipped_existing_areas")
        if isinstance(skipped, list):
            print(f"\nskipped_existing_areas count: {len(skipped)} (expect ~{len(overlap)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
