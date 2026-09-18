"""Circuit naming policy: function-based region titles, no Autogen Circuit."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.circuit_naming import (
    extract_region_title,
    parent_circuit_naming_error,
    validate_circuit_title,
)
from feagi_mcp.feagi_client import FeagiClient


def test_validate_accepts_function_titles() -> None:
    for title in ("Sit", "Sit Drive", "Walk CPG", "OR Gate", "Balance", "Mohammad"):
        assert validate_circuit_title(title) is None


def test_validate_rejects_placeholders() -> None:
    for title in (
        "",
        "   ",
        "Autogen Circuit",
        "untitled",
        "New Circuit",
        "Circuit",
        "MCP Circuit",
        "McpSit",
        "00000000-0000-0000-0000-000000000001",
        "123",
    ):
        err = validate_circuit_title(title)
        assert err is not None
        assert "create_brain_region" in err


def test_extract_region_title_reads_title_only() -> None:
    members = {
        "reg-1": {"title": "Sit", "areas": ["a"]},
        "reg-2": {"name": "Walk"},
    }
    assert extract_region_title(members, "reg-1") == "Sit"
    assert extract_region_title(members, "reg-2") is None
    assert extract_region_title(members, "missing") is None


def test_parent_error_for_autogen_and_missing() -> None:
    missing = parent_circuit_naming_error(None, "reg-missing")
    assert missing is not None
    assert "reg-missing" in missing

    autogen = parent_circuit_naming_error("Autogen Circuit", "reg-auto")
    assert autogen is not None
    assert "Autogen Circuit" in autogen
    assert "create_brain_region" in autogen

    assert parent_circuit_naming_error("Sit", "reg-sit") is None


@pytest.fixture
def mock_client() -> FeagiClient:
    client = FeagiClient()
    client._client = AsyncMock()
    return client


class TestCreateBrainRegionNaming:
    """create_brain_region enforces function titles before POST."""

    @pytest.mark.asyncio
    async def test_rejects_autogen_circuit_without_post(self, mock_client):
        result = await mock_client.create_brain_region(
            "Autogen Circuit",
            [0, 0],
            [0, 0, 0],
        )
        assert result.get("error")
        assert "Autogen Circuit" in result["error"] or "placeholder" in result["error"]
        mock_client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_sit_and_posts(self, mock_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "region_id": "sit-uuid",
            "title": "Sit",
        }
        mock_client._client.post.return_value = mock_response

        result = await mock_client.create_brain_region("Sit", [10, 20], [0, 0, 0])

        assert result["title"] == "Sit"
        mock_client._client.post.assert_called_once()


class TestCreateCorticalAreaCircuitParent:
    """CUSTOM/MEMORY create looks up parent title and refuses placeholders."""

    @pytest.mark.asyncio
    async def test_rejects_autogen_parent_without_post(self, mock_client):
        mock_client.get_regions_members = AsyncMock(
            return_value={
                "auto-1": {"title": "Autogen Circuit"},
            }
        )
        result = await mock_client.create_cortical_area(
            name="babble",
            cortical_type="CUSTOM",
            dimensions=[5, 5, 5],
            position=[50, 50, 0],
            brain_region_id="auto-1",
            skip_placement_validation=True,
        )
        assert result.get("error")
        assert "Autogen Circuit" in result["error"] or "functional" in result["error"]
        mock_client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_missing_region(self, mock_client):
        mock_client.get_regions_members = AsyncMock(return_value={"other": {"title": "Sit"}})
        result = await mock_client.create_cortical_area(
            name="babble",
            cortical_type="CUSTOM",
            dimensions=[5, 5, 5],
            position=[50, 50, 0],
            brain_region_id="missing-id",
            skip_placement_validation=True,
        )
        assert result.get("error")
        assert "missing-id" in result["error"]
        mock_client._client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_sit_parent(self, mock_client):
        mock_client.get_regions_members = AsyncMock(return_value={"sit-1": {"title": "Sit"}})
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"cortical_id": "Y2JhYmJsZaw="}
        mock_client._client.post.return_value = mock_response

        result = await mock_client.create_cortical_area(
            name="babble",
            cortical_type="CUSTOM",
            dimensions=[5, 5, 5],
            position=[50, 50, 0],
            brain_region_id="sit-1",
            skip_placement_validation=True,
        )
        assert result["cortical_id"] == "Y2JhYmJsZaw="
        mock_client._client.post.assert_called_once()


class TestCloneParentCircuitNaming:
    """clone with parent_region_id uses the same parent-title gate."""

    @pytest.mark.asyncio
    async def test_clone_rejects_untitled_parent(self, mock_client):
        mock_client.get_regions_members = AsyncMock(return_value={"auto-1": {"title": "Untitled"}})
        result = await mock_client.clone_cortical_area_via_api(
            source_area_id="src",
            new_name="copy",
            coordinates_3d=[50, 50, 0],
            coordinates_2d=[0, 0],
            clone_cortical_mapping=True,
            parent_region_id="auto-1",
        )
        assert result.get("error")
        mock_client._client.post.assert_not_called()
