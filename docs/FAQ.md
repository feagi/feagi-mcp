# Frequently Asked Questions

## General Questions

### What is FEAGI MCP?

FEAGI MCP is a Model Context Protocol server that allows AI assistants (like Claude, GPT, etc.) to observe and control FEAGI neural systems in real-time. It's designed to enable LLM-assisted circuit design and debugging.

### Why do I need this?

Without MCP, you're designing neural circuits blindly - uploading genomes and hoping they work. With MCP, LLMs can:
- See what neurons are actually firing
- Verify connections exist
- Debug why circuits aren't working
- Iteratively tune parameters based on observation

### Is this production-ready?

No, this is v0.1.0 - an alpha release. It's functional for development and experimentation but lacks:
- Authentication/authorization
- Rate limiting
- Comprehensive error recovery
- Full test coverage

Use in trusted environments only.

---

## Installation & Setup

### What Python version do I need?

Python 3.10 or higher. Tested on 3.10, 3.11, 3.12, 3.13, and 3.14.

### Do I need FEAGI running?

Yes, you need a running FEAGI instance (typically localhost:8000). The MCP server connects to FEAGI's REST API.

### How do I configure the FEAGI connection?

Set environment variables:
```bash
export FEAGI_HOST=localhost
export FEAGI_PORT=8000
```

Or create a `.env` file (copy from `.env.example`).

### Can I connect to remote FEAGI?

Yes, set `FEAGI_HOST` to the remote IP/hostname. However:
- Use SSH tunnels for security (no built-in encryption)
- Beware of latency for monitoring tools
- Ensure firewall allows access

---

## Usage

### How do I use this in Cursor?

1. Install feagi-mcp: `pip install -e .`
2. Configure in `~/.cursor/mcp.json`
3. Restart Cursor
4. Ask AI to use FEAGI tools

See [docs/CURSOR_INTEGRATION.md](docs/CURSOR_INTEGRATION.md) for details.

### Can I use this with Claude Desktop?

Yes! Configure in Claude Desktop's MCP settings with the same JSON structure.

### Can I call tools directly from Python?

Yes:
```python
from feagi_mcp.feagi_client import FeagiClient
import asyncio

async def main():
    client = FeagiClient()
    result = await client.monitor_activity("cCPGa_", 1000)
    print(result)
    await client.close()

asyncio.run(main())
```

---

## Troubleshooting

### "Connection refused" error

**Cause:** FEAGI isn't running or wrong host/port

**Solutions:**
1. Check FEAGI is running: `curl http://localhost:8000/v1/genome/name`
2. Verify port matches FEAGI's configured API port
3. Check firewall settings

### "Tool call failed"

**Cause:** Tool depends on unimplemented FEAGI API

**Solutions:**
1. Check tool status in [TOOL_CATALOG.md](docs/TOOL_CATALOG.md)
2. Some tools have fallback implementations
3. Use alternative tools for same goal

Common fallbacks:
- `monitor_activity` → Use Brain Visualizer GUI
- `stimulate_area` → Use Spike Train Generator plugin

### "Area not found" error

**Cause:** Invalid cortical area ID

**Solutions:**
1. Call `list_cortical_areas()` first to get valid IDs
2. Check spelling and capitalization (case-sensitive)
3. Verify genome was uploaded correctly

### Tests fail with connection errors

**Cause:** Tests try to connect to FEAGI but it's not running

**Solutions:**
- Tests expect FEAGI at localhost:8000
- Start FEAGI before running tests
- Or: Mock FEAGI client in tests (see `tests/test_server.py`)

---

## Features & Capabilities

### Can I modify parameters in real-time?

Not yet. Currently you must:
1. Download genome
2. Modify JSON
3. Upload modified genome

Future: `update_parameter()` tool for temporary changes.

### Can I see real-time activity continuously?

Not yet. `monitor_activity` takes a duration snapshot.

Future: `stream_activity()` for WebSocket-based continuous monitoring.

### Can I control multiple FEAGI instances?

Not in v0.1.0. The server connects to one FEAGI instance.

Future: Multi-instance support with instance selection per tool call.

### What if I need a tool that doesn't exist?

1. Check roadmap in [DEVELOPMENT.md](DEVELOPMENT.md)
2. Open a feature request issue
3. Implement it yourself (see [CONTRIBUTING.md](CONTRIBUTING.md))

---

## Performance

### How fast are tool calls?

Depends on operation:
- `list_cortical_areas`: <100ms
- `get_connectivity`: 100-300ms (downloads genome)
- `monitor_activity`: Duration + network latency
- `upload_genome`: 500-2000ms (depends on size)

### Can I call multiple tools in parallel?

Yes, the MCP protocol supports parallel tool calls. The server uses `asyncio` for concurrency.

### Will this slow down my FEAGI instance?

Minimal impact:
- Read operations (monitoring, inspection) have negligible overhead
- Genome uploads temporarily pause processing
- Stimulation has same cost as manual activation

---

## Security & Privacy

### Is communication encrypted?

No, FEAGI uses HTTP (not HTTPS) by default. For production:
- Deploy FEAGI behind TLS reverse proxy
- Use SSH tunnels for remote access
- Don't expose FEAGI ports publicly

### Is there authentication?

Not in v0.1.0. Anyone who can reach FEAGI can use all tools.

Future versions will support API keys and role-based access.

### What data is logged?

- FEAGI MCP logs tool calls and errors locally
- FEAGI logs all API requests
- No data is sent to external services
- Logs may contain genome data and circuit parameters

---

## Compatibility

### What FEAGI versions are supported?

Tested with FEAGI 2.1.x. Should work with any version that has:
- REST API on port 8000
- `/v1/genome/*` endpoints
- JSON genome format v2.1

### Does this work with FEAGI 1.x?

No. FEAGI 1.x has a different API structure.

### What operating systems are supported?

- Linux (primary)
- macOS (tested)
- Windows (should work, less tested)

### Can I use this with FEAGI in Docker/Kubernetes?

Yes, just point `FEAGI_HOST` to the appropriate service name or IP.

---

## Development

### How do I add a new tool?

See [CONTRIBUTING.md](CONTRIBUTING.md) for step-by-step guide.

### How do I test my changes?

```bash
pytest -v
ruff check .
mypy src/
```

### Where can I get help?

- GitHub Discussions
- Discord: https://discord.gg/feagi  
- Email: feagi@neuraville.com

---

## Circuit design & plasticity

### R-STDP: i8 LTP/LTD, `plasticity_eta`, and `max_weight`

The FEAGI NPU stores `ltp_multiplier` and `ltd_multiplier` as **i8** (range
`-128`..`127`). Eligibility traces still use integer `delta_plus` / `delta_minus`
steps. The **weight commit** is `w += plasticity_eta * R * e` with
`plasticity_eta` defaulting to **1.0**; set it in `(0, 1]` (e.g. `0.01`) for
sub-unit learning. Use **`max_weight`** to cap positive growth. Both fields
are valid only when `plasticity_mode` is `stdp` or `rstdp` (rejected on `off`).

From MCP, `build_reflex_mapping` checks LTP/LTD fit in i8 and forwards
`max_weight` / `plasticity_eta` on the rule dict.

---

## Still have questions?

Open an issue on GitHub or join our Discord!
