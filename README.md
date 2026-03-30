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

## Installation

```bash
# Install from source
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
        "FEAGI_PORT": "8000"
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
- `create_cortical_area` - Add OPU/IPU/CUSTOM/MEMORY areas programmatically
- `update_cortical_area` - Modify cortical area properties
- `delete_cortical_area` - Remove cortical areas
- `list_opu_areas` - List only motor output areas
- `list_ipu_areas` - List only sensory input areas

### Connection Management (NEW)
- `get_cortical_mapping` - Get connection configuration between two areas
- `update_cortical_mapping` - Create/update connections with morphology rules
- `delete_cortical_mapping` - Remove connections between areas

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

- Documentation: https://feagi.org
- Issues: https://github.com/Neuraville/feagi-mcp/issues
- Discord: https://discord.gg/feagi
