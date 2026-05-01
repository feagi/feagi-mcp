# New MCP Tools Added (2026-03-29)

## Overview
Added 11 new diagnostic and genome editing tools to enable programmatic genome manipulation and better agent introspection.

## Agent Introspection Tools

### 1. `get_agent_properties`
**Purpose**: Get detailed properties for a specific registered agent  
**Endpoint**: `/v1/agent/properties/{agent_id}`  
**Returns**: Agent type, capabilities, IP, port, version info

**Use case**: After seeing an agent in `get_registered_agents`, inspect its full configuration to understand what it can do.

### 2. `get_agent_device_registrations`
**Purpose**: Get motor/sensor structure from agent's device registration  
**Endpoint**: `/v1/agent/{agent_id}/device_registrations`  
**Returns**: 
- `output_units_and_decoder_properties`: Motor configuration with group_ids, control modes
- `input_units_and_encoder_properties`: Sensor configuration
- Channel metadata: joint names, actuator types, control semantics

**Use case**: CRITICAL - This answers questions like:
- What `group_id` does `fl_hip` use? (Answer: 0)
- What control mode does this motor support? (absolute-0 vs incremental-1)
- What OPU cortical IDs should I wire to in the genome?

**Example output**:
```json
{
  "output_units_and_decoder_properties": {
    "positional_servo": {
      "0": {  // group_id for fl_hip
        "count": 3,
        "metadata": {
          "0": {"joint_name": "fl_hx", "control_semantics": "absolute_position"},
          "1": {"joint_name": "fl_hy", ...},
          "2": {"joint_name": "fl_kn", ...}
        }
      }
    }
  }
}
```

### 3. `list_opu_areas`
**Purpose**: List only motor output areas  
**Endpoint**: `/v1/cortical_area/opu`  
**Returns**: Filtered list of OPU cortical IDs

### 4. `list_ipu_areas`
**Purpose**: List only sensory input areas  
**Endpoint**: `/v1/cortical_area/ipu`  
**Returns**: Filtered list of IPU cortical IDs

## Genome Editing Tools

### Cortical area naming policy (MCP)

Names are persisted in the genome and shown in Brain Visualizer. **Do not** prefix with `Mcp`, `MCP`, `FEAGI`, or the client/tool name.

| Do | Avoid |
|----|--------|
| Role-first, human-readable: `OrGate_Input_A`, `CPG_Rhythm_Core`, `Motor_FL_Hip` | Generic: `Custom1`, `Area_A`, `Test` |
| Circuit or subsystem prefix + role: `Demo_OR_InputA`, `Walk_CPG_Hip_FL` | Implementation noise: `McpOrInput`, `NewArea_2026` |
| One consistent style per project (`PascalCase` or `snake_case`; underscores between role facets) | Mixed random casing |

Keep labels **short but unambiguous** (aim under ~40 characters). Prefer names that answer: *what circuit* and *what role* (input, output, interneuron, memory bank, etc.).

### 5. `create_cortical_area`
**Purpose**: Add new cortical areas programmatically  
**Endpoints**: 
- `/v1/cortical_area/cortical_area` (for OPU/IPU)
- `/v1/cortical_area/custom_cortical_area` (for CUSTOM/MEMORY)

