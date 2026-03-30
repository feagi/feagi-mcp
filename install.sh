#!/bin/bash
# Quick install script for FEAGI MCP

set -e

echo "==========================================="
echo "  FEAGI MCP - Quick Install"
echo "==========================================="

# Check Python version
python3 --version || { echo "Error: Python 3 not found"; exit 1; }

# Create venv if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate and install
echo "Installing package..."
source venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# Copy env template
if [ ! -f ".env" ]; then
    echo "Creating .env from template..."
    cp .env.example .env
fi

# Run tests
echo "Running tests..."
pytest || echo "Warning: Some tests failed"

echo ""
echo "==========================================="
echo "  Installation Complete!"
echo "==========================================="
echo ""
echo "Activate venv:"
echo "  source venv/bin/activate"
echo ""
echo "Test server:"
echo "  python -m feagi_mcp.server"
echo ""
echo "Configure Cursor:"
echo "  See docs/CURSOR_INTEGRATION.md"
echo ""
