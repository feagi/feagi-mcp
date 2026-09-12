# FEAGI MCP API Reference

Complete reference for all available tools.

## Connection & Health

### health_check()

Check FEAGI server connectivity and retrieve basic status.

**Parameters:** None

**Returns:**
```python
{
    "status": "ok" | "error",
    "genome_name": str,  # Name of loaded genome
    "message": str,  # Error message if failed
}
```

**Example:**
```python
result = await health_check()
# {"status": "ok", "genome_name": "spot_walking_genome"}
```

**Use when:**
- Starting a new session
- Verifying FEAGI is reachable
- After FEAGI restart

---

## Monitoring Tools

### monitor_activity(area_id: str, duration_ms: int = 1000)

Monitor real-time neural activity in a cortical area.

**Parameters:**
- `area_id` (str, required): Cortical area identifier (e.g., "cCPGa_", "opose0")
- `duration_ms` (int, optional): Monitoring duration in milliseconds, default 1000

**Returns:**
```python
{
    "firing_rate": float,  # Average Hz
    "active_neurons": list[int],  # Indices of firing neurons
    "spike_timestamps": list[float],  # Timing data
    "period_ms": float,  # For oscillators
    "error": str,  # If failed
}
```

**Example:**
```python
activity = await monitor_activity("cCPGa_", 2000)
# {
#   "firing_rate": 5.2,
#   "active_neurons": [0, 1, 2, 3, 4],
#   "period_ms": 192
# }
```

**Use when:**
- Verifying CPG oscillations
- Checking if stimulation worked
- Debugging why circuits aren't firing
- Measuring oscillation frequency

---

### get_connectivity(src_area: str, dst_area: str)

Examine synaptic connections between two cortical areas.

**Parameters:**
- `src_area` (str, required): Source area ID
- `dst_area` (str, required): Destination area ID

**Returns:**
```python
{
    "connected": bool,
    "synapse_count": int,
    "connections": list[dict],  # Connection details
    "src_area": str,
    "dst_area": str,
    "error": str,  # If failed
}
```

**Connection details:**
```python
{
    "morphology_id": str,  # e.g., "cpg_to_hip_x"
    "morphology_scalar": list[int],  # [x, y, z] scaling
    "postSynapticCurrent_multiplier": float,  # Synaptic weight
    "plasticity_flag": bool,
}
```

**Example:**
```python
conn = await get_connectivity("cCPGa_", "cHipFL")
# {
#   "connected": true,
#   "synapse_count": 3,
#   "connections": [
#     {"morphology_id": "cpg_to_hip_x", "postSynapticCurrent_multiplier": 18.0},
#     {"morphology_id": "cpg_to_hip_y", "postSynapticCurrent_multiplier": 20.0},
#     {"morphology_id": "cpg_to_knee", "postSynapticCurrent_multiplier": 22.0}
#   ]
# }
```

**Use when:**
- Verifying circuit topology is correct
- Debugging signal flow issues
- Inspecting synaptic weights
- Finding missing connections

---

### trace_signal_path(from_area: str, to_area: str, max_hops: int = 5)

Find all possible paths between two cortical areas through intermediate connections.

**Parameters:**
- `from_area` (str, required): Source area ID
- `to_area` (str, required): Destination area ID
- `max_hops` (int, optional): Maximum path length, default 5

**Returns:**
```python
{
    "from_area": str,
    "to_area": str,
    "paths_found": int,
    "paths": list[list[str]],  # Each path is list of area IDs
    "connected": bool,
    "error": str,
}
```

**Example:**
```python
paths = await trace_signal_path("cCPGa_", "opose0")
# {
#   "from_area": "cCPGa_",
#   "to_area": "opose0",
#   "paths_found": 1,
#   "paths": [["cCPGa_", "cHipFL", "opose0"]],
#   "connected": true
# }
```

**Use when:**
- Debugging why signals aren't reaching destination
- Understanding circuit architecture
- Verifying multi-hop pathways
- Finding bottlenecks

---

## Cortical Area Inspection

### list_cortical_areas(name_contains=None, cortical_id_contains=None, cortical_type=None, limit=None)

List cortical areas as compact catalog rows. Filtering is local after one
FEAGI list fetch. Prefer filters; an unfiltered call returns every area.

**Parameters:**
- `name_contains` (str, optional): Case-insensitive substring of the area title
- `cortical_id_contains` (str, optional): Case-insensitive substring of `cortical_id` or `cortical_id_s`
- `cortical_type` (str, optional): Exact type match against `cortical_type`, `cortical_group`, or `area_type`. Allowed: IPU, OPU, CORE, CUSTOM, MEMORY, SENSORY, MOTOR
- `limit` (int, optional): Maximum rows after filtering

