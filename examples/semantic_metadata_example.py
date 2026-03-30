"""Example: Using semantic metadata to understand OPU areas."""

import asyncio
from feagi_mcp.feagi_client import FeagiClient


async def main():
    """Demonstrate semantic metadata usage."""
    client = FeagiClient(host="localhost", port=8000)
    
    print("=" * 70)
    print("FEAGI Output Areas with Semantic Metadata")
    print("=" * 70)
    
    try:
        areas = await client.list_opu_areas_with_metadata()
        
        for area in areas:
            print(f"\n{'─' * 70}")
            print(f"Area: {area.get('name', 'Unknown')}")
            print(f"ID: {area['id']}")
            print(f"Type: {area['area_type']} ({area['category']})")
            print(f"Purpose: {area['purpose']}")
            print(f"Capabilities: {', '.join(area['capabilities'])}")
            print(f"Supported Devices: {', '.join(area['supported_devices'])}")
            print(f"Data Format: {area['data_format']}")
            print(f"Typical Use: {area['typical_use']}")
            print(f"Connected Devices: {area.get('device_count', 0)}")
        
        print(f"\n{'=' * 70}")
        print(f"Total Output Areas: {len(areas)}")
        print("=" * 70)
        
        print("\n\nGetting specific area info...")
        if areas:
            first_area_id = areas[0]['id']
            specific_info = await client.get_area_semantic_info(first_area_id)
            print(f"\nDetailed info for {first_area_id}:")
            print(f"  Category: {specific_info['category']}")
            print(f"  Purpose: {specific_info['purpose']}")
            print(f"  Can control: {', '.join(specific_info['supported_devices'])}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
