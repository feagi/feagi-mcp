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
    render_tool_index_parts,
    tool_summaries,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the index is stale")
    args = parser.parse_args()

    summaries = tool_summaries((ROOT / "src" / "feagi_mcp" / "server.py").read_text("utf-8"))
    for problem in category_problems(set(summaries)):
        print(f"warning: {problem} (update TOOL_CATEGORIES in skill_bundle.py)")

    ref_dir = (ROOT / "skills" / "feagi" / TOOL_INDEX_RELATIVE_PATH).parent
    parts = render_tool_index_parts(summaries)
    stale = {p for p in ref_dir.glob("tool-index*.md") if p.name not in parts}
    if args.check:
        for name, text in parts.items():
            path = ref_dir / name
            if not path.is_file() or path.read_text("utf-8") != text:
                print(f"{path.relative_to(ROOT)} is stale; run {Path(__file__).name}")
                return 1
        for path in sorted(stale):
            print(f"{path.relative_to(ROOT)} is no longer generated; run {Path(__file__).name}")
            return 1
        return 0
    for name, text in parts.items():
        (ref_dir / name).write_text(text, "utf-8")
        print(f"wrote {(ref_dir / name).relative_to(ROOT)}")
    for path in stale:
        path.unlink()
        print(f"removed {path.relative_to(ROOT)}")
    print(f"{len(summaries)} tools in {len(parts)} parts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
