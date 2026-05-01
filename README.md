# FEAGI MCP Server

Model Context Protocol (MCP) server for FEAGI neural monitoring and control. Enables LLMs to observe brain activity, design neural circuits, and debug neurorobotic systems in real-time.

## Features

### Monitoring & Observation
- **Monitor cortical activity** - Real-time firing rates, spike patterns, and neuron states
- **Trace signal paths** - Verify connectivity between cortical areas
- **Inspect embodiment** - Check controller registration, motor/sensor mappings
- **Analyze connectivity** - Examine synaptic connections and morphologies

### Circuit Building
- **Stimulate areas** - Trigger specific cortical regions for testing
- **Validate circuits** - Check genome structure and parameter sanity
- **Get area parameters** - Inspect neuron properties and dimensions

### Genome Management
- **Upload genomes** - Load neural architectures into running FEAGI
- **Download genomes** - Retrieve current brain configuration
- **List areas** - Enumerate all cortical regions

### Composer integration (optional)
- **Simulator asset packs** - List/resolve/download shared packs from Composer when `FEAGI_COMPOSER_BASE_URL` is set

## Installation

```bash
# From PyPI
pip install feagi-mcp

# Or install from a source checkout (editable)
cd feagi-mcp
pip install -e .

# Or with uv
uv pip install -e .
```

## Usage

### Standalone Server (stdio)

```bash
feagi-mcp
```

### With Configuration

```bash
export FEAGI_HOST=localhost
export FEAGI_PORT=8000
# Optional: Composer public API (shared simulator packs, embodiment metadata APIs, etc.)
export FEAGI_COMPOSER_BASE_URL=https://us-staging-composer.brainsforrobots.com
feagi-mcp
```

### Cursor Integration

