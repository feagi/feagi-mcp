# FEAGI MCP Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Cursor IDE                          │
│                    (or Claude Desktop)                      │
└───────────────────────────┬─────────────────────────────────┘
                            │ MCP Protocol (stdio/JSON-RPC)
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    FEAGI MCP Server                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  FastMCP Framework                                  │   │
│  │  - Tool registration                                │   │
│  │  - Schema generation                                │   │
│  │  - Request routing                                  │   │
│  └────────────┬────────────────────────────────────────┘   │
│               │                                             │
│  ┌────────────▼────────────────────────────────────────┐   │
│  │  Tool Implementations                               │   │
│  │  - monitor_activity                                 │   │
│  │  - get_connectivity                                 │   │
│  │  - trace_signal_path                                │   │
│  │  - stimulate_area                                   │   │
│  │  - upload/download_genome                           │   │
│  │  - validate_genome                                  │   │
│  │  - etc.                                             │   │
│  └────────────┬────────────────────────────────────────┘   │
│               │                                             │
│  ┌────────────▼────────────────────────────────────────┐   │
│  │  FeagiClient (HTTP/REST)                            │   │
│  │  - Async httpx client                               │   │
│  │  - Request/response handling                        │   │
│  │  - Error recovery                                   │   │
│  └────────────┬────────────────────────────────────────┘   │
└───────────────┼─────────────────────────────────────────────┘
                │ HTTP REST API (port 8000)
                │
┌───────────────▼─────────────────────────────────────────────┐
│                      FEAGI Core                             │
│  - Neural Processing Units (NPU)                            │
│  - Connectome                                               │
│  - Genome Manager                                           │
│  - REST API Server                                          │
└───────────────┬─────────────────────────────────────────────┘
                │ ZMQ (motor/sensory ports)
                │
┌───────────────▼─────────────────────────────────────────────┐
│              Embodiment Controllers                         │
│  - MuJoCo Spot (port 5564 motor, 5558 sensory)             │
│  - Other robots                                             │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### MCP Protocol Layer

**Transport:** stdio (standard input/output)
- Cursor/Claude launches MCP server as subprocess
- JSON-RPC messages exchanged via stdin/stdout
- Server lifecycle managed by client

**Message Flow:**
1. Client sends tool call request (JSON-RPC)
2. Server routes to appropriate tool handler
3. Tool executes async operation
4. Result serialized back to client
5. Client presents result to LLM

### FEAGI MCP Server

**Language:** Python 3.10+  
**Framework:** FastMCP (official MCP SDK)  
**Architecture:** Async/await with httpx

**Responsibilities:**
- Expose FEAGI capabilities as MCP tools
- Handle concurrent requests
- Manage FEAGI connection state
- Provide error recovery and fallbacks
- Validate inputs before sending to FEAGI

**Key Components:**

1. **server.py** - Tool definitions with `@mcp.tool()` decorators
   - Each tool = one function
   - Docstrings → tool descriptions for LLM
   - Type hints → automatic JSON schema generation

2. **feagi_client.py** - Async HTTP client
   - Wraps FEAGI REST API
   - Handles request/response
   - Implements fallbacks for unreliable endpoints

3. **config.py** - Configuration management
   - Environment variable loading
   - Pydantic-based validation
   - Defaults for development

### FEAGI REST API

**Base URL:** `http://localhost:8000/v1`

**Current Endpoints (2026-03-29):**
- `GET /genome/name` - Reliable
- `GET /genome/download` - Reliable
- `POST /genome/upload` - Reliable
- `GET /cortical_area/list` - Sometimes returns malformed JSON
- `GET /embodiment/capabilities` - Sometimes returns malformed JSON
- `GET /embodiment/status` - Returns 404 (not implemented)
- `GET /monitor/cortical_activity` - Returns 404 (not implemented)
- `POST /stimulate` - Returns 404 (not implemented)

**Fallback Strategies:**
- When `/cortical_area/list` fails → Parse from `/genome/download`
- When `/embodiment/status` fails → Extract OPU/IPU from genome
- When monitoring APIs unavailable → Return placeholders with warnings

### Tool Categories

**1. Monitoring (Observation)**
- Read-only operations
- No side effects
- Real-time or snapshot data
- Examples: `monitor_activity`, `get_embodiment_status`

**2. Inspection (Analysis)**
- Read-only operations
- Analyze structure and topology
- No real-time data
- Examples: `get_connectivity`, `trace_signal_path`

**3. Control (Actuation)**
- Write operations with immediate effect
- Trigger neural activity
- Examples: `stimulate_area`

**4. Genome Management**
- Write operations with persistent effect
- Modify brain architecture
- Examples: `upload_genome`, `validate_genome`

## Data Flow

### Circuit Design Workflow

```
1. LLM: "Design walking controller for Spot"
   ↓
2. Cursor sends tool call: download_genome()
   ↓
3. MCP Server → FeagiClient → FEAGI REST API
   ↓
4. FEAGI returns genome JSON
   ↓
5. MCP Server returns to Cursor
   ↓
6. LLM analyzes genome, designs CPG circuit
   ↓
7. Cursor sends: validate_genome(new_design)
   ↓
8. MCP validates structure
   ↓
9. Cursor sends: upload_genome(new_design)
   ↓
10. FEAGI loads new genome
   ↓
11. Cursor sends: monitor_activity("cCPGa_")
   ↓
12. MCP monitors neural activity
   ↓
13. LLM reports: "CPG oscillating at 5Hz, circuit working"
```

