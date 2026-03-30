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

### 5. `create_cortical_area`
**Purpose**: Add new cortical areas programmatically  
**Endpoints**: 
- `/v1/cortical_area/cortical_area` (for OPU/IPU)
- `/v1/cortical_area/custom_cortical_area` (for CUSTOM/MEMORY)

**Parameters**:
- `name`: Human-readable name
- `cortical_type`: "OPU", "IPU", "CUSTOM", or "MEMORY"
- `dimensions`: [width, height, depth]
- `position`: [x, y, z] coordinates
- `neurons_per_voxel`: Neurons per voxel (default: 1)
- `device_count`: Number of devices for IPU/OPU
- `properties`: Optional dict (parent_region_id, grp_id, etc.)

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

### 6. `update_cortical_area`
**Purpose**: Modify existing cortical area properties  
**Endpoint**: `/v1/cortical_area/cortical_area` (PUT)

**Use case**: Change neural parameters, position, dimensions without reloading entire genome.

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
