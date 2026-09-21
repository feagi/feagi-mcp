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

Do **not** dump this payload for musculoskeletal bodies. Prefer
``get_motor_group_summary`` (group titles + channel counts) or
``explain_cortical_area_naming`` (why an OPU is titled ``ungrouped-1``).
``get_agent_joint_map`` flattens joint *and* muscle/tendon servo
channels when you need per-actuator rows. Live FEAGI returns registrations as a sibling of ``capabilities``
on ``/v1/agent/capabilities/all``; the client now reads that sibling field.

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

### 2b. `compare_device_registration_store`
**Purpose**: Compact session vs descriptor registration comparison  
**Endpoint**: `/v1/agent/device_registration_store`  
**Returns**: `poll_source`, unit-type keys, vision group indexes, `mismatch`,
`segmented_vision_only_in_descriptor`

Use this instead of `list_agent_capabilities_all` when deleted `isvi` areas
keep returning. Auto-create prefers the **descriptor** store; capabilities/all
only shows the live session.

### 2c. `get_log_tail`
**Purpose**: Filtered FEAGI process logs  
**Endpoint**: `/v1/system/log_tail`  
Pass `message_contains` (`isvi`, `SegmentedVision`, `auto-create`) instead of
fetching the unfiltered ring dump.

### 3. `list_opu_areas`
**Purpose**: List only motor output areas  
**Endpoint**: `/v1/cortical_area/opu`  
**Returns**: Filtered list of OPU cortical IDs

### 4. `list_ipu_areas`
**Purpose**: List only sensory input areas  
**Endpoint**: `/v1/cortical_area/ipu`  
**Returns**: Filtered list of IPU cortical IDs

### 4b. `list_io_areas_compact`
**Purpose**: Genome-wide IPU/OPU inventory without the metadata dump  
**Endpoint**: one `GET /v1/connectome/cortical_areas/list/detailed` (same as `list_cortical_areas`)  
**Returns**: `count`, `mismatch_count`, `by_subtype`, compact `areas` rows

Use this instead of `list_ipu_areas_with_metadata` / `list_opu_areas_with_metadata` when you need:
- 4-char subtype (`ipro`, `imis`, `isvi`, `opse`, …) decoded locally from the cortical ID
- `cortical_dimensions`, `cortical_dimensions_per_device`, `dev_count`
- `dimension_dev_count_mismatch` when width is not `per_device_x * dev_count`

`include_areas=False` returns the subtype summary only. `mismatches_only=True` lists only collapsed I/O strips.

## Classifier assembly

### `list_classifiers`

**Endpoint**: `GET /v1/cortical_area/classifiers`  
**Returns**: compact rows (`classifier_id`, name, parent, 3D pose, input ids, owned `kernel_memory_id` / `class_memory_id` / `scan_twin_id`)

Use this instead of searching cortical-area names for `_kernel_mem`, `_class_mem`, or `_twin`. Classifiers are first-class genome objects, not cortical areas.

### `inspect_classifier`

**Endpoints**: classifier GET/list + cortical-area catalog + mapping table  
**Returns**: resolved slots (kernel/class/field + internals + twin), the four required mappings, `missing_slots`, `missing_mappings`, `twin_visible`

One call for "where is the twin and is the assembly wired?". Do not walk `list_cortical_areas` / `get_connectivity_summary` by hand when this tool is available.

## Connectivity rule authoring

### `propose_connectivity_rule`

Local judgment (dimensions are fetched only when area ids are given and dims are
omitted). Call this **before** `create_morphology`.

- Reuse a core rule when `reuse` is set (`block_to_block`, `projector`, …).
- Otherwise create the returned `custom` patterns/vectors unchanged.
- Never expand a regular transform into exact voxel pairs.
- PositionalServo absolute dest (`opse` subunit 0): dest `z=0` is max command.
  `?+17` / high Z averages to ~0.05 excitation.
- Sit/motor subset requires `source_x_channels`. Wildcarding every muscle is refused.

`create_morphology`, `update_morphology`, and `build_reflex_mapping` enforce
the same policy.

## Activity monitoring

### `monitor_activity` / `monitor_activity_batch`

`summary_only=True` (default) returns counts, rates, and `lifetime_stats` only.
It omits `spike_history` and the `active_neurons` id list. A multi-area batch
of an active babble/OPU used to dump thousands of spike rows into the MCP
context. Set `summary_only=False` only when you need the raw spike list.

### `get_morphology`

One-rule fetch (`POST /v1/morphology/morphology_properties`). Do not use
`list_morphologies` for a single name.

- Compact rules include `parameters` by default (the actual pattern/vector rows).
- Enumerated dumps omit `parameters` unless `include_parameters=True`.
- When stored rows are an enumerable dump, `judgment.compact_form` is the
  `N..M` rewrite.

### `get_sensor_snapshot_last`

Default `summary_only=True` returns `areas_summary` (per-Z count/min/max/mean)
and `encoded_potential_stats`. It does not dump every vision voxel. Pass
`threshold` (the IPU fire threshold) for `count_gte_threshold` per Z layer.
Set `summary_only=False` only for a raw XYZP dump.

### `get_voxel_neurons`

Default `view=summary` keeps neuron state and replaces synapse lists with
source-Z histograms, unique source areas, and unique weights. Use
`view=edges` plus `synapse_page` only when a raw page is required.

### Area name aliases

`list_cortical_area_names` / `list_cortical_areas` treat `vision`,
`simple vision`, and `camera` as aliases for `iimg` / `isvi` / `isvm` /
`isig`. `iimg Unit 0` is simple vision even though the title does not
contain the word vision.

