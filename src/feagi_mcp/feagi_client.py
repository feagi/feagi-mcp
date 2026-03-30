"""HTTP client for FEAGI REST API."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class FeagiClient:
    """Client for interacting with FEAGI REST API."""

    def __init__(self, host: str = "localhost", port: int = 8000, timeout: float = 30.0):
        """Initialize FEAGI client.

        Args:
            host: FEAGI server hostname
            port: FEAGI REST API port
            timeout: Request timeout in seconds
        """
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def health_check(self) -> dict[str, Any]:
        """Check if FEAGI is reachable."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/genome/name")
            return {"status": "ok", "genome_name": response.json()}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "error", "message": str(e)}

    async def monitor_activity(self, area_id: str, duration_ms: int = 1000) -> dict[str, Any]:
        """Monitor cortical area activity.

        Args:
            area_id: Cortical area identifier
            duration_ms: Monitoring duration in milliseconds

        Returns:
            Activity data including firing rate and active neurons
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/monitor/cortical_activity",
                params={"area": area_id, "duration": duration_ms / 1000.0},
            )
            if response.status_code == 200:
                return response.json()
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"monitor_activity failed: {e}")
            return {"error": "request_failed", "message": str(e)}

    async def list_cortical_areas(self) -> list[dict[str, Any]]:
        """List all cortical areas in the current genome."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/cortical_area/list")
            if response.status_code == 200:
                return response.json()
            logger.error(f"list_cortical_areas failed: HTTP {response.status_code}")
            return []
        except Exception as e:
            logger.error(f"list_cortical_areas failed: {e}")
            return []

    async def get_genome_info(self) -> dict[str, Any]:
        """Get current genome metadata."""
        try:
            name_response = await self._client.get(f"{self.base_url}/v1/genome/name")
            genome_name = name_response.json() if name_response.status_code == 200 else "unknown"

            return {
                "genome_name": genome_name,
                "status": "loaded",
            }
        except Exception as e:
            logger.error(f"get_genome_info failed: {e}")
            return {"error": str(e)}

    async def download_genome(self) -> dict[str, Any]:
        """Download complete genome configuration."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/genome/download")
            if response.status_code == 200:
                return response.json()
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"download_genome failed: {e}")
            return {"error": str(e)}

    async def upload_genome(self, genome_data: dict[str, Any]) -> dict[str, Any]:
        """Upload a genome to FEAGI.

        Args:
            genome_data: Complete genome JSON structure

        Returns:
            Upload result with success status
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/genome/upload",
                json=genome_data,
            )
            if response.status_code == 200:
                return response.json()
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
                "success": False,
            }
        except Exception as e:
            logger.error(f"upload_genome failed: {e}")
            return {"error": str(e), "success": False}

    async def get_connectivity(self, src_area: str, dst_area: str) -> dict[str, Any]:
        """Get connectivity information between two cortical areas.

        Args:
            src_area: Source cortical area ID
            dst_area: Destination cortical area ID

        Returns:
            Connection details including synapse count and morphology
        """
        try:
            genome = await self.download_genome()
            if "error" in genome:
                return genome

            blueprint = genome.get("blueprint", {})
            connections = []
            synapse_count = 0

            for key, value in blueprint.items():
                if (
                    "dstmap-d" in key
                    and src_area in key
                    and isinstance(value, dict)
                    and dst_area in value
                ):
                    dst_connections = value[dst_area]
                    if isinstance(dst_connections, list):
                        for conn in dst_connections:
                            connections.append(conn)
                            synapse_count += 1

            if not connections:
                return {
                    "connected": False,
                    "synapse_count": 0,
                    "message": f"No connections found from {src_area} to {dst_area}",
                }

            return {
                "connected": True,
                "synapse_count": synapse_count,
                "connections": connections,
                "src_area": src_area,
                "dst_area": dst_area,
            }
        except Exception as e:
            logger.error(f"get_connectivity failed: {e}")
            return {"error": str(e)}

    async def get_area_parameters(self, area_id: str) -> dict[str, Any]:
        """Get parameters for a specific cortical area.

        Args:
            area_id: Cortical area identifier

        Returns:
            Area parameters including dimensions, neuron properties
        """
        try:
            genome = await self.download_genome()
            if "error" in genome:
                return genome

            blueprint = genome.get("blueprint", {})
            params = {}

            for key, value in blueprint.items():
                if area_id in key:
                    param_name = key.split("-")[-1]
                    params[param_name] = value

            if not params:
                return {"error": f"Area {area_id} not found"}

            return {
                "area_id": area_id,
                "parameters": params,
            }
        except Exception as e:
            logger.error(f"get_area_parameters failed: {e}")
            return {"error": str(e)}

    async def stimulate_area(
        self,
        area_id: str,
        coordinates: list[int],
        potential: float,
        duration_ms: int = 100,
    ) -> dict[str, Any]:
        """Stimulate a cortical area with a specific potential.

        Args:
            area_id: Cortical area identifier
            coordinates: [x, y, z] coordinates within the area
            potential: Stimulation potential value
            duration_ms: Duration of stimulation in milliseconds

        Returns:
            Stimulation result
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/stimulate",
                json={
                    "area_id": area_id,
                    "coordinates": coordinates,
                    "potential": potential,
                    "duration_ms": duration_ms,
                },
            )
            if response.status_code == 200:
                return {"success": True, "message": "Stimulation sent"}
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"stimulate_area failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_embodiment_status(self) -> dict[str, Any]:
        """Get status of connected embodiment controllers."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/embodiment/status")
            if response.status_code == 200:
                return response.json()

            genome = await self.download_genome()
            if "error" not in genome:
                opu_areas = []
                ipu_areas = []
                blueprint = genome.get("blueprint", {})

                for key, value in blueprint.items():
                    if "__name-t" in key:
                        group_key = key.replace("__name-t", "_group-t")
                        group = blueprint.get(group_key, "")
                        if group == "OPU":
                            area_id = key.split("-cx-")[0].replace("_____10c-", "")
                            device_count_key = key.replace("__name-t", "devcnt-i")
                            device_count = blueprint.get(device_count_key, 0)
                            opu_areas.append(
                                {
                                    "name": value,
                                    "id": area_id,
                                    "device_count": device_count,
                                }
                            )
                        elif group == "IPU":
                            area_id = key.split("-cx-")[0].replace("_____10c-", "")
                            device_count_key = key.replace("__name-t", "devcnt-i")
                            device_count = blueprint.get(device_count_key, 0)
                            ipu_areas.append(
                                {
                                    "name": value,
                                    "id": area_id,
                                    "device_count": device_count,
                                }
                            )

                return {
                    "status": "genome_info",
                    "opu_areas": opu_areas,
                    "ipu_areas": ipu_areas,
                    "message": "Embodiment status endpoint unavailable, showing genome I/O config",
                }

            return {"error": "Could not retrieve embodiment status"}
        except Exception as e:
            logger.error(f"get_embodiment_status failed: {e}")
            return {"error": str(e)}
