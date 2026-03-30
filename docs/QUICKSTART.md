# Quick Start Guide

Get started with FEAGI MCP in 5 minutes.

## Prerequisites

- Python 3.10 or higher
- Running FEAGI instance (typically localhost:8000)
- Cursor IDE or another MCP-compatible client

## Installation

### Step 1: Install Package

```bash
# Navigate to feagi-mcp directory
cd /Users/nadji/code/FEAGI-2.0/feagi-mcp

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install
pip install -e .
```

### Step 2: Test Connection

```bash
# Set FEAGI connection details
export FEAGI_HOST=localhost
export FEAGI_PORT=8000

# Run the server to verify it works
python -m feagi_mcp.server
```

You should see:
```
INFO Starting FEAGI MCP Server...
INFO Connecting to FEAGI at localhost:8000
```

Press Ctrl+C to stop.

### Step 3: Configure Cursor

**Option A: Automatic (Recommended)**

1. Open Cursor
2. Press Cmd+Shift+P (Mac) or Ctrl+Shift+P (Windows/Linux)
3. Type "MCP" and select "Add MCP Server"
4. Enter:
   - Name: `feagi`
   - Command: `python`
   - Args: `-m feagi_mcp.server`
   - Working Directory: `/Users/nadji/code/FEAGI-2.0/feagi-mcp`

**Option B: Manual**

Edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "feagi": {
      "command": "python",
      "args": ["-m", "feagi_mcp.server"],
      "cwd": "/Users/nadji/code/FEAGI-2.0/feagi-mcp",
      "env": {
        "FEAGI_HOST": "localhost",
        "FEAGI_PORT": "8000"
      }
    }
  }
}
```

**Restart Cursor** after configuration changes.

## First Test

### Verify MCP Integration

In Cursor, open a new chat and ask:

> "Check FEAGI health and tell me what genome is currently loaded"

If working correctly, the AI will call the `health_check` tool and report:
- FEAGI connection status
- Current genome name
- Available tools

### Example Session

```
You: "List all cortical areas in my current genome"
AI: [calls list_cortical_areas()]
    "Found 15 cortical areas:
     - CPG_Diagonal_A (CUSTOM)
     - CPG_Diagonal_B (CUSTOM)
     - Hip_FL (CUSTOM)
     - Spot_Joint_Control (OPU)
     ..."

You: "Monitor CPG_Diagonal_A activity for 2 seconds"
AI: [calls monitor_activity("cCPGa_", 2000)]
    "CPG_Diagonal_A is firing at 5.2 Hz with 5 active neurons..."

You: "Check if CPG_Diagonal_A connects to Hip_FL"
AI: [calls get_connectivity("cCPGa_", "cHipFL")]
    "Yes, found 150 synapses using morphology 'cpg_to_hip_x' with weight 18.0"
```

## What You Can Do

### Circuit Design
- Ask AI to design walking/reaching/grasping controllers
- AI can verify its designs by monitoring activity
- Iteratively tune parameters based on observed behavior

### Debugging
- "Why isn't my robot moving?"
- "Are the CPGs oscillating?"
- "Is the motor output reaching the controller?"

### Learning
- "Show me how the current genome implements walking"
- "What morphologies are used for motor control?"
- "How are the CPGs connected?"

## Next Steps

- Read [DEVELOPMENT.md](../DEVELOPMENT.md) for advanced usage
- See [examples/circuit_design.py](../examples/circuit_design.py) for code examples
- Check [docs/CURSOR_INTEGRATION.md](CURSOR_INTEGRATION.md) for detailed integration guide

## Troubleshooting

**"MCP server not found"**
- Verify Python path is correct in Cursor settings
- Make sure you installed with `pip install -e .`
- Try absolute path: `/path/to/venv/bin/python -m feagi_mcp.server`

**"Connection refused"**
- Check FEAGI is running: `curl http://localhost:8000/v1/genome/name`
- Verify port in .env or Cursor config matches FEAGI
- Check firewall settings

**"Tool calls fail"**
- Check FEAGI logs for errors
- Some endpoints may not be implemented yet
- Verify cortical area IDs are correct (use `list_cortical_areas` first)

## Support

Need help? Reach out:
- GitHub Issues: https://github.com/Neuraville/feagi-mcp/issues
- Discord: https://discord.gg/feagi
- Email: feagi@neuraville.com
