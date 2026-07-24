# FEAGI MCP - Developer Guide

## Architecture

The FEAGI MCP server provides LLMs with tools to observe, analyze, and control FEAGI neural systems. It acts as a bridge between AI assistants and the FEAGI REST API.

## Project Structure

```
feagi-mcp/
├── src/feagi_mcp/
│   ├── __init__.py           # Package exports
│   ├── server.py             # Main MCP server with tool definitions
│   ├── feagi_client.py       # Async HTTP client for FEAGI API
│   └── config.py             # Configuration management
├── tests/
│   └── test_server.py        # Unit tests
├── examples/
│   └── circuit_design.py     # Example usage patterns
├── pyproject.toml            # Python package configuration
├── README.md                 # User documentation
└── DEVELOPMENT.md            # This file
```

## Setup for Development

### 1. Clone and Install

```bash
cd /Users/nadji/code/FEAGI-2.0/feagi-mcp
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure FEAGI Connection

```bash
cp .env.example .env
# Edit .env to point to your FEAGI instance
```

### 3. Run Tests

```bash
pytest
pytest -v  # Verbose output
pytest --cov=feagi_mcp  # With coverage
```

## Adding New Tools

Tools are defined in `src/feagi_mcp/server.py` using the `@mcp.tool()` decorator:

```python
@mcp.tool()
async def my_new_tool(param1: str, param2: int = 100) -> dict[str, Any]:
    """Tool description shown to the LLM.
    
    Detailed explanation of what this tool does and when to use it.
    
    Args:
        param1: Description of parameter
        param2: Optional parameter with default
        
    Returns:
        Dictionary with results
    """
    # Implementation
    result = await feagi.some_api_call(param1, param2)
    return result
```

The MCP SDK automatically generates JSON schemas from type hints and docstrings.

## Tool Design Principles

### 1. **Observability First**
Tools should prioritize read-only observation over mutation. LLMs need to see what's happening before they can fix it.

### 2. **Clear Return Values**
Always return structured dictionaries with:
- Success/error status
- Human-readable messages
- Actionable data

### 3. **Graceful Degradation**
Handle FEAGI API failures gracefully. If an endpoint isn't available, try alternative approaches or return helpful error messages.

### 4. **Type Safety**
Use type hints for all parameters and return values. This helps the MCP SDK generate accurate schemas.

## FEAGI API Endpoints

### Current (2026-03-29)
- `GET /v1/genome/name` - Get current genome name
- `GET /v1/genome/download` - Download complete genome
- `POST /v1/genome/upload` - Upload new genome
- `GET /v1/cortical_area/list` - List all areas (sometimes unreliable)
- `GET /v1/monitor/cortical_activity?area=X&duration=Y` - Monitor activity (not yet implemented)
- `POST /v1/stimulate` - Stimulate neurons (not yet implemented)
- `GET /v1/embodiment/status` - Get controller status (not yet implemented)
- `GET /v1/embodiment/capabilities` - Get registered capabilities (unreliable)

### Future Endpoints Needed
- `/v1/connectivity/trace` - Trace signal paths
- `/v1/area/{id}/parameters` - Get area parameters
- `/v1/area/{id}/activity/stream` - Real-time activity stream
- `/v1/motor/output/stream` - Monitor motor commands
- `/v1/stimulation/batch` - Batch stimulation commands

## Testing Against Live FEAGI

To test with a running FEAGI instance:

```bash
# Terminal 1: Start FEAGI
cd /Users/nadji/code/FEAGI-2.0/feagi-core
# (start FEAGI)

# Terminal 2: Run MCP server
cd /Users/nadji/code/FEAGI-2.0/feagi-mcp
source venv/bin/activate
python -m feagi_mcp.server

# Terminal 3: Test with example
python examples/circuit_design.py
```

## Debugging

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

### Test Tool Calls Directly

```python
from feagi_mcp.server import monitor_activity, get_connectivity
import asyncio


async def test():
    result = await monitor_activity("cCPGa_", 1000)
    print(result)


asyncio.run(test())
```

## Contributing

1. Follow PEP 8 style guidelines
2. Use type hints for all function signatures
3. Write docstrings in Google style
4. Add tests for new tools
5. Update README.md when adding features
6. Run linters before committing:
   ```bash
   ruff check .
   ruff format .
   mypy src/
   ```

## Release Process (PyPI)

Publishing matches **feagi-python-sdk**: create a **GitHub Release** (with a tag such as `v0.0.2`). The workflow `.github/workflows/publish_pypi_feagi_mcp.yml` runs on `release: published`, sets the version from the tag (PEP 440, strip leading `v`), runs tests, builds, and uploads to PyPI.

**Repository settings:** configure a `pypi` environment and the `PYPI_PASSWORD_TOKEN` secret (same pattern as the Python SDK). Optional: **Trusted Publishing** on PyPI for this project; the workflow includes `id-token: write` for OIDC if you switch the publish action later.

```bash
# Local sanity check (optional)
pytest
python -m build
python -m twine check --strict dist/*
```

**Manual workflow run:** Actions → “Publish to PyPI - FEAGI MCP” → Run workflow → set `version` (e.g. `0.0.2`) and optional `dry_run`.

## Roadmap

### Phase 1: Core Monitoring (Current)
- [x] Genome upload/download
- [x] Cortical area listing
- [x] Connectivity inspection
- [x] Basic validation
- [ ] Activity monitoring (pending FEAGI API)
- [ ] Embodiment status (pending FEAGI API)

### Phase 2: Real-time Observation
- [ ] Streaming activity data
- [ ] Signal path tracing with timing
- [ ] Motor output monitoring
- [ ] Sensory input inspection

### Phase 3: Interactive Control
- [ ] Direct stimulation
- [ ] Parameter tuning (non-persistent)
- [ ] Circuit testing automation
- [ ] Batch operations

### Phase 4: Advanced Analysis
- [ ] Performance profiling
- [ ] Circuit comparison
- [ ] Pattern recognition
- [ ] Anomaly detection

## Known Issues

1. `/v1/cortical_area/list` sometimes returns malformed JSON - fallback to genome download
2. `/v1/monitor/cortical_activity` not yet implemented in FEAGI - tool returns placeholder
3. `/v1/embodiment/status` returns 404 - fallback to genome OPU/IPU analysis

## Support

- GitHub Issues: https://github.com/Neuraville/feagi-mcp/issues
- FEAGI Docs: https://feagi.org
- Discord: https://discord.gg/feagi
