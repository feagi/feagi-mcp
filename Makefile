# FEAGI MCP - Makefile for common tasks

.PHONY: help install test lint format typecheck clean dev-setup run

help:
	@echo "FEAGI MCP - Available commands:"
	@echo ""
	@echo "  make install     - Install package in development mode"
	@echo "  make dev-setup   - Complete development setup"
	@echo "  make test        - Run test suite"
	@echo "  make lint        - Run ruff linter"
	@echo "  make format      - Format code with ruff"
	@echo "  make typecheck   - Run mypy type checker"
	@echo "  make clean       - Remove build artifacts"
	@echo "  make run         - Run MCP server"
	@echo ""

install:
	pip install -e ".[dev]"

dev-setup:
	python -m venv venv
	. venv/bin/activate && pip install --upgrade pip
	. venv/bin/activate && pip install -e ".[dev]"
	cp .env.example .env
	@echo ""
	@echo "Setup complete! Activate venv:"
	@echo "  source venv/bin/activate"

test:
	pytest -v --cov=feagi_mcp --cov-report=term-missing

test-fast:
	pytest -v -x

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy src/

check-all: lint typecheck test

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run:
	python -m feagi_mcp.server

build:
	python -m build

docs-serve:
	@echo "Documentation available in docs/ folder"
	@echo "Open docs/QUICKSTART.md to get started"
