"""FEAGI MCP Server - Neural monitoring and control for LLMs."""

__version__ = "0.1.0"
__author__ = "Neuraville Inc."
__email__ = "feagi@neuraville.com"

__all__ = ["main"]


def __getattr__(name: str):
    """Lazy entrypoint so importing feagi_mcp.feagi_client does not require mcp installed."""
    if name == "main":
        from feagi_mcp.server import main as _main

        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