**Parameters**:
- `name`: Human-readable name (follow [Cortical area naming policy](#cortical-area-naming-policy-mcp) above; never use an `Mcp` prefix)
- `cortical_type`: "OPU", "IPU", "CUSTOM", or "MEMORY"
- `dimensions`: [width, height, depth]
- `position`: [x, y, z] coordinates
- `neurons_per_voxel`: Neurons per voxel (default: 1)
- `device_count`: Number of devices for IPU/OPU
- `brain_region_id`: **Required for CUSTOM and MEMORY** — parent brain region (circuit) UUID. Call `get_brain_regions` to list regions. Same as REST `brain_region_id` on `custom_cortical_area`. You may pass this inside `properties["brain_region_id"]` instead of the top-level argument.
- `properties`: Optional dict (e.g. `grp_id`; for CUSTOM/MEMORY include `brain_region_id` here if not using the dedicated parameter)

**Use case**: Instead of manually editing genome JSON, programmatically add the 4 per-limb OPU areas:
```python
mcp.create_cortical_area(
    name="fl_hip",
    cortical_type="OPU",
    dimensions=[3, 1, 10],
    position=[800, 400, -30],
    device_count=3,
    properties={"grp_id": 0}
)
```

**CUSTOM / MEMORY** (must supply a non-root circuit region):

```python
mcp.create_cortical_area(
    name="MyCircuit",
    cortical_type="CUSTOM",
    dimensions=[10, 10, 1],
    position=[50, 50, 0],
    brain_region_id="<uuid-from-get_brain_regions>",
)
```

**Placement (MCP enforced for CUSTOM/MEMORY)** — before calling the API, the client checks:

- **Origin clearance**: anchor must be **≥ 20 voxels** (Euclidean) from `(0,0,0)` so areas stay visible next to the BV axis helper.
- **Label spacing**: anchor must be **≥ 32 voxels** (Euclidean) from every existing area anchor (from `get_cortical_area_geometry`) to reduce overlapping names in 3D.

Set `skip_placement_validation=True` only if you must bypass these checks.

### 6. `update_cortical_area`
**Purpose**: Modify existing cortical area properties  
**Endpoint**: `/v1/cortical_area/cortical_area` (PUT)

**Use case**: Change neural parameters, position, dimensions without reloading entire genome.

**Rate-modulated leak (homeostatic, dense custom LIF):** set `rate_modulated_leak` in `updates` to a JSON object (`enabled`, `target_firing_per_burst`, `rate_ema_tau_bursts`, `gain`, `leak_min`, `leak_max`, `update_every_n_bursts`) as in the FEAGI and Brain Visualizer Advanced / Danger area UI. `inspect_cortical_areas_minimal` includes `rate_modulated_leak` in its projection when the field is present on the area or under `properties`.

### 7. `delete_cortical_area`
**Purpose**: Remove a cortical area  
**Endpoint**: `/v1/cortical_area/cortical_area` (DELETE)

## Connection Management Tools

### 8. `get_cortical_mapping`
**Purpose**: Get detailed connection configuration between two areas  
**Endpoint**: `/v1/cortical_mapping/mapping_properties` (POST)  
**Returns**: Connection rules with morphology, weights, plasticity

**Use case**: Instead of parsing genome JSON, directly query "What's the connection from cHipFL to opose1?"

### 9. `update_cortical_mapping`
**Purpose**: Create or update connections between cortical areas  
**Endpoint**: `/v1/cortical_mapping/mapping_properties` (PUT)

**Parameters**:
- `src_area`: Source cortical ID
- `dst_area`: Destination cortical ID  
- `mapping_rules`: List of connection rules

**Use case**: Programmatically wire Hip controllers to OPU areas:
```python
mcp.update_cortical_mapping(
    src_area="cHipFL",
    dst_area="opose1",
    mapping_rules=[{
        "morphology_id": "all_to_all",
        "morphology_scalar": [1, 1, 1],
        "postSynapticCurrent_multiplier": 25.0,
        "plasticity_flag": False,
        "plasticity_constant": 1,
        "ltp_multiplier": 1,
        "ltd_multiplier": 1,
        "plasticity_window": 0
    }]
)
```

### 10. `delete_cortical_mapping`
**Purpose**: Remove connections between two areas  
**Endpoint**: `/v1/cortical_mapping/mapping` (DELETE)

### 11–14. Composer shared simulator packs (optional)

**Purpose**: Eliminate fragile browser-curl probing of Composer for GCS-hosted MuJoCo (and other) asset packs deployed via `shared-sim/` CI.

**Configuration**: Set `FEAGI_COMPOSER_BASE_URL` to the Composer HTTPS root (no trailing slash), e.g. `https://us-staging-composer.brainsforrobots.com`.

| Tool | Maps to |
|------|---------|
| `composer_list_simulator_packs` | `GET /v1/public/global/simulator-packs` |
| `composer_get_simulator_pack_versions` | `GET .../simulator-packs/{pack_id}` |
| `composer_get_simulator_pack_resolved` | `GET .../{pack_id}/versions/{semver}/resolved` |
| `composer_download_simulator_pack_bundle` | resolved JSON + sequential `GET` of each blob URL |

**Use case**: After `composer_get_simulator_pack_resolved`, place files beside `scene.xml` via `composer_download_simulator_pack_bundle`, add MJCF `<include file="…"/>`, restart the MuJoCo controller (MjModel reload).

## Impact on Current Debugging Workflow

### Before (Manual Approach):
1. Guess which OPU cortical IDs to use
2. Manually edit genome JSON with Base64 IDs
3. Upload and hope it works
4. Debugging requires downloading genome and parsing JSON

### After (MCP-Driven Approach):
1. `get_registered_agents()` → Get MuJoCo agent ID
2. `get_agent_device_registrations(agent_id)` → See `group_id` mappings
3. `list_opu_areas()` → See which OPUs exist
4. `get_cortical_mapping("cHipFL", "opose1")` → Check current wiring
5. `create_cortical_area(...)` → Add missing OPU areas if needed
6. `update_cortical_mapping(...)` → Wire Hip → OPU programmatically
7. Verify with `get_connectivity()`

## Next Steps

1. Restart Cursor to load new MCP tools
2. Test with current Spot walking scenario
3. Consider adding:
   - `batch_create_cortical_areas` for bulk operations
   - `get_all_cortical_mappings` to see full connectivity graph
   - `validate_connection` to check if a connection will work before creating it
