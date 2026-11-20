"""Load a JSON list of stimulus steps (or schedule entries) from a file.

Long protocols (for example replaying recorded body values) would cost tokens per step when
passed inline; ``steps_file`` lets the caller write the list to disk once and pass the path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STEPS_FILE_MAX_BYTES = 50_000_000


def load_steps_file(
    path: Any, what: str = "steps"
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Return ``(items, None)`` or ``(None, error_message)``.

    The file must hold a JSON array of objects in the same format as the inline argument.
    """
    if not isinstance(path, str) or not path.strip():
        return None, "steps_file must be a non-empty path string"
    try:
        p = Path(path.strip()).expanduser()
        if not p.is_file():
            return None, f"steps_file {str(p)!r} does not exist or is not a file"
        size = p.stat().st_size
        if size > STEPS_FILE_MAX_BYTES:
            return None, f"steps_file is {size} bytes; the limit is {STEPS_FILE_MAX_BYTES}"
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, f"steps_file is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})"
    except (OSError, UnicodeDecodeError) as e:
        return None, f"steps_file could not be read: {e}"
    if not isinstance(data, list):
        return None, f"steps_file must hold a JSON list of {what}, got {type(data).__name__}"
    if not data:
        return None, f"steps_file holds an empty list; {what} must be non-empty"
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return None, f"steps_file item {i} must be an object, got {type(item).__name__}"
    return data, None


def resolve_steps(
    inline: list[dict[str, Any]] | None, steps_file: str | None, what: str = "steps"
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Pick the inline list or the file's list; exactly one must be given."""
    if steps_file is not None and inline:
        return None, f"pass either {what} or steps_file, not both"
    if steps_file is not None:
        return load_steps_file(steps_file, what)
    if not inline:
        return None, f"{what} must be non-empty (or pass steps_file)"
    return inline, None
