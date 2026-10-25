"""Tests for the FEAGI agent skill and plugin bundle (``skills/feagi``, ``.claude-plugin``)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from feagi_mcp.skill_bundle import (
    DESTRUCTIVE_TOOLS,
    SKILL_NAME,
    STUDIO_ONLY_SECTION,
    STUDIO_ONLY_TOOLS,
    TOOL_INDEX_RELATIVE_PATH,
    category_problems,
    is_known_tool,
    render_tool_index,
    repository_root,
    skill_dir,
    tool_parameters,
    tool_summaries,
)

ROOT = repository_root()
SKILL_DIR = ROOT / "skills" / SKILL_NAME
SERVER_SOURCE = (ROOT / "src" / "feagi_mcp" / "server.py").read_text("utf-8")
SKILL_FILES = sorted(SKILL_DIR.rglob("*.md"))

# A tool reference is an identifier with an underscore followed by "(" inside a code span,
# e.g. `apply_connectivity_rule(src_area=..., intent="...")`. Plain math such as
# `round(x)` has no underscore and is ignored.
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_CALL = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(")
_KWARG = re.compile(r"[(,]\s*([a-z_][a-z0-9_]*)=")
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def _frontmatter(text: str) -> dict[str, str]:
    """Top-level ``key: value`` pairs of a YAML frontmatter block."""
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if line and not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def _tool_calls(text: str) -> list[tuple[str, list[str]]]:
    """``(tool_name, [keyword, ...])`` for every call-shaped code span outside fences."""
    calls: list[tuple[str, list[str]]] = []
    for span in _CODE_SPAN.findall(_FENCE.sub("", text)):
        for match in _CALL.finditer(span):
            args = span[match.end() - 1 :]
            calls.append((match.group(1), _KWARG.findall(args)))
    return calls


def test_every_tool_has_exactly_one_category() -> None:
    assert category_problems(set(tool_summaries(SERVER_SOURCE))) == []


def test_destructive_tools_are_registered() -> None:
    assert set(tool_summaries(SERVER_SOURCE)) >= DESTRUCTIVE_TOOLS


def test_tool_index_is_current() -> None:
    index = (SKILL_DIR / TOOL_INDEX_RELATIVE_PATH).read_text("utf-8")
    assert index == render_tool_index(tool_summaries(SERVER_SOURCE)), (
        "run: python scripts/generate_skill_tool_index.py"
    )


def test_skill_frontmatter_follows_agent_skills_spec() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text("utf-8")
    fields = _frontmatter(text)
    assert fields["name"] == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"])
    assert len(fields["name"]) <= 64
    assert 0 < len(fields["description"]) <= 1024
    assert len(fields.get("compatibility", "")) <= 500
    body_lines = text.split("---\n", 2)[2].splitlines()
    assert len(body_lines) < 500, "keep SKILL.md under 500 lines; move detail to references/"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_tool_references_match_server(path: Path) -> None:
    params = tool_parameters(SERVER_SOURCE)
    problems = []
    for name, kwargs in _tool_calls(path.read_text("utf-8")):
        if not is_known_tool(name, set(params)):
            problems.append(f"unknown tool {name}()")
            continue
        if name not in params:
            continue  # Studio-only tool: parameters are not defined in server.py
        problems.extend(
            f"{name}() has no parameter {kw}" for kw in kwargs if kw not in params[name]
        )
    assert problems == []


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_relative_links_resolve(path: Path) -> None:
    targets = [t for t in _LINK.findall(path.read_text("utf-8")) if "://" not in t]
    missing = [t for t in targets if not (path.parent / t).resolve().is_file()]
    assert missing == []


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_skill_text_is_host_neutral(path: Path) -> None:
    """The same skill serves every MCP host, so it must not address one model vendor."""
    assert not re.search(r"\b(Claude|Anthropic|OpenAI|Gemini|GPT)\b", path.read_text("utf-8"))


def test_reference_files_are_reachable_from_skill() -> None:
    linked = set(_LINK.findall((SKILL_DIR / "SKILL.md").read_text("utf-8")))
    references = {f"references/{p.name}" for p in (SKILL_DIR / "references").glob("*.md")}
    assert references <= linked


def test_plugin_marketplace_and_package_versions_agree() -> None:
    # tomllib is 3.11+; the [project] version is the first top-level ``version =`` line.
    pyproject = (ROOT / "pyproject.toml").read_text("utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)  # type: ignore[union-attr]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    entry = next(p for p in marketplace["plugins"] if p["name"] == plugin["name"])
    assert plugin["version"] == entry["version"] == version
    assert plugin["mcpServers"]["feagi"]["args"] == [f"feagi-mcp@{version}"]
    assert entry["source"] == "./"


def test_skill_dir_resolves_source_checkout() -> None:
    assert skill_dir() == SKILL_DIR.resolve()


def test_tool_summaries_reads_decorated_functions_only() -> None:
    source = '''
@mcp.tool()
async def alpha_tool(a: int, b: str = "x") -> None:
    """First line with ``code``.

    More detail.
    """

def helper_fn() -> None:
    """Not a tool."""

@mcp.tool
def beta_tool() -> None:
    pass
'''
    assert tool_summaries(source) == {"alpha_tool": "First line with `code`.", "beta_tool": ""}
    assert tool_parameters(source) == {"alpha_tool": ("a", "b"), "beta_tool": ()}


def test_category_problems_reports_missing_and_unknown_tools() -> None:
    problems = category_problems({"health_check", "brand_new_tool"})
    assert "brand_new_tool has no category in TOOL_CATEGORIES" in problems
    assert any("get_brain_regions" in p and "not a registered tool" in p for p in problems)


def test_render_tool_index_puts_uncategorized_tools_under_other() -> None:
    index = render_tool_index({"health_check": "Ping.", "brand_new_tool": "New."})
    assert "## Health and runtime diagnostics\n\n- `health_check()`: Ping." in index
    assert "## Other\n\n- `brand_new_tool()`: New." in index


def test_tool_call_extraction() -> None:
    text = (
        'Use `apply_connectivity_rule(src_area=a, intent="x=y")` and `round(p)`.\n'
        '```json\n{"not_a_call": `fake_tool(x=1)`}\n```\n'
    )
    assert _tool_calls(text) == [("apply_connectivity_rule", ["src_area", "intent"])]


def test_studio_only_tools_listed_in_own_index_section() -> None:
    index = render_tool_index(tool_summaries(SERVER_SOURCE))
    assert f"## {STUDIO_ONLY_SECTION}" in index
    section = index.split(f"## {STUDIO_ONLY_SECTION}", 1)[1]
    for name in ("read_design_notebook", "append_design_note"):
        assert name in STUDIO_ONLY_TOOLS
        assert f"- `{name}(" in section


def test_reference_check_accepts_studio_only_but_not_unknown_tools() -> None:
    server_tools = set(tool_parameters(SERVER_SOURCE))
    assert is_known_tool("read_design_notebook", server_tools)
    assert is_known_tool("append_design_note", server_tools)
    assert is_known_tool("health_check", server_tools)
    assert not is_known_tool("made_up_tool", server_tools)