Add to your Cursor MCP settings (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "feagi": {
      "command": "python",
      "args": ["-m", "feagi_mcp.server"],
      "env": {
        "FEAGI_HOST": "localhost",
        "FEAGI_PORT": "8000",
        "FEAGI_COMPOSER_BASE_URL": "https://us-staging-composer.brainsforrobots.com"
      }
    }
  }
}
```

## Available Tools

### Agent Introspection
- `get_registered_agents` - List all connected agents (controllers, embodiments)
- `get_agent_properties` - Get agent type, capabilities, version, connection info
- `get_agent_device_registrations` - Inspect motor/sensor structure, group_ids, control modes

### Monitoring
- `monitor_activity` - Get real-time firing rates for a cortical area
- `get_connectivity` - Inspect synaptic connections between areas
- `trace_signal_path` - Verify signal propagation paths
- `get_embodiment_status` - Check controller connections and mappings
- `get_area_parameters` - Inspect neuron properties
- `get_cortical_synapse_counts` - Get incoming/outgoing synapse counts

### Genome Editing (NEW)
- `create_cortical_area` - Add OPU/IPU/CUSTOM/MEMORY areas programmatically (CUSTOM/MEMORY require `brain_region_id`; MCP enforces origin/label spacing unless skipped). **Naming:** use intuitive role/circuit names; never prefix with `Mcp` — see `docs/NEW_TOOLS.md` (Cortical area naming policy).
- `update_cortical_area` - Modify cortical area properties
- `delete_cortical_area` - Remove cortical areas
- `list_opu_areas` - List only motor output areas
- `list_ipu_areas` - List only sensory input areas
- `list_opu_areas_with_metadata` - List OPU areas with semantic type/purpose/capabilities info
- `list_ipu_areas_with_metadata` - List IPU areas with semantic type/purpose/capabilities info
- `get_area_semantic_info` - Get detailed semantic information about any cortical area

### Connection Management (NEW)
- `get_cortical_mapping` - Get connection configuration between two areas
- `update_cortical_mapping` - Create/update connections with morphology rules
- `delete_cortical_mapping` - Remove connections between areas

### Composer shared simulator packs (optional)
Set `FEAGI_COMPOSER_BASE_URL` to the Composer HTTPS root (e.g. staging). Read-only routes under `/v1/public/global/simulator-packs`.
- `composer_list_simulator_packs` - Catalog with optional filters (`engine`, `kind`, `state`)
- `composer_get_simulator_pack_versions` - Version index for a `pack_id`
- `composer_get_simulator_pack_resolved` - Resolved manifest and per-file HTTPS URLs (GCS)
- `composer_download_simulator_pack_bundle` - Fetch every listed file into a local directory for MJCF `include` wiring (MuJoCo still requires XML edit + model reload)

### Brain Visualizer parity (full REST router)
- `list_brain_visualizer_operations` - Index of every supported `operation_id` with HTTP method and path (same surface as `FEAGIHTTPAddressList.gd`)
- `brain_visualizer_api` - Call any whitelisted operation: genome (save, amalgamation, circuits), cortical areas (geometry, properties, multi-put, reset, clone), regions (CRUD, relocate, clone), morphologies (CRUD, rename, usage), cortical mappings (afferents, efferents, batch), burst engine, system visualization tuning, neuroplasticity, insight/monitoring, agents (register, heartbeat, stimulation, device registrations), network, vision input. Use `path_params` for `{agent_id}` / `{region_id}` routes; for amalgamation-by-upload use `post_genome_amalgamation_by_upload_multipart` with `json_body: {\"genome_json\": \"...\"}`.
- **Voxel / neuron inspection:** For a specific cortical area and voxel `(x,y,z)`—neuron details, incoming/outgoing synapses at that voxel, or debugging—use `operation_id` **`get_cortical_area_voxel_neurons`** (GET `/v1/cortical_area/voxel_neurons`) with `query`: `cortical_id`, `x`, `y`, `z`, optional `synapse_page`.

### Control
- `stimulate_area` - Trigger neurons for testing
- `upload_genome` - Load a new brain architecture
- `download_genome` - Retrieve current genome

### Inspection
- `list_cortical_areas` - Enumerate all brain regions
- `get_genome_info` - Get metadata about current genome
- `validate_genome` - Check genome structure for issues
- `get_burst_engine_status` - Check burst engine state
- `get_runtime_metrics` - Get comprehensive runtime metrics

## Example: LLM-Assisted Circuit Design

```python
# LLM can now:
# 1. Monitor CPG oscillation
activity = await monitor_activity(area_id="cCPGa_", duration_ms=1000)
# Returns: {"firing_rate": 5.2, "active_neurons": [0,1,2,3,4], "period_ms": 192}

# 2. Verify connections
conn = await get_connectivity(src_area="cCPGa_", dst_area="cHipFL")
# Returns: {"synapse_count": 150, "morphology": "cpg_to_hip_x", "avg_weight": 18.0}

# 3. Check motor output
status = await get_embodiment_status()
# Returns: {"motor_cortical_id": "opose0", "device_count": 12, "last_packet_ms": 42}

# 4. Debug with stimulation
result = await stimulate_area(area_id="cStart", coords=[0,0,0], potential=1.0)
# Trigger walking behavior for testing
```

## Architecture

```
feagi-mcp/
├── src/feagi_mcp/
│   ├── __init__.py
│   ├── server.py          # Main MCP server with tool definitions
│   ├── feagi_client.py    # HTTP client for FEAGI REST API
│   ├── config.py          # Configuration management
│   └── tools/             # Individual tool implementations
│       ├── monitoring.py
│       ├── control.py
│       └── genome.py
├── tests/
│   ├── test_server.py
│   └── test_feagi_client.py
├── examples/
│   └── circuit_design.py
├── pyproject.toml
└── README.md
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check .
ruff format .
mypy src/
```

## Requirements

- Python 3.10+
- Running FEAGI instance (default: localhost:8000)
- MCP-compatible client (Cursor, Claude Desktop)

## License

Apache-2.0 - Copyright 2026 Neuraville Inc.

## Support

- Issues: https://github.com/Neuraville/feagi-mcp/issues
- Discord: https://discord.gg/PTVC8fyGN8
