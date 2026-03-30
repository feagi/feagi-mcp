#!/usr/bin/env python3
"""
Quick verification that FEAGI MCP is installed correctly.

Usage:
    python verify_install.py
"""

import sys
from pathlib import Path


def check_file_exists(path: Path, description: str) -> bool:
    """Check if a file exists."""
    if path.exists():
        print(f"✓ {description}")
        return True
    print(f"✗ {description} - NOT FOUND: {path}")
    return False


def check_python_import(module: str, description: str) -> bool:
    """Check if a Python module can be imported."""
    try:
        __import__(module)
        print(f"✓ {description}")
        return True
    except ImportError as e:
        print(f"✗ {description} - IMPORT FAILED: {e}")
        return False


def main() -> int:
    """Run verification checks."""
    print("=" * 60)
    print("  FEAGI MCP Installation Verification")
    print("=" * 60)

    checks_passed = 0
    checks_total = 0

    print("\n[1] Checking project structure...")
    checks_total += 1
    project_files = [
        (Path("pyproject.toml"), "pyproject.toml exists"),
        (Path("src/feagi_mcp/__init__.py"), "Package __init__.py exists"),
        (Path("src/feagi_mcp/server.py"), "MCP server exists"),
        (Path("src/feagi_mcp/feagi_client.py"), "FEAGI client exists"),
        (Path("src/feagi_mcp/config.py"), "Config module exists"),
        (Path("README.md"), "README exists"),
        (Path("docs/QUICKSTART.md"), "Quick start guide exists"),
    ]

    structure_ok = all(check_file_exists(path, desc) for path, desc in project_files)
    if structure_ok:
        checks_passed += 1

    print("\n[2] Checking Python imports...")
    checks_total += 1
    imports_ok = all(
        check_python_import(module, desc)
        for module, desc in [
            ("feagi_mcp", "feagi_mcp package"),
            ("feagi_mcp.server", "MCP server module"),
            ("feagi_mcp.feagi_client", "FEAGI client module"),
            ("feagi_mcp.config", "Config module"),
            ("mcp", "MCP SDK"),
            ("httpx", "HTTP client"),
            ("pydantic", "Pydantic"),
        ]
    )
    if imports_ok:
        checks_passed += 1

    print("\n[3] Checking tool definitions...")
    checks_total += 1
    try:
        from feagi_mcp import server
        
        tool_functions = [
            "monitor_activity",
            "get_connectivity",
            "get_area_parameters",
            "get_embodiment_status",
            "stimulate_area",
            "list_cortical_areas",
            "get_genome_info",
            "download_genome",
            "upload_genome",
            "validate_genome",
            "trace_signal_path",
            "health_check",
        ]
        
        found_tools = [name for name in tool_functions if hasattr(server, name)]
        print(f"✓ {len(found_tools)}/12 expected tool functions found")
        if len(found_tools) >= 10:
            checks_passed += 1
        else:
            print(f"  Warning: Some tools missing: {set(tool_functions) - set(found_tools)}")
    except Exception as e:
        print(f"✗ Tool check failed: {e}")

    print("\n[4] Checking documentation...")
    checks_total += 1
    doc_files = [
        Path("docs/API_REFERENCE.md"),
        Path("docs/QUICKSTART.md"),
        Path("docs/CURSOR_INTEGRATION.md"),
        Path("DEVELOPMENT.md"),
    ]
    docs_ok = all(f.exists() for f in doc_files)
    if docs_ok:
        print("✓ All documentation files present")
        checks_passed += 1
    else:
        print("✗ Some documentation missing")

    print("\n" + "=" * 60)
    print(f"  Results: {checks_passed}/{checks_total} checks passed")
    print("=" * 60)

    if checks_passed == checks_total:
        print("\n✅ FEAGI MCP is correctly installed!")
        print("\nNext steps:")
        print("  1. Configure Cursor: see docs/CURSOR_INTEGRATION.md")
        print("  2. Test connection: python scripts/test_connection.py")
        print("  3. Read quick start: docs/QUICKSTART.md")
        return 0
    else:
        print("\n❌ Installation incomplete")
        print("\nTroubleshooting:")
        print("  1. Run: pip install -e .")
        print("  2. Check all files are present")
        print("  3. See DEVELOPMENT.md for details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
