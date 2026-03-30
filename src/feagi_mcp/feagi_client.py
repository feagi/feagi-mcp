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
                f"{self.base_url}/v1/monitoring/cortical_activity",
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
        _potential: float,
        _duration_ms: int = 100,
    ) -> dict[str, Any]:
        """Stimulate a cortical area with a specific potential.

        Args:
            area_id: Cortical area identifier
            coordinates: [x, y, z] coordinates within the area
            potential: Stimulation potential value
            duration_ms: Duration of stimulation in milliseconds (currently unused by API)

        Returns:
            Stimulation result
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/agent/manual_stimulation",
                json={
                    "stimulation_payload": {area_id: [coordinates]},
                    "mode": "force_fire",
                },
            )
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": result.get("success", False),
                    "neurons_stimulated": result.get("unique_neuron_ids", 0),
                    "matched_coordinates": result.get("matched_coordinates", 0),
                    "mode": result.get("mode", "unknown"),
                }
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

    async def get_burst_engine_status(self) -> dict[str, Any]:
        """Get burst engine runtime status."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/burst_engine/status")
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_burst_engine_status failed: {e}")
            return {"error": str(e)}

    async def get_runtime_metrics(self) -> dict[str, Any]:
        """Get comprehensive runtime metrics."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/monitoring/metrics")
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_runtime_metrics failed: {e}")
            return {"error": str(e)}

    async def get_cortical_synapse_counts(self, area_id: str) -> dict[str, Any]:
        """Get synapse counts for a cortical area."""
        try:
            incoming_response = await self._client.get(
                f"{self.base_url}/v1/cortical_area/{area_id}/incoming_count"
            )
            outgoing_response = await self._client.get(
                f"{self.base_url}/v1/cortical_area/{area_id}/outgoing_count"
            )

            result = {"area_id": area_id}

            if incoming_response.status_code == 200:
                result["incoming_synapses"] = incoming_response.json()
            else:
                result["incoming_synapses"] = {
                    "error": f"HTTP {incoming_response.status_code}",
                    "message": incoming_response.text,
                }

            if outgoing_response.status_code == 200:
                result["outgoing_synapses"] = outgoing_response.json()
            else:
                result["outgoing_synapses"] = {
                    "error": f"HTTP {outgoing_response.status_code}",
                    "message": outgoing_response.text,
                }

            return result
        except Exception as e:
            logger.error(f"get_cortical_synapse_counts failed: {e}")
            return {"error": str(e), "area_id": area_id}

    async def get_registered_agents(self) -> dict[str, Any]:
        """Get list of registered agents."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/agent/list")
            if response.status_code == 200:
                agent_ids = response.json()
                if isinstance(agent_ids, list):
                    return {"agent_ids": agent_ids, "count": len(agent_ids)}
                return agent_ids
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_registered_agents failed: {e}")
            return {"error": str(e)}

    async def get_agent_properties(self, agent_id: str) -> dict[str, Any]:
        """Get properties for a specific agent."""
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/agent/capabilities/all",
                params={"include_device_registrations": "false"},
            )
            if response.status_code == 200:
                all_agents = response.json()
                if agent_id in all_agents:
                    return {
                        "agent_id": agent_id,
                        **all_agents[agent_id],
                    }
                return {"error": f"Agent {agent_id} not found"}
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_agent_properties failed: {e}")
            return {"error": str(e)}

    async def get_agent_device_registrations(self, agent_id: str) -> dict[str, Any]:
        """Get device registrations for an agent."""
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/agent/capabilities/all",
                params={"include_device_registrations": "true"},
            )
            if response.status_code == 200:
                all_agents = response.json()
                if agent_id in all_agents:
                    agent_data = all_agents[agent_id]
                    return {
                        "agent_id": agent_id,
                        "agent_name": agent_data.get("agent_name", "unknown"),
                        "capabilities": agent_data.get("capabilities", {}),
                        "device_registrations": agent_data.get("capabilities", {}).get(
                            "device_registrations", {}
                        ),
                    }
                return {"error": f"Agent {agent_id} not found in capabilities"}
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_agent_device_registrations failed: {e}")
            return {"error": str(e)}

    async def list_opu_areas(self) -> list[str]:
        """List all OPU cortical area IDs."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/cortical_area/opu")
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.error(f"list_opu_areas failed: {e}")
            return []

    async def list_ipu_areas(self) -> list[str]:
        """List all IPU cortical area IDs."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/cortical_area/ipu")
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            logger.error(f"list_ipu_areas failed: {e}")
            return []

    async def create_cortical_area(
        self,
        name: str,
        cortical_type: str,
        dimensions: list[int],
        position: list[int],
        neurons_per_voxel: int = 1,
        device_count: int = 1,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new cortical area."""
        try:
            request_data = {
                "cortical_name": name,
                "cortical_type": cortical_type,
                "cortical_dimensions": dimensions,
                "coordinates_3d": position,
            }

            if properties:
                request_data.update(properties)

            if cortical_type in ["OPU", "IPU"]:
                request_data["device_count"] = device_count
                request_data["neurons_per_voxel"] = neurons_per_voxel
                response = await self._client.post(
                    f"{self.base_url}/v1/cortical_area/cortical_area",
                    json=request_data,
                )
            else:
                request_data["cortical_dimensions"] = dimensions
                response = await self._client.post(
                    f"{self.base_url}/v1/cortical_area/custom_cortical_area",
                    json=request_data,
                )

            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"create_cortical_area failed: {e}")
            return {"error": str(e)}

    async def update_cortical_area(
        self, cortical_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Update properties of an existing cortical area."""
        try:
            request_data = {"cortical_id": cortical_id}
            request_data.update(updates)

            response = await self._client.put(
                f"{self.base_url}/v1/cortical_area/cortical_area",
                json=request_data,
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"update_cortical_area failed: {e}")
            return {"error": str(e)}

    async def delete_cortical_area(self, cortical_id: str) -> dict[str, Any]:
        """Delete a cortical area."""
        try:
            response = await self._client.delete(
                f"{self.base_url}/v1/cortical_area/cortical_area",
                json={"cortical_id": cortical_id},
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"delete_cortical_area failed: {e}")
            return {"error": str(e)}

    async def get_cortical_mapping(self, src_area: str, dst_area: str) -> dict[str, Any]:
        """Get cortical mapping configuration between two areas."""
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/cortical_mapping/mapping_properties",
                json={"src_cortical_area": src_area, "dst_cortical_area": dst_area},
            )
            if response.status_code == 200:
                return {"src_area": src_area, "dst_area": dst_area, "rules": response.json()}
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_cortical_mapping failed: {e}")
            return {"error": str(e)}

    async def update_cortical_mapping(
        self, src_area: str, dst_area: str, mapping_rules: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create or update connections between two cortical areas."""
        try:
            response = await self._client.put(
                f"{self.base_url}/v1/cortical_mapping/mapping_properties",
                json={
                    "src_cortical_area": src_area,
                    "dst_cortical_area": dst_area,
                    "mapping_string": mapping_rules,
                },
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"update_cortical_mapping failed: {e}")
            return {"error": str(e)}

    async def delete_cortical_mapping(self, src_area: str, dst_area: str) -> dict[str, Any]:
        """Delete connections between two cortical areas."""
        try:
            response = await self._client.delete(
                f"{self.base_url}/v1/cortical_mapping/mapping",
                json={"src_cortical_area": src_area, "dst_cortical_area": dst_area},
            )
            if response.status_code == 200:
                return response.json()
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"delete_cortical_mapping failed: {e}")
            return {"error": str(e)}