**Returns:**
```python
[
    {
        "name": str,  # Human-readable name
        "cortical_id": str,  # Wire ID
        "cortical_id_s": str,  # ASCII unit id when present
        "cortical_group": str,  # IPU, OPU, CUSTOM, CORE, MEMORY
        "cortical_type": str,
        "cortical_dimensions": list[int],  # [x, y, z]
        "neuron_count": int,
        "parent_region_id": str | None,
    },
    ...,
]
```

**Example:**
```python
areas = await list_cortical_areas(name_contains="Speed")
# [
#   {"name": "Spatial Pointer Speed", "cortical_id": "...", "cortical_dimensions": [3,1,100]},
#   {"name": "Positional Servo Speed", "cortical_id": "...", "cortical_dimensions": [6,1,50]}
# ]
```

**Use when:**
- Finding a named area without dumping the genome
- Getting IDs for inspect / stimulate tools
- Exploring a new genome (unfiltered, only when the full catalog is required)

---

### get_area_parameters(area_id: str)

Get complete parameter set for a cortical area.

**Parameters:**
- `area_id` (str, required): Cortical area identifier

**Returns:**
```python
{
    "area_id": str,
    "parameters": {
        "__name-t": str,            # Area name
        "_group-t": str,            # IPU/OPU/CUSTOM/etc
        "___bbx-i": int,            # X dimension
        "___bby-i": int,            # Y dimension
        "___bbz-i": int,            # Z dimension
        "excite-f": float,          # Excitability
        "fire_t-f": float,          # Fire threshold
        "leak_c-f": float,          # Leak coefficient
        "pstcr_-f": float,          # Post-synaptic current
        "dstmap-d": dict,           # Destination connections
        ...
    }
}
```

**Example:**
```python
params = await get_area_parameters("cCPGa_")
# {
#   "area_id": "cCPGa_",
#   "parameters": {
#     "__name-t": "CPG_Diagonal_A",
#     "leak_c-f": 18.0,
#     "fire_t-f": 0.05,
#     "excite-f": 80.0
#   }
# }
```

**Use when:**
- Inspecting existing circuits
- Comparing parameter values
- Debugging neuron behavior
- Before modifying parameters

---

## Control & Stimulation

### stimulate_area(area_id: str, coordinates: list[int], potential: float, duration_ms: int = 100)

Inject spikes or continuous potential into specific neurons for testing.

**Parameters:**
- `area_id` (str, required): Cortical area identifier
- `coordinates` (list[int], required): [x, y, z] neuron coordinates
- `potential` (float, required): Stimulation value (typically 0.0 to 1.0)
- `duration_ms` (int, optional): Stimulation duration, default 100

**Returns:**
```python
{"success": bool, "neurons_activated": int, "message": str, "error": str}
```

**Example:**
```python
# Trigger walking by stimulating WalkStart area
result = await stimulate_area("cStart", [0, 0, 0], 1.0, 500)
# {"success": true, "message": "Stimulation sent"}
```

**Use when:**
- Testing if CPGs start oscillating
- Triggering behavior for debugging
- Verifying circuit responsiveness
- Manual activation of controllers

---

## Embodiment & I/O

### get_embodiment_status()

Get status of connected controllers and their I/O mappings.

**Parameters:** None

**Returns:**
```python
{
    "status": str,
    "opu_areas": list[dict],  # Motor output areas
    "ipu_areas": list[dict],  # Sensory input areas
    "connected_agents": list[dict],  # Active controllers
    "message": str,
}
```

**OPU/IPU structure:**
```python
{
    "name": str,  # Human-readable name
    "id": str,  # Cortical ID
    "device_count": int,  # Number of channels
    "last_activity_ms": int,  # Time since last packet
}
```

**Example:**
```python
status = await get_embodiment_status()
# {
#   "opu_areas": [
#     {"name": "Spot_Joint_Control", "id": "opose0", "device_count": 12}
#   ],
#   "ipu_areas": [
#     {"name": "Joint_Pos_Sensor", "id": "iipro0", "device_count": 24}
#   ]
# }
```

**Use when:**
- Debugging why robot isn't moving
- Verifying controller connection
- Checking motor/sensor mappings
- Investigating I/O issues

---

## Genome Management

### get_genome_info()

Get metadata about the currently loaded genome.

**Parameters:** None

**Returns:**
```python
{"genome_name": str, "status": str, "error": str}
```

---

### download_genome()

Download the complete genome configuration.

**Parameters:** None

