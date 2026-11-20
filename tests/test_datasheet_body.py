"""Datasheet body key: shared fixture (same cases in all four validators), vendored vocabulary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feagi_mcp.datasheet import BODY_ROLES_PATH, validate_author_fields

FIXTURE = json.loads((Path(__file__).with_name("body-datasheet-fixtures.json")).read_text("utf-8"))
CASES = FIXTURE["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_fixture(case: dict) -> None:
    errors = validate_author_fields(case["datasheet"])
    if case["valid"]:
        assert errors == []
    else:
        assert any(case["error_path"] in e for e in errors), errors


def test_vendored_roles_vocabulary_is_the_nrs_one() -> None:
    doc = json.loads(BODY_ROLES_PATH.read_text("utf-8"))
    assert doc["format"] == "nrs.body_roles/1"
    assert {f["id"] for f in doc["families"]} == {"human", "serial_arm"}
