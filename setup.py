#!/usr/bin/env python3
"""Setup script for FEAGI MCP - Interactive installation and configuration."""

import json
import os
import subprocess
import sys
from pathlib import Path


def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def check_python_version() -> bool:
    """Verify Python version is 3.10+."""
    version = sys.version_info
    if version.major == 3 and version.minor >= 10:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
        return True
    print(f"✗ Python {version.major}.{version.minor}.{version.micro} - Need 3.10+")
    return False


def check_feagi_connection(host: str, port: int) -> bool:
    """Check if FEAGI is reachable."""
    try:
        import urllib.request

        url = f"http://{host}:{port}/v1/genome/name"
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status == 200:
                genome_name = json.loads(response.read())
                print(f"✓ FEAGI reachable at {host}:{port}")
                print(f"  Current genome: {genome_name}")
                return True
    except Exception as e:
        print(f"✗ FEAGI not reachable at {host}:{port}")
        print(f"  Error: {e}")
        return False
    return False


def create_venv() -> bool:
    """Create virtual environment."""
    venv_path = Path("venv")
    if venv_path.exists():
        print("✓ Virtual environment already exists")
        return True

    try:
        print("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)
        print("✓ Virtual environment created")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create venv: {e}")
        return False


def install_package() -> bool:
    """Install package in development mode."""
    try:
        venv_python = "venv/bin/python" if os.name != "nt" else "venv\\Scripts\\python"
        print("Installing feagi-mcp...")
        subprocess.run(
            [venv_python, "-m", "pip", "install", "-e", ".[dev]"],
            check=True,
            capture_output=True,
        )
        print("✓ Package installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Installation failed: {e}")
        return False


def configure_env() -> None:
    """Create .env file from template."""
    env_path = Path(".env")
    template_path = Path(".env.example")

    if env_path.exists():
        print("✓ .env already exists")
        return

    if not template_path.exists():
        print("✗ .env.example not found")
        return

    print("\nFEAGI Connection Configuration")
    print("-" * 40)
    host = input("FEAGI host [localhost]: ").strip() or "localhost"
    port = input("FEAGI port [8000]: ").strip() or "8000"

    config_lines = [
        f"FEAGI_HOST={host}",
        f"FEAGI_PORT={port}",
        "FEAGI_TIMEOUT_SECONDS=30.0",
        "FEAGI_MAX_RETRIES=3",
        "FEAGI_CONNECTION_CHECK_INTERVAL_SECONDS=5.0",
    ]

    with open(env_path, "w") as f:
        f.write("\n".join(config_lines) + "\n")

    print(f"✓ Created .env with {host}:{port}")


def generate_cursor_config() -> None:
    """Generate Cursor MCP configuration."""
    project_root = Path.cwd().resolve()
    venv_python = (
        project_root / "venv" / "bin" / "python"
        if os.name != "nt"
        else project_root / "venv" / "Scripts" / "python"
    )

    cursor_config = {
        "mcpServers": {
            "feagi": {
                "command": str(venv_python),
                "args": ["-m", "feagi_mcp.server"],
                "env": {
                    "FEAGI_HOST": "localhost",
                    "FEAGI_PORT": "8000",
                },
            }
        }
    }

    print("\nCursor MCP Configuration:")
    print("-" * 40)
    print(json.dumps(cursor_config, indent=2))
    print("\nAdd this to ~/.cursor/mcp.json")
    print("(Create file if it doesn't exist)")


def run_tests() -> bool:
    """Run test suite."""
    try:
        venv_python = "venv/bin/python" if os.name != "nt" else "venv\\Scripts\\python"
        print("Running tests...")
        result = subprocess.run(
            [venv_python, "-m", "pytest", "-v"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("✓ All tests passed")
            return True
        print(f"✗ Tests failed:\n{result.stdout}\n{result.stderr}")
        return False
    except Exception as e:
        print(f"✗ Test run failed: {e}")
        return False


def main() -> None:
    """Run setup wizard."""
    print_header("FEAGI MCP Setup")

    print("\n1. Checking Python version...")
    if not check_python_version():
        sys.exit(1)

    print("\n2. Creating virtual environment...")
    if not create_venv():
        sys.exit(1)

    print("\n3. Installing package...")
    if not install_package():
        sys.exit(1)

    print("\n4. Configuring environment...")
    configure_env()

    print("\n5. Checking FEAGI connection...")
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path) as f:
            env_vars = dict(
                line.strip().split("=", 1) for line in f if "=" in line and not line.startswith("#")
            )
        host = env_vars.get("FEAGI_HOST", "localhost")
        port = int(env_vars.get("FEAGI_PORT", "8000"))
        feagi_ok = check_feagi_connection(host, port)
    else:
        feagi_ok = check_feagi_connection("localhost", 8000)

    print("\n6. Running tests...")
    tests_ok = run_tests()

    print_header("Setup Complete!")

    if feagi_ok and tests_ok:
        print("\n✓ All checks passed!")
    elif not feagi_ok:
        print("\n⚠ FEAGI not reachable - start FEAGI then rerun tests")
    elif not tests_ok:
        print("\n⚠ Some tests failed - check logs above")

    print("\nNext steps:")
    print("  1. Activate venv: source venv/bin/activate")
    print("  2. Test server: python -m feagi_mcp.server")
    print("  3. Configure Cursor (see below)")

    generate_cursor_config()

    print("\nDocs:")
    print("  - Quick Start: docs/QUICKSTART.md")
    print("  - API Reference: docs/API_REFERENCE.md")
    print("  - Development: DEVELOPMENT.md")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
