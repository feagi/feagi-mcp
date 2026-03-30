# FEAGI MCP - Getting Started in 3 Minutes

The absolute fastest way to get FEAGI MCP running.

## Prerequisites Check

Before starting, verify:
- [ ] Python 3.10+ installed: `python3 --version`
- [ ] FEAGI running: `curl http://localhost:8000/v1/genome/name`
- [ ] Cursor IDE installed (or Claude Desktop)

---

## Installation (60 seconds)

```bash
# Navigate to project
cd /Users/nadji/code/FEAGI-2.0/feagi-mcp

# Quick install (automated)
./install.sh

# Or manual:
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

**Verify:**
```bash
python scripts/verify_install.py
```

Expected: "✅ FEAGI MCP is correctly installed!"

---

## Configure Cursor (30 seconds)

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

**Important:** Update `cwd` path to match your installation location.

**Restart Cursor** after saving.

---

## First Test (30 seconds)

Open Cursor and ask:

> Check FEAGI health and list all cortical areas

If working, you'll see:
```
FEAGI is running with genome "..."
Found X cortical areas:
- CPG_Diagonal_A (CUSTOM)
- Hip_FL (CUSTOM)
- ...
```

---

## What You Can Do Now

### Inspect Circuits
> "Show me how the CPG areas are connected"
> "What parameters does CPG_Diagonal_A use?"
> "Trace the signal path from CPG to motor output"

### Debug Issues
> "Why isn't my robot moving?"
> "Are the CPGs connected to the motor output?"
> "What's the embodiment status?"

### Design Circuits
> "Design a reaching controller for a 3-DOF arm"
> "Validate this genome before I upload it"

### Learn
> "Explain how the walking genome works"
> "What's a Central Pattern Generator?"
> "Show me all available circuit templates"

---

## Common Issues

**"MCP server not found in Cursor"**
- Check `cwd` path in config matches your installation
- Try absolute path to Python: `/path/to/venv/bin/python`
- Restart Cursor

**"Connection refused"**
- Verify FEAGI is running: `curl http://localhost:8000/v1/genome/name`
- Check port matches in `.env` and Cursor config

**"Tool calls return errors"**
- Some tools await FEAGI API implementation (see STATUS.md)
- Use fallbacks: Brain Visualizer for monitoring
- Check tool status in docs/TOOL_CATALOG.md

---

## Next Steps

Once working:
1. Try the Spot walking example: `docs/SPOT_WALKING_EXAMPLE.md`
2. Read tool catalog: `docs/TOOL_CATALOG.md`
3. Explore circuit templates: `docs/CIRCUIT_TEMPLATES.md`

---

## Need Help?

- **Quick questions:** See `docs/FAQ.md`
- **Tool reference:** See `docs/API_REFERENCE.md`
- **Issues:** https://github.com/Neuraville/feagi-mcp/issues
- **Discord:** https://discord.gg/feagi

---

**Total time: 3 minutes**

Now start designing neural circuits with AI assistance!
