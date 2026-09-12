"""FEAGI MCP Server - Neural monitoring and control for LLMs."""

from typing import Any

__version__ = "0.0.14"
__author__ = "Neuraville Inc."
__email__ = "feagi@neuraville.com"

__all__ = ["main"]


def __getattr__(name: str) -> Any:
    """Lazy entrypoint so importing feagi_mcp.feagi_client does not require mcp installed."""
    if name == "main":
        from feagi_mcp.server import main as _main

        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
