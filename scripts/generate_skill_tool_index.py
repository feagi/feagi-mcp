"""Regenerate skills/feagi/references/tool-index.md from the MCP tools in server.py.

Usage:
    python scripts/generate_skill_tool_index.py          # write the index
    python scripts/generate_skill_tool_index.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feagi_mcp.skill_bundle import (  # noqa: E402
    TOOL_INDEX_RELATIVE_PATH,
    category_problems,
    render_tool_index,
    tool_summaries,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the index is stale")
    args = parser.parse_args()

    summaries = tool_summaries((ROOT / "src" / "feagi_mcp" / "server.py").read_text("utf-8"))
    for problem in category_problems(set(summaries)):
        print(f"warning: {problem} (update TOOL_CATEGORIES in skill_bundle.py)")

    index_path = ROOT / "skills" / "feagi" / TOOL_INDEX_RELATIVE_PATH
    rendered = render_tool_index(summaries)
    if args.check:
        current = index_path.read_text("utf-8") if index_path.is_file() else ""
        if current != rendered:
            print(f"{index_path.relative_to(ROOT)} is stale; run {Path(__file__).name}")
            return 1
        return 0
    index_path.write_text(rendered, "utf-8")
    print(f"wrote {index_path.relative_to(ROOT)} ({len(summaries)} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
