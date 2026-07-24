# Contributing to FEAGI MCP

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### 1. Fork and Clone

```bash
git clone git@github.com:YourUsername/feagi-mcp.git
cd feagi-mcp
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 3. Install Development Dependencies

```bash
pip install -e ".[dev]"
```

### 4. Verify Setup

```bash
pytest
ruff check .
mypy src/
```

## Code Style

### Python Standards
- Follow PEP 8
- Use type hints for all function signatures
- Maximum line length: 100 characters
- Use `ruff` for linting and formatting

### Docstrings
Use Google-style docstrings:

```python
def my_function(param1: str, param2: int = 10) -> dict[str, Any]:
    """Brief one-line summary.
    
    Detailed explanation of what the function does, when to use it,
    and any important notes about behavior.
    
    Args:
        param1: Description of first parameter
        param2: Description of optional parameter with default
        
    Returns:
        Dictionary containing result data with keys:
        - key1: Description
        - key2: Description
        
    Raises:
        ValueError: When param1 is empty
        ConnectionError: When FEAGI is unreachable
    """
```

### Type Hints
Always use type hints:

```python
# Good
async def monitor_activity(area_id: str, duration_ms: int) -> dict[str, Any]: ...


# Bad
async def monitor_activity(area_id, duration_ms): ...
```

## Testing

### Writing Tests

Place tests in `tests/` directory:

```python
import pytest
from feagi_mcp.server import my_new_tool


@pytest.mark.asyncio
async def test_my_new_tool():
    """Test description."""
    result = await my_new_tool("test_param")
    assert result["success"] is True
    assert "data" in result
```

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=feagi_mcp --cov-report=html

# Specific test
pytest tests/test_server.py::test_my_new_tool -v
```

### Test Requirements
- All new tools must have tests
- Aim for >80% code coverage
- Test both success and error cases
- Mock FEAGI API calls when appropriate

## Adding New Tools

### 1. Add Client Method

In `src/feagi_mcp/feagi_client.py`:

```python
async def my_new_api_call(self, param: str) -> dict[str, Any]:
    """Call FEAGI API endpoint.

    Args:
        param: Parameter description

    Returns:
        API response data
    """
    try:
        response = await self._client.get(
            f"{self.base_url}/v1/new_endpoint", params={"param": param}
        )
        if response.status_code == 200:
            return response.json()
        return {"error": f"HTTP {response.status_code}", "message": response.text}
    except Exception as e:
        logger.error(f"my_new_api_call failed: {e}")
        return {"error": str(e)}
```

### 2. Add Tool Definition

In `src/feagi_mcp/server.py`:

```python
@mcp.tool()
async def my_new_tool(param: str) -> dict[str, Any]:
    """Brief description shown to LLM.
    
    Detailed explanation of what this tool does, when to use it,
    and what results it returns. Be specific about use cases.
    
    Args:
        param: Parameter description
        
    Returns:
        Description of return value structure
    """
    result = await feagi.my_new_api_call(param)
    return result
```

### 3. Add Tests

In `tests/test_server.py`:

```python
@pytest.mark.asyncio
async def test_my_new_tool():
    """Test my_new_tool functionality."""
    result = await my_new_tool("test_value")
    assert "error" in result or "data" in result
```

### 4. Update Documentation

Add to `docs/API_REFERENCE.md`:

```markdown
### my_new_tool(param: str)

Brief description.

**Parameters:**
- `param` (str, required): Description

**Returns:**
...
```

## Pull Request Process

### 1. Create Feature Branch

```bash
git checkout -b feature/my-new-tool
```

### 2. Make Changes

- Write code
- Add tests
- Update documentation

### 3. Run Quality Checks

```bash
# Format code
ruff format .

# Check for issues
ruff check .

# Type checking
mypy src/

# Run tests
pytest
```

### 4. Commit

```bash
git add .
git commit -m "Add my_new_tool for X functionality"
```

### 5. Push and Create PR

```bash
git push origin feature/my-new-tool
```

Then create a pull request on GitHub with:
- Clear title describing the change
- Description of what the PR does
- Reference to any related issues
- Test results

## Commit Message Guidelines

Format:
```
<type>: <brief description>

Detailed explanation of the change, why it was needed,
and any relevant context.

Fixes #123
```

Types:
- `feat:` - New feature or tool
- `fix:` - Bug fix
- `docs:` - Documentation updates
- `test:` - Test additions or changes
- `refactor:` - Code restructuring
- `perf:` - Performance improvements
- `chore:` - Maintenance tasks

Examples:
```
feat: Add trace_signal_path tool for circuit debugging

Implements multi-hop path tracing to help LLMs debug why signals
aren't reaching their destination. Uses BFS to find all paths up
to max_hops depth.

Fixes #15
```

## Code Review

PRs will be reviewed for:
- Code quality and style
- Test coverage
- Documentation completeness
- Type safety
- Error handling
- Performance considerations

## Reporting Issues

When reporting bugs or requesting features:

1. Check existing issues first
2. Use issue templates
3. Include:
   - Python version
   - MCP SDK version
   - FEAGI version
   - Reproduction steps
   - Expected vs actual behavior
   - Relevant logs

## Questions?

- GitHub Discussions: https://github.com/Neuraville/feagi-mcp/discussions
- Discord: https://discord.gg/feagi
- Email: feagi@neuraville.com

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 License.
