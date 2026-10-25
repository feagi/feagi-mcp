# Connecting the FEAGI MCP server

Use this when FEAGI tools are missing or every call fails to connect.

## Requirements

- A running FEAGI instance with its HTTP API reachable (default `http://localhost:8000`).
  Neurorobotics Studio starts one when an experiment runs; FEAGI can also run standalone or
  in Docker.
- Python 3.10 or newer, and either `uv` (recommended) or `pip`.

## Install and run

The server is the PyPI package `feagi-mcp`, which provides the `feagi-mcp` command (stdio
transport).

```bash
uvx feagi-mcp
```

or

```bash
pip install feagi-mcp
feagi-mcp
```

## Configuration

Environment variables (or a `.env` file in the server's working directory):

| Variable | Default | Purpose |
|---|---|---|
| `FEAGI_HOST` | `localhost` | FEAGI API host |
| `FEAGI_PORT` | `8000` | FEAGI API port |
| `FEAGI_TIMEOUT_SECONDS` | `30.0` | Request timeout |
| `FEAGI_PROBE_TIMEOUT_SECONDS` | `5.0` | Health probe timeout used by `diagnose_feagi_runtime()` |
| `FEAGI_LOG_FILE` | unset | FEAGI log file for runtime diagnosis |
| `FEAGI_COMPOSER_BASE_URL` | unset | Composer catalog root for simulator asset pack tools |
| `FEAGI_MCP_SNAPSHOTS_DIR` | server `var/snapshots` | Where genome snapshots are stored |
| `FEAGI_MCP_TRACES_DIR` | server `var/traces` | Where aligned traces (`record_aligned_trace`) are written |
| `FEAGI_MCP_ALLOW_DIRECT` | unset | `1` lets the standalone server run tools even while Studio is running (normally it hands off to `neurorobotics-studio`) |
| `FEAGI_STUDIO_DIR` | `~/.feagi/studio` | Where Studio's `mcp.json` discovery file is looked up |

## Client configuration

Most MCP clients accept a JSON entry like this:

```json
{
  "mcpServers": {
    "feagi": {
      "command": "uvx",
      "args": ["feagi-mcp"],
      "env": { "FEAGI_HOST": "localhost", "FEAGI_PORT": "8000" }
    }
  }
}
```

Hosts that install FEAGI as a plugin configure this automatically.

## Check the connection

1. `health_check()` should return the genome name and burst engine status.
2. If it fails, confirm FEAGI is running and that host and port match, then run
   `diagnose_feagi_runtime()`.
3. For remote FEAGI, set `FEAGI_HOST` to its address. The API has no built-in authentication
   or encryption, so use it only on trusted networks or through a tunnel.
