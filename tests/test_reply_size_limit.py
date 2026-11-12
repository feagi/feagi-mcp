"""Reply-size guard in ``_StudioAwareFastMCP.call_tool``."""

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent

from feagi_mcp import server


def _text(s: str) -> TextContent:
    return TextContent(type="text", text=s)


def test_helper_shapes():
    blocks = [_text("abcd"), ImageContent(type="image", data="xyz", mimeType="image/png")]
    assert server.tool_reply_bytes((blocks, {"a": 1})) == 7
    assert server.tool_reply_bytes(blocks) == 7
    assert server.tool_reply_bytes({"a": 1}) == len('{"a":1}')
    assert server.tool_reply_bytes(CallToolResult(content=blocks)) == 7
    assert server.tool_reply_bytes(object()) == 0
    assert server.tool_reply_bytes("ran") == 0


def test_non_ascii_counted_in_bytes():
    assert server.tool_reply_bytes([_text("é")]) == 2


@pytest.fixture
def _stub(monkeypatch):
    monkeypatch.setattr(server, "studio_manages_feagi", lambda *_: False)

    def _set(result):
        async def _ran(*_args):
            return result

        monkeypatch.setattr(server.FastMCP, "call_tool", _ran)

    return _set


def test_under_limit_returns_same_object(monkeypatch, _stub):
    monkeypatch.setattr(server, "MAX_TOOL_REPLY_BYTES", 10)
    result = ([_text("a" * 10)], {"result": "x"})
    _stub(result)
    assert asyncio.run(server.mcp.call_tool("health_check", {})) is result


def test_over_limit_raises_with_details(monkeypatch, _stub):
    monkeypatch.setattr(server, "MAX_TOOL_REPLY_BYTES", 10)
    _stub([_text("a" * 11)])
    name = "get_area_parameters"
    declared = server.mcp._declared_arguments(name)
    assert declared
    with pytest.raises(ToolError) as exc:
        asyncio.run(server.mcp.call_tool(name, {}))
    msg = str(exc.value)
    assert name in msg and "0.00 MB" in msg and "Nothing was returned" in msg
    assert ", ".join(declared) in msg


def test_no_arguments_shows_none(monkeypatch, _stub):
    monkeypatch.setattr(server, "MAX_TOOL_REPLY_BYTES", 10)
    _stub([_text("a" * 11)])
    name = next(
        t.name for t in server.mcp._tool_manager.list_tools() if not t.parameters.get("properties")
    )
    with pytest.raises(ToolError) as exc:
        asyncio.run(server.mcp.call_tool(name, {}))
    assert "(none)" in str(exc.value)


def test_non_ascii_over_limit_by_bytes(monkeypatch, _stub):
    monkeypatch.setattr(server, "MAX_TOOL_REPLY_BYTES", 10)
    _stub([_text("é" * 6)])  # 6 chars, 12 bytes
    with pytest.raises(ToolError):
        asyncio.run(server.mcp.call_tool("health_check", {}))
