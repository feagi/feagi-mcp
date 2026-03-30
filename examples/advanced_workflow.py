"""Advanced example: Complete CPG design workflow with validation and tuning."""

import asyncio

from feagi_mcp.feagi_client import FeagiClient


async def build_walking_genome_with_validation():
    """
    Complete workflow demonstrating:
    1. Design a CPG-based walking controller
    2. Validate structure
    3. Upload to FEAGI
    4. Monitor and verify behavior
    5. Iteratively tune parameters
    """

    client = FeagiClient(host="localhost", port=8000)

    try:
        print("\n" + "=" * 70)
        print("  FEAGI MCP - Advanced Circuit Design Workflow")
        print("=" * 70)

        print("\n[PHASE 1] FEAGI Health Check")
        print("-" * 70)
        health = await client.health_check()
        if health["status"] != "ok":
            print(f"✗ FEAGI not reachable: {health.get('message')}")
            return
        print("✓ FEAGI is running")
        print(f"  Current genome: {health['genome_name']}")

        print("\n[PHASE 2] Download Current Genome as Baseline")
        print("-" * 70)
        baseline_genome = await client.download_genome()
        if "error" in baseline_genome:
            print(f"✗ Failed to download genome: {baseline_genome['error']}")
            return
        print("✓ Downloaded baseline genome")
        print(f"  Version: {baseline_genome.get('version')}")
        print(
            f"  Areas: {baseline_genome.get('stats', {}).get('innate_cortical_area_count', 'N/A')}"
        )

        print("\n[PHASE 3] Analyze Existing Architecture")
        print("-" * 70)
        areas = await client.list_cortical_areas()
        print(f"✓ Found {len(areas)} cortical areas")

        cpg_areas = [a for a in areas if "CPG" in a.get("name", "")]
        hip_areas = [a for a in areas if "Hip" in a.get("name", "")]
        opu_areas = [a for a in areas if a.get("cortical_group") == "OPU"]

        print(f"  CPG areas: {len(cpg_areas)}")
        print(f"  Hip control areas: {len(hip_areas)}")
        print(f"  Motor outputs (OPU): {len(opu_areas)}")

        if cpg_areas:
            print("\n[PHASE 4] Monitor CPG Activity")
            print("-" * 70)
            for cpg in cpg_areas[:2]:
                cpg_id = cpg.get("cortical_id") or cpg.get("id", "unknown")
                print(f"\nMonitoring {cpg['name']} ({cpg_id}) for 2 seconds...")
                activity = await client.monitor_activity(cpg_id, duration_ms=2000)

                if "error" in activity:
                    print(f"  ⚠ Monitoring not available: {activity['error']}")
                    print("    (API endpoint may not be implemented yet)")
                else:
                    firing_rate = activity.get("firing_rate", 0)
                    active_neurons = activity.get("active_neurons", [])
                    print(f"  ✓ Firing rate: {firing_rate:.2f} Hz")
                    print(f"  ✓ Active neurons: {len(active_neurons)}")

                    if firing_rate > 0:
                        print("  → CPG is oscillating correctly!")
                    else:
                        print("  ⚠ CPG may not be active - try stimulation")

        print("\n[PHASE 5] Verify Circuit Connectivity")
        print("-" * 70)
        if cpg_areas and hip_areas and len(cpg_areas) > 0 and len(hip_areas) > 0:
            cpg_id = cpg_areas[0].get("cortical_id", "cCPGa_")
            hip_id = hip_areas[0].get("cortical_id") or hip_areas[0].get("id", "cHipFL")

            print(f"Checking: {cpg_id} → {hip_id}")
            conn = await client.get_connectivity(cpg_id, hip_id)

            if conn.get("connected"):
                print(f"  ✓ Connected with {conn['synapse_count']} synapses")
                for c in conn.get("connections", [])[:3]:
                    morph = c.get("morphology_id", "unknown")
                    weight = c.get("postSynapticCurrent_multiplier", 0)
                    print(f"    - {morph}: weight={weight:.1f}")
            else:
                print("  ✗ No connection found")
                print("    This may explain lack of movement!")

        if cpg_areas and opu_areas:
            print(f"\nChecking: {cpg_id} → Motor Output")
            from feagi_mcp.server import trace_signal_path

            paths = await trace_signal_path(cpg_id, opu_areas[0].get("cortical_id", "opose0"))
            if paths.get("connected"):
                print(f"  ✓ Signal path exists ({paths['paths_found']} paths)")
                for i, path in enumerate(paths.get("paths", [])[:2]):
                    print(f"    Path {i + 1}: {' → '.join(path)}")
            else:
                print("  ✗ No signal path to motor output")
                print("    CPG cannot control robot!")

        print("\n[PHASE 6] Check Embodiment Status")
        print("-" * 70)
        embodiment = await client.get_embodiment_status()

        if "opu_areas" in embodiment:
            print("✓ Motor outputs configured:")
            for opu in embodiment["opu_areas"]:
                print(f"  - {opu['name']} (ID: {opu['id']}, Devices: {opu['device_count']})")

        if "ipu_areas" in embodiment:
            print("\n✓ Sensory inputs configured:")
            for ipu in embodiment["ipu_areas"]:
                print(f"  - {ipu['name']} (ID: {ipu['id']}, Devices: {ipu['device_count']})")

        print("\n[PHASE 7] Circuit Health Summary")
        print("-" * 70)
        issues = []
        warnings = []

        if not cpg_areas:
            issues.append("No CPG areas found - cannot generate rhythmic movement")
        if not opu_areas:
            issues.append("No motor outputs (OPU) - cannot control robot")
        if cpg_areas and opu_areas and not paths.get("connected"):
            issues.append("CPG not connected to motor output")

        if issues:
            print("✗ Issues found:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("✓ Circuit architecture looks good!")

        if warnings:
            print("\n⚠ Warnings:")
            for warning in warnings:
                print(f"  - {warning}")

        print("\n[PHASE 8] Recommendations")
        print("-" * 70)
        if issues:
            print("To fix issues:")
            if "No CPG" in str(issues):
                print("  1. Add CPG oscillator areas for rhythm generation")
            if "not connected" in str(issues):
                print("  2. Add connections from CPG → Hip Control → OPU")
            if "No motor" in str(issues):
                print("  3. Define OPU area matching controller registration")
        else:
            print("Circuit is well-formed. Next steps:")
            print("  1. Stimulate WalkStart or CPG to activate")
            print("  2. Monitor CPG oscillation frequency")
            print("  3. Check if motor commands reach controller")
            print("  4. Tune PSC multipliers if movement is too weak/strong")

        print("\n" + "=" * 70)
        print("  Workflow Complete!")
        print("=" * 70)

    finally:
        await client.close()


async def tune_cpg_frequency():
    """Example: Adjust CPG oscillation frequency iteratively."""

    client = FeagiClient()

    try:
        print("\n" + "=" * 60)
        print("  CPG Frequency Tuning")
        print("=" * 60)

        cpg_id = "cCPGa_"

        print("\n1. Measure current frequency...")
        activity = await client.monitor_activity(cpg_id, duration_ms=3000)

        if "error" not in activity:
            current_freq = activity.get("firing_rate", 0)
            print(f"   Current: {current_freq:.2f} Hz")

            target_freq = 5.0
            if abs(current_freq - target_freq) > 0.5:
                print(f"\n2. Frequency deviation detected (target: {target_freq} Hz)")

                print("\n3. Modifying parameters based on frequency...")
                print("   [In practice: download genome, adjust leak_coefficient, re-upload]")
                if current_freq > target_freq:
                    print("   → Reducing leak to slow oscillation")
                else:
                    print("   → Increasing leak to speed up oscillation")

                print("\n4. Upload modified genome:")
                print("   result = await client.upload_genome(modified_genome)")

                print("\n5. Re-measure frequency:")
                print("   activity = await client.monitor_activity(...)")
            else:
                print("   ✓ Frequency within target range!")
        else:
            print("   Monitoring API not available yet")

    finally:
        await client.close()


if __name__ == "__main__":
    print("FEAGI MCP - Advanced Examples")
    print("=" * 60)
    print("1. Complete circuit design workflow")
    print("2. CPG frequency tuning")
    print()

    choice = input("Select example [1]: ").strip() or "1"

    if choice == "1":
        asyncio.run(build_walking_genome_with_validation())
    elif choice == "2":
        asyncio.run(tune_cpg_frequency())
    else:
        print("Invalid choice")