### `update_morphology`

`PUT /v1/morphology/morphology`. Replaces the rule and rebuilds mappings that
use it. Submit compact patterns (or `judgment.compact_form` from
`get_morphology`). Enumerated dumps are rejected.

## Genome Editing Tools

### Circuit naming policy (MCP)

In Brain Visualizer a **circuit** is a named **brain region**, not a cortical area. Untitled genomes expose a placeholder region titled **Autogen Circuit**. MCP refuses that container.

**Workflow when building a circuit**

1. Name the function (Sit, Walk CPG, OR Gate) — not the tool or a UUID.
2. `create_brain_region(title="<function>")`.
3. `create_cortical_area(..., brain_region_id=<that region_id>)` for CUSTOM/MEMORY.

| Do | Avoid |
|----|--------|
| Function-first: `Sit`, `Sit Drive`, `Walk CPG`, `OR Gate`, `Balance` | `Autogen Circuit`, `Untitled`, `New Circuit`, `Circuit` |
| Same function name the user asked for | `MCP Circuit`, `McpSit`, a region UUID as the title |

`create_brain_region` rejects placeholder titles. `create_cortical_area` (CUSTOM/MEMORY) and `clone_cortical_area` (when `parent_region_id` is set) look up the parent title and reject Autogen Circuit / Untitled.

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
- `brain_region_id`: **Required for CUSTOM and MEMORY** — parent brain region (circuit) UUID whose **title names the circuit function**. Do not use Autogen Circuit. Call `create_brain_region` first; `get_brain_regions` only to reuse an already-named circuit. Same as REST `brain_region_id` on `custom_cortical_area`. You may pass this inside `properties["brain_region_id"]` instead of the top-level argument.
- `properties`: Optional dict (e.g. `grp_id`; for CUSTOM/MEMORY include `brain_region_id` here if not using the dedicated parameter)

**Use case**: Instead of manually editing genome JSON, programmatically add the 4 per-limb OPU areas:
```python
mcp.create_cortical_area(
    name="fl_hip",
    cortical_type="OPU",
    dimensions=[3, 1, 10],
    position=[800, 400, -30],
    device_count=3,
    properties={"grp_id": 0},
)
```

**CUSTOM / MEMORY** (must supply a function-named circuit region):

```python
region = mcp.create_brain_region(
    title="Sit",
    coordinates_2d=[0, 0],
    coordinates_3d=[120, 40, 0],
)
mcp.create_cortical_area(
    name="babble",
    cortical_type="CUSTOM",
    dimensions=[10, 10, 1],
    position=[50, 50, 0],
    brain_region_id=region["region_id"],
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
**Purpose**: Get stored connection rules between two areas  
**Source**: source-area `cortical_mapping_dst` via `POST /v1/cortical_area/cortical_area_properties`  
**Returns**: Connection rules with morphology, weights, plasticity (as stored)

Does not call `POST /v1/cortical_mapping/mapping_properties`, which 400s when a
non-plastic rule omits `plasticity_constant`.

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
    mapping_rules=[
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
    ],
)
```

### 10. `delete_cortical_mapping`
**Purpose**: Remove connections between two areas  
**Endpoint**: `/v1/cortical_mapping/mapping` (DELETE)

### 11–14. Composer shared simulator packs (optional)

**Purpose**: Eliminate fragile browser-curl probing of Composer for GCS-hosted MuJoCo (and other) asset packs deployed via `shared-sim/` CI.

**Configuration**: Set `FEAGI_COMPOSER_BASE_URL` to the Composer HTTPS root (no trailing slash), e.g. `https://staging-api.brainsforrobots.com`.

| Tool | Maps to |
|------|---------|
| `composer_list_simulator_packs` | `GET /v1/public/global/simulator-packs` |
| `composer_get_simulator_pack_versions` | `GET .../simulator-packs/{pack_id}` |
| `composer_get_simulator_pack_resolved` | `GET .../{pack_id}/versions/{semver}/resolved` |
| `composer_download_simulator_pack_bundle` | resolved JSON + sequential `GET` of each blob URL |

**Use case**: After `composer_get_simulator_pack_resolved`, place files beside `scene.xml` via `composer_download_simulator_pack_bundle`, add MJCF `<include file="…"/>`, restart the MuJoCo controller (MjModel reload).

## Cortical ID interpretation (client-side)

### `interpret_cortical_id`

Pure decode of an 8-byte cortical wire ID (standard Base64 or legacy 8-character latin-1 key). ``cortical_subunit_index`` is flag bits 4-7 of bytes 4-5 (connectome ``subunit_id``, 0-15). ``cortical_unit_index`` is little-endian u16 in bytes 6-7 (BV ``unit_id``). ``frame_change_handling`` comes from flag bit 8. This matches Rust ``CorticalID``; byte 6 is **not** the subunit.

### ``explain_cortical_area_naming``

Compact title provenance for a live area: connectome name/subunit/encoding, local ID decode, matching motor bundle (if any), and a one-sentence ``naming_cause``. Does **not** return per-channel registrations.

### ``get_motor_group_summary``

One row per motor bundle (friendly name, unit id, channel count, sample actuator names, ``is_catch_all``). One capabilities fetch; optional ``agent_id`` filter.

### ``inspect_cortical_area``

The connectome inspector response includes ``cortical_id_interpretation`` (same structure) for the requested ``cortical_id`` so agents do not need a separate decode step.

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
