# FEAGI MCP Tool Catalog

Complete reference of all available tools, organized by category.

## Quick Reference

| Category | Tool Count | Key Use Cases |
|----------|------------|---------------|
| [Monitoring](#monitoring-tools) | 2 | Observe neural activity, verify circuits |
| [Inspection](#inspection-tools) | 4 | Analyze connections, trace paths, get parameters |
| [Control](#control-tools) | 1 | Stimulate neurons for testing |
| [Genome](#genome-tools) | 4 | Upload/download/validate architectures |
| [Utility](#utility-tools) | 1 | Health checks, connectivity |

**Total: 12 tools**

---

## Monitoring Tools

### monitor_activity
**Category:** Monitoring  
**Purpose:** Observe real-time neural firing in cortical areas  
**Signature:** `(area_id: str, duration_ms: int = 1000) -> dict`

**When to use:**
- Verify CPG oscillations are happening
- Check if stimulation triggered activity
- Measure oscillation frequency
- Debug silent circuits

**Example:**
```python
activity = await monitor_activity("cCPGa_", 2000)
# Returns firing_rate, active_neurons, spike_timestamps
```

**Status:** Awaiting FEAGI API `/v1/monitor/cortical_activity`

---

### get_embodiment_status
**Category:** Monitoring  
**Purpose:** Check robot controller connections and I/O mappings  
**Signature:** `() -> dict`

**When to use:**
- Debug why robot isn't moving
- Verify controller is connected
- Check motor/sensor cortical ID mappings
- Confirm device counts match genome

**Example:**
```python
status = await get_embodiment_status()
# Returns opu_areas, ipu_areas, connected_agents
```

**Status:** Fallback to genome analysis (API endpoint pending)

---

## Inspection Tools

### get_connectivity
**Category:** Inspection  
**Purpose:** Examine synaptic connections between areas  
**Signature:** `(src_area: str, dst_area: str) -> dict`

**When to use:**
- Verify circuit topology is correct
- Check if connections were created
- Inspect synaptic weights
- Debug signal flow issues

**Example:**
```python
conn = await get_connectivity("cCPGa_", "cHipFL")
# Returns connected, synapse_count, morphologies, weights
```

**Status:** Fully functional

---

### trace_signal_path
**Category:** Inspection  
**Purpose:** Find multi-hop propagation paths  
**Signature:** `(from_area: str, to_area: str, max_hops: int = 5) -> dict`

**When to use:**
- Debug why signals aren't reaching destination
- Understand information flow
- Find bottlenecks or missing links
- Verify multi-layer architectures

**Example:**
```python
paths = await trace_signal_path("cCPGa_", "opose0")
# Returns all paths, intermediate areas, connectivity status
```

**Status:** Fully functional

---

### get_area_parameters
**Category:** Inspection  
**Purpose:** Get complete parameter set for a cortical area  
**Signature:** `(area_id: str) -> dict`

**When to use:**
- Inspect existing circuit designs
- Understand neuron behavior
- Compare parameter values
- Debug oscillation or firing issues

**Example:**
```python
params = await get_area_parameters("cCPGa_")
# Returns dimensions, leak_coefficient, fire_threshold, connections, etc.
```

**Status:** Fully functional

---

### list_cortical_areas
**Category:** Inspection  
**Purpose:** Enumerate cortical areas as compact catalog rows  
**Signature:** `(name_contains=None, cortical_id_contains=None, cortical_type=None, limit=None) -> list[dict]`

**When to use:**
- Find a named area or ID without dumping the genome
- Explore new genomes (unfiltered only when the full catalog is required)
- Get IDs for inspect / stimulate tools

**Example:**
```python
areas = await list_cortical_areas(name_contains="Speed", cortical_type="OPU")
# Returns matching catalog rows: name, id, type, dimensions
```

**Status:** Fully functional

---

## Control Tools

### stimulate_area
**Category:** Control  
**Purpose:** Inject spikes into neurons for testing  
**Signature:** `(area_id: str, coordinates: list[int], potential: float, duration_ms: int = 100) -> dict`

**When to use:**
- Trigger CPGs to start oscillating
- Test if circuits respond to input
- Activate behavior controllers
- Manual circuit debugging

**Example:**
```python
result = await stimulate_area("cStart", [0, 0, 0], 1.0, 500)
# Triggers walking behavior
```

**Status:** Awaiting FEAGI API `/v1/stimulate`

---

## Genome Tools

### upload_genome
**Category:** Genome Management  
**Purpose:** Load new neural architecture into FEAGI  
**Signature:** `(genome_json: str) -> dict`

**When to use:**
- Deploy new circuit designs
- Apply modifications
- Load different architectures
- Test genome versions

**Example:**
```python
with open("my_brain.genome") as f:
    result = await upload_genome(f.read())
# Returns success, cortical_area_count, brain_region_count
```

**Status:** Fully functional

---

### download_genome
**Category:** Genome Management  
**Purpose:** Retrieve complete genome configuration  
**Signature:** `() -> dict`

**When to use:**
- Inspect current architecture
- Create baseline for modifications
- Analyze existing circuits
- Backup current design

**Example:**
```python
genome = await download_genome()
# Returns complete genome: blueprint, morphologies, regions, etc.
```

**Status:** Fully functional

---

### validate_genome
**Category:** Genome Management  
**Purpose:** Check genome structure before upload  
**Signature:** `(genome_json: str) -> dict`

**When to use:**
- Before uploading to catch errors early
- Verify connections are valid
- Check for missing required fields
- Debug upload failures

**Example:**
```python
result = await validate_genome(genome_json_str)
# Returns valid (bool), issues[], warnings[]
```

**Status:** Fully functional

---

### get_genome_info
**Category:** Genome Management  
**Purpose:** Get current genome metadata  
**Signature:** `() -> dict`

**When to use:**
- Quick status check
- Verify genome loaded correctly
- Get basic statistics

**Example:**
```python
info = await get_genome_info()
# Returns genome_name, version, status
```

**Status:** Fully functional

---

## Utility Tools

### health_check
**Category:** Utility  
**Purpose:** Verify FEAGI connectivity  
**Signature:** `() -> dict`

**When to use:**
- Start of every session
- After FEAGI restart
- Diagnose connection issues
- Verify configuration

**Example:**
```python
health = await health_check()
# Returns status, genome_name
```

**Status:** Fully functional

---

## Tool Combinations

### Common Workflows

**Debug Non-Moving Robot:**
```python
1. health_check()
2. get_embodiment_status()
3. monitor_activity(opu_id)
4. trace_signal_path(cpg_id, opu_id)
```

**Design New CPG Circuit:**
```python
1. download_genome()  # Baseline
2. [Modify genome with new CPG]
3. validate_genome(new_genome)
4. upload_genome(new_genome)
5. monitor_activity(cpg_id)
```

**Tune Oscillation Frequency:**
```python
1. monitor_activity(cpg_id)  # Measure current
2. get_area_parameters(cpg_id)  # Check leak coefficient
3. [Adjust leak in genome]
4. upload_genome(modified)
5. monitor_activity(cpg_id)  # Verify change
```

**Verify Circuit Topology:**
```python
1. list_cortical_areas()
2. get_connectivity(src, dst)  # Each connection
3. trace_signal_path(input, output)  # End-to-end
```

---

## Tool Status Legend

- **Fully functional**: Implemented and tested
- **Awaiting FEAGI API**: Tool defined, waiting for server endpoint
- **Fallback implemented**: Works via alternative method when primary API unavailable

---

## Future Tools (Roadmap)

### Phase 2: Real-time Streams
- `stream_activity` - WebSocket-based continuous monitoring
- `stream_motor_output` - Real-time motor command observation
- `stream_sensory_input` - Real-time sensor data inspection

### Phase 3: Advanced Analysis
- `compare_genomes` - Diff two architectures
- `profile_circuit` - Performance and timing analysis
- `detect_patterns` - Identify common motifs (CPGs, FFNs, etc.)
- `suggest_parameters` - AI-assisted parameter tuning

### Phase 4: Batch Operations
- `batch_stimulate` - Multiple simultaneous stimulations
- `batch_monitor` - Monitor multiple areas in parallel
- `circuit_health_check` - Comprehensive diagnostic suite

---

## See Also

- [API Reference](API_REFERENCE.md) - Detailed parameter documentation
- [Quick Start](QUICKSTART.md) - Getting started guide
- [Circuit Templates](CIRCUIT_TEMPLATES.md) - Pre-built patterns
- [Cursor Integration](CURSOR_INTEGRATION.md) - IDE setup
