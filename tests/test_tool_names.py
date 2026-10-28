"""Registered MCP tool names are unique and match the generated skill tool index."""

from __future__ import annotations

import ast
import asyncio
import re
from collections import Counter

from feagi_mcp import server
from feagi_mcp.skill_bundle import (
    SKILL_NAME,
    STUDIO_ONLY_TOOLS,
    TOOL_INDEX_RELATIVE_PATH,
    _is_tool_decorator,
    repository_root,
)

ROOT = repository_root()
SERVER_SOURCE = (ROOT / "src" / "feagi_mcp" / "server.py").read_text("utf-8")
INDEX = ROOT / "skills" / SKILL_NAME / TOOL_INDEX_RELATIVE_PATH


def _decorated_tool_names() -> list[str]:
    return [
        node.name
        for node in ast.walk(ast.parse(SERVER_SOURCE))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_is_tool_decorator(d) for d in node.decorator_list)
    ]


def _registered_names() -> list[str]:
    return [t.name for t in asyncio.run(server.mcp.list_tools())]


def test_tool_functions_have_unique_names() -> None:
    """A second ``@mcp.tool()`` with the same name is dropped or shadowed silently."""
    duplicated = sorted(n for n, c in Counter(_decorated_tool_names()).items() if c > 1)
    assert not duplicated, f"duplicate tool function names in server.py: {duplicated}"


def test_registered_tool_names_are_unique() -> None:
    names = _registered_names()
    duplicated = sorted(n for n, c in Counter(names).items() if c > 1)
    assert not duplicated, f"duplicate registered tool names: {duplicated}"


def test_registry_matches_decorated_functions_and_tool_index() -> None:
    registered = set(_registered_names())
    decorated = set(_decorated_tool_names())
    # The index also lists Studio's native tools in their own section; those are not
    # served by this server.
    indexed = set(re.findall(r"^- `(\w+)\(", INDEX.read_text("utf-8"), flags=re.M))
    indexed -= set(STUDIO_ONLY_TOOLS)
    assert not registered & set(STUDIO_ONLY_TOOLS), (
        f"names both registered here and listed as Studio-only: "
        f"{sorted(registered & set(STUDIO_ONLY_TOOLS))}"
    )
    assert registered == decorated, (
        f"registry vs @mcp.tool functions: only registered {sorted(registered - decorated)}, "
        f"only decorated {sorted(decorated - registered)}"
    )
    assert registered == indexed, (
        f"registry vs {TOOL_INDEX_RELATIVE_PATH}: only registered {sorted(registered - indexed)}, "
        f"only indexed {sorted(indexed - registered)} "
        "(run: python scripts/generate_skill_tool_index.py)"
    )
