"""
Example: Using New MCP Tools to Fix Spot Walking Genome

This demonstrates how the new MCP tools enable programmatic genome fixing
instead of manual JSON editing.

NOTE: This is pseudocode for demonstration. Actual usage would be through
an LLM agent with MCP access, not direct Python execution.
"""
# ruff: noqa: F704, F821

# ============================================================================
# SCENARIO: Spot robot isn't walking. Neural circuit fires but no motion.
# ============================================================================

# STEP 1: Understand what the MuJoCo controller expects
# --------------------------------------------------------
agents = await get_registered_agents()
# Returns: ["AgentIDBase64String"]

mujoco_agent_id = agents[0]  # Get the MuJoCo agent ID

# CRITICAL: Inspect the device registrations to understand motor structure
device_regs = await get_agent_device_registrations(mujoco_agent_id)

# Returns:
# {
#   "device_registrations": {
#     "output_units_and_decoder_properties": {
#       "positional_servo": {
#         "0": {  # group_id for fl_hip
#           "count": 3,
#           "metadata": {
#             "0": {"joint_name": "fl_hx", "control_semantics": "absolute_position"},
#             "1": {"joint_name": "fl_hy", "control_semantics": "absolute_position"},
#             "2": {"joint_name": "fl_kn", "control_semantics": "absolute_position"}
#           }
#         },
#         "1": {  # group_id for fr_hip
#           "count": 3,
#           "metadata": {...}
#         },
#         "2": {  # group_id for hl_hip
#           "count": 3,
#           "metadata": {...}
#         },
#         "3": {  # group_id for hr_hip
#           "count": 3,
#           "metadata": {...}
#         }
#       }
#     }
#   }
# }

# NOW I KNOW:
# - fl_hip uses group_id=0
# - fr_hip uses group_id=1
# - hl_hip uses group_id=2
# - hr_hip uses group_id=3
# - Each has 3 joints (hx, hy, kn)
# - Control mode: absolute_position (maps to OPU area suffix "-0")


# STEP 2: Check what OPU areas currently exist
# -----------------------------------------------
opu_areas = await list_opu_areas()
# Returns: ["Y29wb3NlMF8="]  # Only "Spot_Joint_Control" exists

# But MuJoCo registered these dynamically:
embodiment = await get_embodiment_status()
# Shows: fl_hip-0 (b3BzZQEAAAA=), fr_hip-0 (b3BzZQEAAAE=), etc.


# STEP 3: Check if Hip controllers are wired to the right OPUs
# -------------------------------------------------------------
conn_fl = await get_connectivity(src_area="cHipFL", dst_area="opose1")
# Returns: {"connected": False, "message": "No connections found"}

# AH-HA! Hip controllers aren't wired to the per-limb OPU areas!


# STEP 4: Programmatically add the missing OPU areas to genome
# ------------------------------------------------------------
# Instead of manual JSON editing, use create_cortical_area:

await create_cortical_area(
    name="fl_hip",
    cortical_type="OPU",
    dimensions=[3, 1, 10],
    position=[800, 400, -30],
    device_count=3,
    neurons_per_voxel=1,
    properties={
        "grp_id": 0,  # Matches MuJoCo's group_id for fl_hip
        "parent_region_id": "root",
    },
)

await create_cortical_area(
    name="fr_hip",
    cortical_type="OPU",
    dimensions=[3, 1, 10],
    position=[800, -400, -30],
    device_count=3,
    properties={"grp_id": 1},
)

await create_cortical_area(
    name="hl_hip",
    cortical_type="OPU",
    dimensions=[3, 1, 10],
    position=[1200, -400, -30],
    device_count=3,
    properties={"grp_id": 2},
)

await create_cortical_area(
    name="hr_hip",
    cortical_type="OPU",
    dimensions=[3, 1, 10],
    position=[1200, 400, -30],
    device_count=3,
    properties={"grp_id": 3},
)


# STEP 5: Wire Hip controllers to the new OPU areas
# --------------------------------------------------
connection_rule = [
    {
        "morphology_id": "all_to_all",
        "morphology_scalar": [1, 1, 1],
        "postSynapticCurrent_multiplier": 25.0,
        "plasticity_flag": False,
        "plasticity_constant": 1,
        "ltp_multiplier": 1,
        "ltd_multiplier": 1,
        "plasticity_window": 0,
    }
]

await update_cortical_mapping(src_area="cHipFL", dst_area="opose1", mapping_rules=connection_rule)

await update_cortical_mapping(src_area="cHipFR", dst_area="opose2", mapping_rules=connection_rule)

await update_cortical_mapping(src_area="cHipRL", dst_area="opose3", mapping_rules=connection_rule)

await update_cortical_mapping(src_area="cHipRR", dst_area="opose4", mapping_rules=connection_rule)


# STEP 6: Verify the wiring worked
# ---------------------------------
for src, dst in [
    ("cHipFL", "opose1"),
    ("cHipFR", "opose2"),
    ("cHipRL", "opose3"),
    ("cHipRR", "opose4"),
]:
    conn = await get_connectivity(src_area=src, dst_area=dst)
    print(f"{src} -> {dst}: {conn['connected']}, {conn['synapse_count']} synapses")

# Returns:
# cHipFL -> opose1: True, 30 synapses
# cHipFR -> opose2: True, 30 synapses
# cHipRL -> opose3: True, 30 synapses
# cHipRR -> opose4: True, 30 synapses


# STEP 7: Stimulate and verify motor signals reach the robot
# -----------------------------------------------------------
await stimulate_area(area_id="cStart", coordinates=[0, 0, 0], potential=100.0)

# Monitor Hip controller activity
hip_activity = await monitor_activity(area_id="cHipFL", duration_ms=500)
print(f"Hip FL firing rate: {hip_activity['firing_rate']} Hz")

# Monitor OPU output
opu_activity = await monitor_activity(area_id="opose1", duration_ms=500)
print(f"FL Hip OPU firing rate: {opu_activity['firing_rate']} Hz")

# Result: Now signals propagate CPG -> Hip -> OPU -> MuJoCo -> Robot walks!


# ============================================================================
# COMPARISON: Before vs After
# ============================================================================

# BEFORE (Manual Approach):
# 1. Download genome JSON
# 2. Find dstmap entries by searching thousands of lines
# 3. Guess Base64 cortical IDs (b3BzZQEAAAA=)
# 4. Manually edit JSON
# 5. Upload and pray
# 6. Debug by downloading genome again and parsing JSON

# AFTER (MCP-Driven Approach):
# 1. get_agent_device_registrations() → See group_id mappings
# 2. list_opu_areas() → See what exists
# 3. create_cortical_area() → Add missing OPUs with correct grp_id
# 4. update_cortical_mapping() → Wire Hip → OPU programmatically
# 5. get_connectivity() → Verify instantly
# 6. Done!

# Time saved: ~2 hours of manual JSON editing and debugging
# Accuracy: 100% (no manual Base64 encoding errors)
# Reproducibility: Fully scriptable for other embodiments
