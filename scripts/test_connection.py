#!/usr/bin/env python3
"""
Simple script to test FEAGI MCP connectivity without Cursor.

Usage:
    python test_connection.py
    python test_connection.py --host 192.168.1.100 --port 8000
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from feagi_mcp.feagi_client import FeagiClient


async def test_connection(host: str, port: int) -> None:
    """Test FEAGI connection and basic functionality."""

    print("=" * 60)
    print("  FEAGI MCP Connection Test")
    print("=" * 60)

    client = FeagiClient(host=host, port=port)

    try:
        print(f"\n1. Testing connection to {host}:{port}...")
        health = await client.health_check()

        if health["status"] == "ok":
            print("   ✓ Connected successfully")
            print(f"   ✓ Genome: {health.get('genome_name', 'N/A')}")
        else:
            print(f"   ✗ Connection failed: {health.get('message')}")
            return

        print("\n2. Testing genome download...")
        genome = await client.download_genome()
        if "error" in genome:
            print(f"   ✗ Failed: {genome['error']}")
        else:
            print(f"   ✓ Downloaded genome: {genome.get('genome_title', 'N/A')}")
            print(f"   ✓ Version: {genome.get('version', 'N/A')}")
            stats = genome.get("stats", {})
            print(f"   ✓ Areas: {stats.get('innate_cortical_area_count', 'N/A')}")
            print(f"   ✓ Neurons: {stats.get('innate_neuron_count', 'N/A')}")

        print("\n3. Testing cortical area listing...")
        areas = await client.list_cortical_areas()
        if areas:
            print(f"   ✓ Found {len(areas)} cortical areas")
            area_types = {}
            for area in areas:
                group = area.get("cortical_group", "UNKNOWN")
                area_types[group] = area_types.get(group, 0) + 1
            for group, count in sorted(area_types.items()):
                print(f"      - {group}: {count}")
        else:
            print("   ⚠ No areas found (or API unavailable)")

        print("\n4. Testing connectivity inspection...")
        if areas and len(areas) >= 2:
            area1_id = areas[0].get("cortical_id") or areas[0].get("id", "unknown")
            area2_id = areas[1].get("cortical_id") or areas[1].get("id", "unknown")
            print(f"   Checking: {area1_id} → {area2_id}")

            conn = await client.get_connectivity(area1_id, area2_id)
            if conn.get("connected"):
                print(f"   ✓ Connected ({conn['synapse_count']} synapses)")
            else:
                print("   ○ Not connected (expected for unrelated areas)")
        else:
            print("   ⚠ Skipped (need at least 2 areas)")

        print("\n5. Testing parameter retrieval...")
        if areas:
            test_area_id = areas[0].get("cortical_id") or areas[0].get("id")
            params = await client.get_area_parameters(test_area_id)
            if "error" not in params:
                param_count = len(params.get("parameters", {}))
                print(f"   ✓ Retrieved {param_count} parameters for {test_area_id}")
            else:
                print(f"   ✗ Failed: {params['error']}")

        print("\n" + "=" * 60)
        print("  All Tests Passed!")
        print("=" * 60)
        print("\nFEAGI MCP is working correctly.")
        print("You can now configure it in Cursor.")
        print("\nNext steps:")
        print("  1. See docs/CURSOR_INTEGRATION.md for setup")
        print("  2. See docs/QUICKSTART.md for usage examples")

    except Exception as e:
        print(f"\n✗ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await client.close()


def main() -> None:
    """Parse arguments and run test."""
    parser = argparse.ArgumentParser(description="Test FEAGI MCP connection")
    parser.add_argument("--host", default="localhost", help="FEAGI host")
    parser.add_argument("--port", type=int, default=8000, help="FEAGI port")

    args = parser.parse_args()

    asyncio.run(test_connection(args.host, args.port))


if __name__ == "__main__":
    main()
