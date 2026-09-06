"""Example: Using FEAGI MCP to design and debug a walking genome."""

import asyncio

from feagi_mcp.feagi_client import FeagiClient


async def design_cpg_circuit():
    """Example workflow for designing a CPG-based walking controller."""

    client = FeagiClient(host="localhost", port=8000)

    try:
        print("=" * 60)
        print("FEAGI MCP - CPG Circuit Design Example")
        print("=" * 60)

        print("\n1. Check FEAGI health...")
        health = await client.health_check()
        print(f"   Status: {health.get('status')}")
        print(f"   Genome: {health.get('genome_name')}")

        print("\n2. List current cortical areas...")
        areas = await client.list_cortical_areas()
        print(f"   Found {len(areas)} areas")

        cpg_areas = [a for a in areas if "CPG" in a.get("name", "")]
        if cpg_areas:
            print(f"   CPG areas found: {[a.get('name') for a in cpg_areas]}")

            print("\n3. Monitor CPG activity...")
            for cpg in cpg_areas[:2]:
                area_id = cpg.get("cortical_id") or cpg.get("id")
                if area_id:
                    activity = await client.monitor_activity(area_id, duration_ms=2000)
                    print(f"   {cpg.get('name')}: {activity}")

        print("\n4. Check embodiment status...")
        embodiment = await client.get_embodiment_status()
        print(f"   OPU areas: {embodiment.get('opu_areas', [])}")
        print(f"   IPU areas: {embodiment.get('ipu_areas', [])}")

        print("\n5. Verify connectivity (CPG → Hip control)...")
        conn = await client.get_connectivity("cCPGa_", "cHipFL")
        print(f"   Connected: {conn.get('connected')}")
        if conn.get("connected"):
            print(f"   Synapses: {conn.get('synapse_count')}")
            print(
                f"   Morphologies: {[c.get('morphology_id') for c in conn.get('connections', [])]}"
            )

        print("\n6. Stimulate WalkStart to trigger walking...")
        stim_result = await client.stimulate_area(
            area_id="cStart",
            coordinates=[0, 0, 0],
            potential=1.0,
            duration_ms=500,
        )
        print(f"   Stimulation: {stim_result}")

        print("\n7. Monitor motor output (OPU)...")
        await asyncio.sleep(1)
        motor_activity = await client.monitor_activity("opose0", duration_ms=1000)
        print(f"   Motor output: {motor_activity}")

        print("\n" + "=" * 60)
        print("Design iteration complete!")
        print("=" * 60)

    finally:
        await client.close()


async def validate_custom_genome():
    """Example: Validate a genome before uploading."""

    genome_path = "/path/to/spot_walking.genome"

    with open(genome_path) as f:
        genome_json = f.read()

    client = FeagiClient()
    try:
        from feagi_mcp.server import validate_genome

        print("Validating genome...")
        result = await validate_genome(genome_json)

        print(f"\nValid: {result['valid']}")
        print(f"Cortical areas: {result['cortical_area_count']}")

        if result["issues"]:
            print("\nIssues:")
            for issue in result["issues"]:
                print(f"  - {issue}")

        if result["warnings"]:
            print("\nWarnings:")
            for warning in result["warnings"]:
                print(f"  - {warning}")

    finally:
        await client.close()


if __name__ == "__main__":
    print("Choose example:")
    print("1. Design CPG circuit (requires running FEAGI)")
    print("2. Validate genome file")

    choice = input("\nChoice [1]: ").strip() or "1"

    if choice == "1":
        asyncio.run(design_cpg_circuit())
    elif choice == "2":
        asyncio.run(validate_custom_genome())
    else:
        print("Invalid choice")