### Monitoring Workflow

```
User: "Why isn't robot moving?"
   ↓
LLM: [calls get_embodiment_status()]
   ↓
MCP: Checks /v1/embodiment/status
   ↓
FEAGI: Returns 404 (not implemented)
   ↓
MCP: Fallback to genome OPU/IPU analysis
   ↓
MCP: Returns motor config to LLM
   ↓
LLM: [calls monitor_activity("opose0")]
   ↓
MCP: Checks /v1/monitor/cortical_activity
   ↓
FEAGI: Returns 404 (not implemented)
   ↓
MCP: Returns warning + suggestion
   ↓
LLM: "Motor monitoring API not yet available. 
      Suggestion: Check Brain Visualizer for OPU activity,
      or verify controller logs show [MOTOR-SNAPSHOT] messages."
```

## Concurrency Model

- **Server:** Single-threaded event loop (asyncio)
- **Requests:** Concurrent via async/await
- **FEAGI Client:** Connection pooling via httpx
- **Tool Calls:** Can execute in parallel from same LLM query

**Performance:**
- Typical tool latency: 50-300ms
- Concurrent limit: ~100 requests/sec
- Bottleneck: FEAGI API response time

## Error Handling Strategy

### Levels

1. **Network errors** - Retry with exponential backoff
2. **HTTP errors** - Parse response, return structured error
3. **API unavailable** - Fallback to alternative method
4. **Invalid input** - Validate and return clear message

### Principle: Graceful Degradation

Never crash. Always return:
```python
{
    "error": "error_type",
    "message": "Human-readable explanation",
    "suggestion": "How to work around this",
}
```

## Security Considerations

### Current State (v0.1.0)
- No authentication
- No authorization
- No rate limiting
- HTTP only (no TLS)
- Trusted network assumption

### Threat Model

**In Scope:**
- Malicious genome uploads → Validation catches most issues
- Connection hijacking → Use localhost or SSH tunnels
- Data exposure → Logs may contain sensitive circuit data

**Out of Scope (for now):**
- DDoS attacks
- Advanced persistent threats
- Multi-tenancy

### Recommendations

For production use:
1. Deploy FEAGI behind TLS reverse proxy
2. Implement API key authentication
3. Add rate limiting per client
4. Use VPN or SSH tunnels for remote access
5. Audit log all genome uploads

## Extensibility

### Adding New Tools

1. Define async function in `server.py`
2. Add `@mcp.tool()` decorator
3. Implement in `feagi_client.py` if needs new API
4. Add tests in `tests/`
5. Document in `docs/API_REFERENCE.md`

### Adding New Endpoints

When FEAGI adds new API endpoints:

1. Add method to `FeagiClient`:
```python
async def new_endpoint(self, param: str) -> dict:
    response = await self._client.get(f"{self.base_url}/v1/new")
    return response.json()
```

2. Update tool to use real endpoint instead of placeholder:
```python
@mcp.tool()
async def my_tool(param: str) -> dict:
    return await feagi.new_endpoint(param)
```

### WebSocket Support (Future)

For streaming activity data:
```python
import websockets


async def stream_activity(area_id: str):
    async with websockets.connect("ws://localhost:8000/ws/activity") as ws:
        await ws.send(json.dumps({"area_id": area_id}))
        async for message in ws:
            yield json.loads(message)
```

## Performance Optimization

### Current
- Connection reuse via httpx client
- Async/await for concurrency
- Response caching (none currently)

### Future
- Cache genome downloads (TTL: 5s)
- Batch multiple tool calls
- WebSocket for continuous monitoring
- Connection pooling for multi-FEAGI

## Deployment Options

### Local Development
```bash
python -m feagi_mcp.server
```

### Docker
```bash
docker build -t feagi-mcp .
docker run -e FEAGI_HOST=host.docker.internal feagi-mcp
```

### Systemd Service
```ini
[Unit]
Description=FEAGI MCP Server
After=feagi.service

[Service]
Type=simple
User=feagi
Environment="FEAGI_HOST=localhost"
Environment="FEAGI_PORT=8000"
ExecStart=/opt/feagi-mcp/venv/bin/python -m feagi_mcp.server
Restart=always

[Install]
WantedBy=multi-user.target
```

## Monitoring & Observability

### Logs
- Structured logging via Python `logging` module
- Log levels: INFO (default), DEBUG, WARNING, ERROR
- Format: `timestamp [level] module: message`

### Metrics (Future)
- Tool call counts
- Latency per tool
- Error rates
- FEAGI connection uptime

### Health Checks (Future)
- Periodic FEAGI ping
- Tool availability matrix
- Alert on degraded service

## Testing Strategy

### Unit Tests
- Mock FEAGI client
- Test tool logic in isolation
- Fast execution (<1s total)

### Integration Tests (Future)
- Requires running FEAGI
- Test actual API calls
- Verify end-to-end flows

### End-to-End Tests (Future)
- Full Cursor integration
- Automated circuit design scenarios
- Performance benchmarks

## References

- [MCP Protocol Spec](https://modelcontextprotocol.io)
- [FastMCP Documentation](https://github.com/modelcontextprotocol/python-sdk)
- [FEAGI Architecture](https://feagi.org/docs/architecture)
- [Async Python Patterns](https://docs.python.org/3/library/asyncio.html)