**Returns:**
```python
{
    "genome_title": str,
    "version": str,
    "blueprint": dict,  # All cortical areas and connections
    "neuron_morphologies": dict,  # Synapse patterns
    "brain_regions": dict,  # Hierarchical grouping
    "physiology": dict,  # Global parameters
    "stats": dict,  # Counts and metrics
    "error": str,
}
```

**Use when:**
- Inspecting current architecture
- Creating modified versions
- Baseline for new designs
- Debugging circuit structure

---

### upload_genome(genome_json: str)

Upload a new genome to FEAGI.

**Parameters:**
- `genome_json` (str, required): Complete genome as JSON string

**Returns:**
```python
{
    "success": bool,
    "message": str,
    "cortical_area_count": int,
    "brain_region_count": int,
    "error": str,
}
```

**Example:**
```python
with open("my_brain.genome") as f:
    genome_str = f.read()
    
result = await upload_genome(genome_str)
# {
#   "success": true,
#   "cortical_area_count": 12,
#   "message": "Genome uploaded successfully"
# }
```

**Use when:**
- Loading new neural architectures
- Applying circuit modifications
- Switching between genome versions
- Testing new designs

---

### validate_genome(genome_json: str)

Validate genome structure without uploading.

**Parameters:**
- `genome_json` (str, required): Genome JSON string

**Returns:**
```python
{
    "valid": bool,
    "issues": list[str],  # Critical problems
    "warnings": list[str],  # Non-critical concerns
    "cortical_area_count": int,
}
```

**Example:**
```python
result = await validate_genome(genome_json)
# {
#   "valid": false,
#   "issues": ["Missing required key: neuron_morphologies"],
#   "warnings": ["Connection to undefined area: test123"]
# }
```

**Use when:**
- Before uploading new genomes
- Catching structural errors early
- Verifying connectivity
- Debugging upload failures

---

## Voxel and neuron inspection (`GET /v1/cortical_area/voxel_neurons`)

Use **`brain_visualizer_api`** when the user asks to inspect a **specific voxel** or **neuron(s)** inside a **cortical area**, including:

- Neuron-level properties at that coordinate (same live snapshot style as connectome neuron views)
- **Incoming and outgoing synapse** detail for neurons in that voxel (paginated)
- **Debugging** connectivity or behavior at a given `(x, y, z)` in an area

**Parameters (query string):**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `cortical_id` | Yes | Cortical area ID (base64 string from genome / `list_cortical_areas`) |
| `x`, `y`, `z` | Yes | Voxel indices within that area |
| `synapse_page` | No | 0-based page index for synapse detail lists (incoming and outgoing per page) |

**MCP call:**

- `operation_id`: `get_cortical_area_voxel_neurons`
- `query`: `{ "cortical_id": "<id>", "x": 0, "y": 0, "z": 0, "synapse_page": 0 }`

Resolve the cortical ID with **`list_cortical_areas`** (or genome tools) if the user gave a name instead of an ID.

---

## Error Handling

All tools return dictionaries that may include an `"error"` key:

```python
{
    "error": str,       # Error type or HTTP status
    "message": str,     # Human-readable description
    ...                 # Tool-specific fields
}
```

Always check for `"error"` in responses:

```python
result = await monitor_activity("invalid_id")
if "error" in result:
    print(f"Failed: {result['message']}")
```

## Common Error Types

| Error | Cause | Solution |
|-------|-------|----------|
| `"request_failed"` | Network/connection issue | Check FEAGI is running |
| `"invalid_json"` | Malformed genome JSON | Validate JSON structure |
| `"HTTP 404"` | API endpoint doesn't exist | Endpoint not implemented yet |
| `"HTTP 500"` | FEAGI internal error | Check FEAGI logs |
| `"Area X not found"` | Invalid cortical ID | Use `list_cortical_areas()` first |

## Rate Limits

- No explicit rate limits
- Avoid rapid-fire calls (<100ms apart)
- Use appropriate `duration_ms` for monitoring (1000-3000ms typical)

## Timeouts

- Default: 30 seconds per request
- Configurable via `FEAGI_TIMEOUT_SECONDS` environment variable
- Genome uploads may take longer for large architectures

## Future API Additions

These tools are defined but await FEAGI API implementation:

- `get_motor_output_stream()` - Real-time motor command monitoring
- `get_sensory_input_stream()` - Real-time sensor data inspection
- `update_parameter()` - Temporary parameter tuning
- `compare_genomes()` - Diff two genome architectures
- `profile_circuit()` - Performance analysis
- `detect_patterns()` - Identify common circuit motifs

See [DEVELOPMENT.md](../DEVELOPMENT.md) for roadmap.
