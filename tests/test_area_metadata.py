"""Tests for area metadata functionality."""

import pytest
from feagi_mcp.area_metadata import (
    get_area_type_from_id,
    get_semantic_info,
    enrich_area_list,
    enrich_area_with_name,
)


def test_get_area_type_from_id():
    """Test extracting area type from cortical ID."""
    test_cases = [
        ("b21vdAUAAAA=", "omot"),
        ("b2dhegIAAAA=", "ogaz"),
        ("b2ltZwkAAAA=", "oimg"),
        ("aXN2aQkAAAA=", "isvi"),
        ("aXRlbgoAAAA=", "iten"),
    ]
    
    for cortical_id, expected_type in test_cases:
        result = get_area_type_from_id(cortical_id)
        assert result == expected_type, f"Expected {expected_type}, got {result} for {cortical_id}"


def test_get_semantic_info():
    """Test getting semantic information for an area."""
    result = get_semantic_info("b21vdAUAAAA=")
    
    assert result["area_type"] == "omot"
    assert result["category"] == "motor_control"
    assert "purpose" in result
    assert "capabilities" in result
    assert isinstance(result["capabilities"], list)
    assert "supported_devices" in result
    assert "data_format" in result
    assert "typical_use" in result


def test_get_semantic_info_unknown():
    """Test semantic info for unknown area type."""
    result = get_semantic_info("dW5rbm93bg==")
    
    assert result["area_type"] == "unknown"
    assert result["category"] == "unknown"
    assert result["purpose"] == "Unknown cortical area type"


def test_enrich_area_list():
    """Test enriching a list of area IDs."""
    area_ids = ["b21vdAUAAAA=", "b2dhegIAAAA="]
    
    result = enrich_area_list(area_ids)
    
    assert len(result) == 2
    assert all("id" in item for item in result)
    assert all("area_type" in item for item in result)
    assert all("category" in item for item in result)
    assert all("purpose" in item for item in result)
    
    assert result[0]["id"] == "b21vdAUAAAA="
    assert result[0]["area_type"] == "omot"
    assert result[1]["id"] == "b2dhegIAAAA="
    assert result[1]["area_type"] == "ogaz"


def test_enrich_area_with_name():
    """Test enriching an area with name and device count."""
    result = enrich_area_with_name("b21vdAUAAAA=", "Motor Output", 5)
    
    assert result["id"] == "b21vdAUAAAA="
    assert result["name"] == "Motor Output"
    assert result["device_count"] == 5
    assert result["area_type"] == "omot"
    assert result["category"] == "motor_control"
    assert "purpose" in result
    assert "capabilities" in result


def test_all_area_types_have_metadata():
    """Test that all defined area types have complete metadata."""
    from feagi_mcp.area_metadata import CORTICAL_TYPE_METADATA
    
    required_keys = [
        "category",
        "type",
        "purpose",
        "capabilities",
        "supported_devices",
        "data_format",
        "typical_use",
    ]
    
    for area_type, metadata in CORTICAL_TYPE_METADATA.items():
        for key in required_keys:
            assert key in metadata, f"Area type {area_type} missing key: {key}"
        
        assert isinstance(metadata["capabilities"], list)
        assert isinstance(metadata["supported_devices"], list)
        assert len(metadata["purpose"]) > 0
        assert len(metadata["typical_use"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
