"""Cortical area metadata for semantic information about area types and capabilities."""

from typing import Any

CORTICAL_TYPE_METADATA = {
    "opse": {
        "category": "motor_control",
        "type": "servo_motor",
        "purpose": "Controls servo motors with precise angular positioning",
        "capabilities": ["angular_control", "absolute_positioning", "incremental_control"],
        "supported_devices": ["servo", "actuator"],
        "data_format": "angle_commands",
        "typical_use": "Robot joint control, camera positioning, gripper control",
    },
    "omot": {
        "category": "motor_control",
        "type": "general_motor",
        "purpose": "Controls general motor outputs and movement actuators",
        "capabilities": ["velocity_control", "direction_control"],
        "supported_devices": ["dc_motor", "stepper_motor", "velocity_controller"],
        "data_format": "velocity_commands",
        "typical_use": "Wheel motors, linear actuators, continuous rotation motors",
    },
    "ogaz": {
        "category": "vision_control",
        "type": "gaze_control",
        "purpose": "Controls camera gaze direction and eye movement",
        "capabilities": ["pan_control", "tilt_control", "focus_control"],
        "supported_devices": ["camera_gimbal", "eye_actuator"],
        "data_format": "pan_tilt_coordinates",
        "typical_use": "Camera positioning, visual attention, eye tracking systems",
    },
    "oimg": {
        "category": "vision_output",
        "type": "image_output",
        "purpose": "Generates visual output and image data",
        "capabilities": ["image_generation", "visual_feedback"],
        "supported_devices": ["display", "image_processor"],
        "data_format": "image_data",
        "typical_use": "Visual imagination, image generation, visual feedback",
    },
    "oseg": {
        "category": "vision_processing",
        "type": "object_segmentation",
        "purpose": "Outputs segmented object detection and classification",
        "capabilities": ["object_detection", "image_segmentation", "classification"],
        "supported_devices": ["vision_processor", "object_detector"],
        "data_format": "segmentation_masks",
        "typical_use": "Object recognition, scene understanding, visual categorization",
    },
    "onet": {
        "category": "language",
        "type": "text_output",
        "purpose": "Generates natural language text output",
        "capabilities": ["text_generation", "language_output", "communication"],
        "supported_devices": ["text_interface", "speech_synthesizer"],
        "data_format": "text_strings",
        "typical_use": "Language generation, communication, text responses",
    },
    "ocnt": {
        "category": "control",
        "type": "counter_control",
        "purpose": "Generates counter or control signals",
        "capabilities": ["counting", "control_signals", "state_tracking"],
        "supported_devices": ["counter", "state_controller"],
        "data_format": "numeric_values",
        "typical_use": "Counting tasks, state management, control logic",
    },
    "isvi": {
        "category": "vision_input",
        "type": "visual_sensor",
        "purpose": "Processes visual input from cameras or image sensors",
        "capabilities": ["image_input", "visual_processing"],
        "supported_devices": ["camera", "image_sensor"],
        "data_format": "raw_image_data",
        "typical_use": "Camera input, visual perception, image capture",
    },
    "iten": {
        "category": "language_input",
        "type": "text_input",
        "purpose": "Processes natural language text input",
        "capabilities": ["text_input", "language_understanding"],
        "supported_devices": ["keyboard", "text_interface"],
        "data_format": "text_strings",
        "typical_use": "Text input, language understanding, command parsing",
    },
    "icnt": {
        "category": "control_input",
        "type": "counter_input",
        "purpose": "Receives counter or control input signals",
        "capabilities": ["counting_input", "state_input"],
        "supported_devices": ["counter_sensor", "state_monitor"],
        "data_format": "numeric_values",
        "typical_use": "State monitoring, counter input, control feedback",
    },
}


def get_area_type_from_id(cortical_id: str) -> str:
    """Extract the area type prefix from a cortical ID.
    
    Args:
        cortical_id: Encoded cortical ID (e.g., "b21vdAUAAAA=")
        
    Returns:
        Area type prefix (e.g., "omot", "isvi")
    """
    try:
        import base64
        decoded = base64.b64decode(cortical_id).decode('utf-8', errors='ignore')
        for area_type in CORTICAL_TYPE_METADATA:
            if decoded.startswith(area_type):
                return area_type
        return "unknown"
    except Exception:
        return "unknown"


def get_semantic_info(cortical_id: str) -> dict[str, Any]:
    """Get semantic information about a cortical area from its ID.
    
    Args:
        cortical_id: Encoded cortical ID
        
    Returns:
        Dictionary with semantic information including type, purpose, capabilities
    """
    area_type = get_area_type_from_id(cortical_id)
    
    if area_type == "unknown":
        return {
            "area_type": "unknown",
            "category": "unknown",
            "purpose": "Unknown cortical area type",
            "capabilities": [],
            "supported_devices": [],
            "data_format": "unknown",
            "typical_use": "No metadata available",
        }
    
    metadata = CORTICAL_TYPE_METADATA[area_type].copy()
    metadata["area_type"] = area_type
    return metadata


def enrich_area_list(areas: list[str]) -> list[dict[str, Any]]:
    """Enrich a list of cortical area IDs with semantic metadata.
    
    Args:
        areas: List of encoded cortical IDs
        
    Returns:
        List of dictionaries with ID and semantic information
    """
    enriched = []
    for area_id in areas:
        info = get_semantic_info(area_id)
        info["id"] = area_id
        enriched.append(info)
    return enriched


def enrich_area_with_name(area_id: str, area_name: str, device_count: int = 0) -> dict[str, Any]:
    """Enrich a cortical area with its name, device count, and semantic metadata.
    
    Args:
        area_id: Encoded cortical ID
        area_name: Human-readable area name
        device_count: Number of connected devices
        
    Returns:
        Dictionary with complete area information
    """
    info = get_semantic_info(area_id)
    info["id"] = area_id
    info["name"] = area_name
    info["device_count"] = device_count
    return info
