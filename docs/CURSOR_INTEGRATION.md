# Cursor Integration Guide

This guide shows how to integrate the FEAGI MCP server with Cursor for LLM-assisted neural circuit design.

## Quick Setup

### 1. Install FEAGI MCP

```bash
cd /Users/nadji/code/FEAGI-2.0/feagi-mcp
python -m venv venv
source venv/bin/activate
pip install -e .
```

### 2. Configure Cursor

Open Cursor settings and add the MCP server configuration.

**Method 1: Via Cursor Settings UI**
1. Open Cursor Settings (Cmd+,)
2. Search for "MCP"
3. Click "Edit in settings.json"
4. Add the FEAGI server configuration

**Method 2: Direct JSON Edit**

Edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "feagi": {
      "command": "python",
      "args": [
        "-m",
        "feagi_mcp.server"
      ],
      "cwd": "/Users/nadji/code/FEAGI-2.0/feagi-mcp",
      "env": {
        "FEAGI_HOST": "localhost",
        "FEAGI_PORT": "8000"
      }
    }
  }
}
```

### 3. Verify Installation

Restart Cursor, then ask the AI:

> "Use the FEAGI MCP to check if FEAGI is running"

The AI should be able to call `health_check()` and report back.

## Example Workflows

### Workflow 1: Debug Walking Genome

```
You: "Why isn't my Spot robot moving?"

AI uses:
1. health_check() - Verify FEAGI is running
2. get_embodiment_status() - Check controller connection
3. list_cortical_areas() - Find CPG and motor areas
4. monitor_activity("cCPGa_", 2000) - Check if CPGs are oscillating
5. get_connectivity("cCPGa_", "cHipFL") - Verify connections
6. monitor_activity("opose0", 1000) - Check motor output
7. Reports: "CPGs are firing but no connection to OPU - missing synapse"
```

### Workflow 2: Design New Circuit

```
You: "Build a genome for arm reaching with 3 DOF"

AI uses:
1. list_cortical_areas() - See existing areas for reference
2. download_genome() - Get current structure as template
3. Designs new genome with reach controller
4. validate_genome(new_genome_json) - Check for issues
5. upload_genome(new_genome_json) - Load into FEAGI
6. monitor_activity("reach_controller", 1000) - Verify it works
7. get_connectivity("visual_target", "reach_controller") - Check sensorimotor integration
```

### Workflow 3: Iterative Tuning

```
You: "The CPG is oscillating too fast, slow it down"

AI uses:
1. monitor_activity("cCPGa_", 3000) - Measure current frequency (8Hz)
2. download_genome() - Get current parameters
3. Identifies leak_coefficient=24.0 is too high
4. Modifies genome: leak_coefficient=18.0
5. upload_genome(modified) - Reload
6. monitor_activity("cCPGa_", 3000) - Verify new frequency (5Hz)
7. Reports: "Slowed from 8Hz to 5Hz by reducing leak coefficient"
```

## Available Tools Reference

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `health_check` | Verify FEAGI is running | Start of every session |
| `monitor_activity` | Observe neural firing | Debug circuits, verify oscillations |
| `get_connectivity` | Check synaptic connections | Verify circuit topology |
| `get_area_parameters` | Inspect neuron properties | Understand existing circuits |
| `get_embodiment_status` | Check robot connection | Debug motor/sensor issues |
| `list_cortical_areas` | Enumerate brain regions | Explore architecture |
| `trace_signal_path` | Find propagation paths | Debug signal flow |
| `stimulate_area` | Test circuits | Trigger behaviors for testing |
| `validate_genome` | Check genome structure | Before uploading |
| `upload_genome` | Load new architecture | Deploy circuits |
| `download_genome` | Get current config | Baseline for modifications |

## Tips for Effective Use

### 1. Always Check Health First
Before designing circuits, verify FEAGI is running:
```
"Check FEAGI health and show me current genome info"
```

### 2. Monitor Before and After
Verify changes had the intended effect:
```
"Monitor CPG_Diagonal_A activity before and after I stimulate WalkStart"
```

### 3. Trace Problematic Paths
If signals aren't reaching their destination:
```
"Trace the signal path from CPG_Diagonal_A to Spot_Joint_Control"
```

### 4. Validate Before Upload
Catch errors early:
```
"Validate this genome JSON before uploading: [paste JSON]"
```

### 5. Use Embodiment Status for Motor Debugging
```
"Check embodiment status and tell me if motor commands are reaching the controller"
```

## Troubleshooting

### "FEAGI MCP not found"
- Check `~/.cursor/mcp.json` exists and is valid JSON
- Verify Python path in configuration
- Restart Cursor after changes

### "Connection refused"
- Ensure FEAGI is running on the specified host/port
- Check firewall settings
- Try `curl http://localhost:8000/v1/genome/name` to verify

### "Tool call failed"
- Check FEAGI logs for errors
- Verify the cortical area ID exists: `list_cortical_areas()`
- Some API endpoints may not be implemented yet (see DEVELOPMENT.md)

## Advanced: Custom Tool Development

To add FEAGI-specific tools for your use case:

1. Add method to `FeagiClient` in `feagi_client.py`:
```python
async def my_custom_api(self, param: str) -> dict[str, Any]:
    response = await self._client.get(f"{self.base_url}/v1/custom/{param}")
    return response.json()
```

2. Add tool definition in `server.py`:
```python
@mcp.tool()
async def my_custom_tool(param: str) -> dict[str, Any]:
    """Description for LLM."""
    return await feagi.my_custom_api(param)
```

3. Restart the MCP server in Cursor

## Future Enhancements

- **WebSocket Support** - Real-time activity streaming
- **Batch Operations** - Multiple stimulations or queries
- **Circuit Templates** - Pre-built patterns (CPGs, FFNs, etc.)
- **Performance Profiling** - Circuit timing analysis
- **Visual Diff** - Compare genome versions

## Questions?

- Email: feagi@neuraville.com
- Discord: https://discord.gg/feagi
- GitHub Discussions: https://github.com/Neuraville/feagi-mcp/discussions
