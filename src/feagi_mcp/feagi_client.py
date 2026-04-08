"""HTTP client for FEAGI REST API."""

import logging
from typing import Any, cast

import httpx

from feagi_mcp.area_metadata import enrich_area_list, enrich_area_with_name, get_semantic_info
from feagi_mcp.bv_operations import BV_OPERATION_BY_ID, resolve_path
from feagi_mcp.placement_policy import (
    check_min_separation_to_existing,
    check_origin_exclusion,
)

logger = logging.getLogger(__name__)


def _as_json_dict(data: Any) -> dict[str, Any]:
    """Narrow ``response.json()`` / API payloads to ``dict`` for strict typing."""
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return {}


def _as_json_list_str(data: Any) -> list[str]:
    """Narrow JSON list payloads to ``list[str]`` (OPU/IPU id lists, etc.)."""
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


def _normalize_cortical_area_list_payload(data: Any) -> list[dict[str, Any]]:
    """Turn API JSON into a list of area dicts.

    Rust feagi-api returns ``{ "area_id": { ... } }`` from connectome detailed list;
    older Python FEAGI may return a JSON array.
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        out: list[dict[str, Any]] = []
        for cortical_id, val in data.items():
            if isinstance(val, dict):
                merged = dict(val)
                merged.setdefault("cortical_id", cortical_id)
                out.append(merged)
            else:
                out.append({"cortical_id": cortical_id, "data": val})
        return out
    return []


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
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"monitor_activity failed: {e}")
            return {"error": "request_failed", "message": str(e)}

    async def list_cortical_areas(self) -> list[dict[str, Any]]:
        """List all cortical areas in the current genome."""
        detailed = f"{self.base_url}/v1/connectome/cortical_areas/list/detailed"
        legacy = f"{self.base_url}/v1/cortical_area/list"
        try:
            response = await self._client.get(detailed)
            if response.status_code == 200:
                return _normalize_cortical_area_list_payload(response.json())
            logger.warning(
                "list_cortical_areas: GET %s returned HTTP %s; trying legacy %s",
                detailed,
                response.status_code,
                legacy,
            )
            response = await self._client.get(legacy)
            if response.status_code == 200:
                return _normalize_cortical_area_list_payload(response.json())
            logger.error(
                "list_cortical_areas failed: HTTP %s body=%s",
                response.status_code,
                (response.text or "")[:800],
            )
            return []
        except Exception as e:
            logger.error(f"list_cortical_areas failed: {e}")
            return []

    async def list_cortical_area_names(self) -> list[str]:
        """Get simple list of all cortical area names."""
        try:
            url = f"{self.base_url}/v1/cortical_area/cortical_area_name_list"
            response = await self._client.get(url)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    raw = data.get("cortical_area_name_list", [])
                    if isinstance(raw, list):
                        return [str(x) for x in raw]
                return []
            logger.error(f"list_cortical_area_names failed: HTTP {response.status_code}")
            return []
        except Exception as e:
            logger.error(f"list_cortical_area_names failed: {e}")
            return []

    async def list_morphologies(self) -> dict[str, Any]:
        """Get all morphology definitions including connectivity rules."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/morphology/morphologies")
            if response.status_code == 200:
                return _as_json_dict(response.json())
            logger.error(f"list_morphologies failed: HTTP {response.status_code}")
            return {}
        except Exception as e:
            logger.error(f"list_morphologies failed: {e}")
            return {}

    async def get_genome_info(self) -> dict[str, Any]:
        """Get current genome metadata."""
        try:
            name_response = await self._client.get(f"{self.base_url}/v1/genome/name")
            if name_response.status_code == 200:
                gn: Any = name_response.json()
                genome_name: str = gn if isinstance(gn, str) else str(gn)
            else:
                genome_name = "unknown"

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
                return _as_json_dict(response.json())
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
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
                "success": False,
            }
        except Exception as e:
            logger.error(f"upload_genome failed: {e}")
            return {"error": str(e), "success": False}

    async def load_barebones_genome(self) -> dict[str, Any]:
        """Load the barebones genome (minimal core areas).

        Returns:
            Load result with success status and cortical area count
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/genome/upload/barebones",
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
                "success": False,
            }
        except Exception as e:
            logger.error(f"load_barebones_genome failed: {e}")
            return {"error": str(e), "success": False}

    async def create_morphology(
        self,
        morphology_name: str,
        morphology_type: str,
        morphology_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a custom morphology definition.

        Args:
            morphology_name: Unique morphology name
            morphology_type: Type (vectors, patterns, functions, composite)
            morphology_parameters: Type-specific parameters

        Returns:
            Status of morphology creation
        """
        try:
            payload = {
                "morphology_name": morphology_name,
                "morphology_type": morphology_type,
                "morphology_parameters": morphology_parameters,
            }
            response = await self._client.post(
                f"{self.base_url}/v1/morphology/morphology", json=payload
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
                "success": False,
            }
        except Exception as e:
            logger.error(f"create_morphology failed: {e}")
            return {"error": str(e), "success": False}

    async def get_cortical_area_geometry(self) -> dict[str, Any]:
        """Get full geometry info for all cortical areas.

        Uses the same endpoint as Brain Visualizer (`GET .../cortical_area/geometry`).

        Returns:
            Dictionary mapping cortical_id to geometry properties
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/cortical_area/cortical_area/geometry"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"get_cortical_area_geometry failed: {e}")
            return {"error": str(e)}

    async def get_cortical_id_name_mapping(self) -> dict[str, Any]:
        """GET /v1/cortical_area/cortical_id_name_mapping — same as Brain Visualizer."""
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/cortical_area/cortical_id_name_mapping"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"get_cortical_id_name_mapping failed: {e}")
            return {"error": str(e)}

    async def resolve_cortical_display_name(
        self,
        display_name: str,
        match_mode: str = "exact",
    ) -> dict[str, Any]:
        """Map a human-readable cortical name to base64 cortical_id(s).

        Args:
            display_name: Genome display name (e.g. \"Object Segmentation-0-0\").
            match_mode: \"exact\" | \"substring\" | \"icase\" (case-insensitive exact).
        """
        mapping = await self.get_cortical_id_name_mapping()
        if not isinstance(mapping, dict):
            return {"error": "invalid_mapping_response"}
        if "error" in mapping:
            return mapping

        matches: list[dict[str, str]] = []
        needle = display_name.strip()
        for cid, name in mapping.items():
            if not isinstance(name, str):
                continue
            if match_mode == "substring":
                if needle.lower() in name.lower():
                    matches.append({"cortical_id": cid, "cortical_name": name})
            elif match_mode == "icase":
                if name.strip().lower() == needle.lower():
                    matches.append({"cortical_id": cid, "cortical_name": name})
            else:
                if name.strip() == needle:
                    matches.append({"cortical_id": cid, "cortical_name": name})

        resolved = matches[0]["cortical_id"] if len(matches) == 1 else None
        return {
            "display_name": display_name,
            "match_mode": match_mode,
            "match_count": len(matches),
            "matches": matches,
            "resolved_cortical_id": resolved,
        }

    async def get_cortical_map_detailed(self) -> dict[str, Any]:
        """GET /v1/cortical_area/cortical_map_detailed — outgoing mapping graph (BV reload)."""
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/cortical_area/cortical_map_detailed"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"get_cortical_map_detailed failed: {e}")
            return {"error": str(e)}

    async def get_regions_members(self) -> dict[str, Any]:
        """GET /v1/region/regions_members — brain regions and member cortical areas (BV)."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/region/regions_members")
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"get_regions_members failed: {e}")
            return {"error": str(e)}

    async def create_brain_region(
        self,
        title: str,
        coordinates_2d: list[int],
        coordinates_3d: list[int],
        parent_region_id: str | None = None,
        region_type: str = "Undefined",
        region_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/region/region — create a brain region (hierarchy node; BV \"circuit\").

        Omitted parent_region_id: FEAGI resolves to the existing root so new regions are not
        siblings of root (matches BV single-root expectation).
        """
        try:
            trimmed = title.strip()
            if not trimmed:
                return {"error": "title must be non-empty"}
            if len(coordinates_2d) != 2:
                return {"error": "coordinates_2d must have exactly 2 integers"}
            if len(coordinates_3d) != 3:
                return {"error": "coordinates_3d must have exactly 3 integers"}
            body: dict[str, Any] = {
                "title": trimmed,
                "coordinates_2d": coordinates_2d,
                "coordinates_3d": coordinates_3d,
                "region_type": region_type,
            }
            if parent_region_id is not None and str(parent_region_id).strip():
                body["parent_region_id"] = str(parent_region_id).strip()
            if region_id is not None and str(region_id).strip():
                body["region_id"] = str(region_id).strip()
            response = await self._client.post(
                f"{self.base_url}/v1/region/region",
                json=body,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"create_brain_region failed: {e}")
            return {"error": str(e)}

    async def get_genome_file_name(self) -> dict[str, Any]:
        """GET /v1/genome/file_name — loaded genome file label."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/genome/file_name")
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"get_genome_file_name failed: {e}")
            return {"error": str(e)}

    async def save_genome_to_filesystem(
        self,
        file_path: str | None = None,
        genome_id: str | None = None,
        genome_title: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/genome/save — persist current genome JSON (Brain Visualizer save)."""
        try:
            body: dict[str, str] = {}
            if file_path:
                body["file_path"] = file_path
            if genome_id:
                body["genome_id"] = genome_id
            if genome_title:
                body["genome_title"] = genome_title
            response = await self._client.post(
                f"{self.base_url}/v1/genome/save",
                json=body,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"save_genome_to_filesystem failed: {e}")
            return {"error": str(e)}

    async def fetch_cortical_area_properties(self, cortical_id: str) -> dict[str, Any]:
        """POST cortical_area_properties: full connectome area record (BV inspector)."""
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/cortical_area/cortical_area_properties",
                json={"cortical_id": cortical_id},
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"fetch_cortical_area_properties failed: {e}")
            return {"error": str(e)}

    async def fetch_multi_cortical_area_properties(self, cortical_ids: list[str]) -> dict[str, Any]:
        """POST /v1/cortical_area/multi/cortical_area_properties — batch properties (BV)."""
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/cortical_area/multi/cortical_area_properties",
                json=cortical_ids,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"fetch_multi_cortical_area_properties failed: {e}")
            return {"error": str(e)}

    async def reset_cortical_neural_state(self, area_ids: list[str]) -> dict[str, Any]:
        """PUT /v1/cortical_area/reset — reset runtime state for areas (BV reset neurons)."""
        try:
            response = await self._client.put(
                f"{self.base_url}/v1/cortical_area/reset",
                json={"area_list": area_ids},
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"reset_cortical_neural_state failed: {e}")
            return {"error": str(e)}

    async def clone_cortical_area_via_api(
        self,
        source_area_id: str,
        new_name: str,
        coordinates_3d: list[int],
        coordinates_2d: list[int],
        clone_cortical_mapping: bool,
        parent_region_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/cortical_area/clone — duplicate custom/memory area (BV clone)."""
        try:
            payload: dict[str, Any] = {
                "source_area_id": source_area_id,
                "new_name": new_name,
                "coordinates_3d": [
                    int(coordinates_3d[0]),
                    int(coordinates_3d[1]),
                    int(coordinates_3d[2]),
                ],
                "coordinates_2d": [int(coordinates_2d[0]), int(coordinates_2d[1])],
                "clone_cortical_mapping": clone_cortical_mapping,
            }
            if parent_region_id is not None:
                payload["parent_region_id"] = parent_region_id
            response = await self._client.post(
                f"{self.base_url}/v1/cortical_area/clone",
                json=payload,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"clone_cortical_area_via_api failed: {e}")
            return {"error": str(e)}

    async def get_cortical_template(self) -> dict[str, Any]:
        """GET /v1/genome/cortical_template — IPU/OPU templates (BV template picker)."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/genome/cortical_template")
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error(f"get_cortical_template failed: {e}")
            return {"error": str(e)}

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
                result = _as_json_dict(response.json())
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

    async def stimulate_areas(
        self,
        stimulation_payload: dict[str, list[list[int]]],
        mode: str = "force_fire",
    ) -> dict[str, Any]:
        """Stimulate multiple cortical areas in one request (same burst / tick).

        Use this when several inputs must fire together (e.g. logic AND demos).

        Args:
            stimulation_payload: Map cortical_id -> list of [x, y, z] coordinate lists
            mode: Stimulation mode (default ``force_fire``)

        Returns:
            Same shape as :meth:`stimulate_area` (success, neuron counts, etc.)
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/agent/manual_stimulation",
                json={
                    "stimulation_payload": stimulation_payload,
                    "mode": mode,
                },
            )
            if response.status_code == 200:
                result = _as_json_dict(response.json())
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
            logger.error(f"stimulate_areas failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_embodiment_status(self) -> dict[str, Any]:
        """Get status of connected embodiment controllers."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/embodiment/status")
            if response.status_code == 200:
                return _as_json_dict(response.json())

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
                            enriched = enrich_area_with_name(area_id, value, device_count)
                            opu_areas.append(enriched)
                        elif group == "IPU":
                            area_id = key.split("-cx-")[0].replace("_____10c-", "")
                            device_count_key = key.replace("__name-t", "devcnt-i")
                            device_count = blueprint.get(device_count_key, 0)
                            enriched = enrich_area_with_name(area_id, value, device_count)
                            ipu_areas.append(enriched)

                return {
                    "status": "genome_info",
                    "opu_areas": opu_areas,
                    "ipu_areas": ipu_areas,
                    "message": (
                        "Embodiment status endpoint unavailable, "
                        "showing genome I/O config with semantic metadata"
                    ),
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
                return _as_json_dict(response.json())
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"get_burst_engine_status failed: {e}")
            return {"error": str(e)}

    async def get_runtime_metrics(self) -> dict[str, Any]:
        """Get comprehensive runtime metrics."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/monitoring/metrics")
            if response.status_code == 200:
                return _as_json_dict(response.json())
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

            result: dict[str, Any] = {"area_id": area_id}

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
                    ids = _as_json_list_str(agent_ids)
                    return {"agent_ids": ids, "count": len(ids)}
                if isinstance(agent_ids, dict):
                    return _as_json_dict(agent_ids)
                return {"error": "unexpected_response", "raw": agent_ids}
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
                all_agents = _as_json_dict(response.json())
                if agent_id in all_agents:
                    raw_agent = all_agents[agent_id]
                    if isinstance(raw_agent, dict):
                        return {
                            "agent_id": agent_id,
                            **cast(dict[str, Any], raw_agent),
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
                all_agents = _as_json_dict(response.json())
                if agent_id in all_agents:
                    agent_data = all_agents[agent_id]
                    if isinstance(agent_data, dict):
                        caps = agent_data.get("capabilities", {})
                        dev_reg: Any = {}
                        if isinstance(caps, dict):
                            dev_reg = caps.get("device_registrations", {})
                        return {
                            "agent_id": agent_id,
                            "agent_name": agent_data.get("agent_name", "unknown"),
                            "capabilities": caps if isinstance(caps, dict) else {},
                            "device_registrations": dev_reg,
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
                return _as_json_list_str(response.json())
            return []
        except Exception as e:
            logger.error(f"list_opu_areas failed: {e}")
            return []

    async def list_opu_areas_with_metadata(self) -> list[dict[str, Any]]:
        """List all OPU areas with semantic metadata about their type and capabilities.

        Returns:
            List of dictionaries with ID, type, purpose, capabilities, and usage info
        """
        try:
            areas = await self.list_opu_areas()
            return enrich_area_list(areas)
        except Exception as e:
            logger.error(f"list_opu_areas_with_metadata failed: {e}")
            return []

    async def list_ipu_areas(self) -> list[str]:
        """List all IPU cortical area IDs."""
        try:
            response = await self._client.get(f"{self.base_url}/v1/cortical_area/ipu")
            if response.status_code == 200:
                return _as_json_list_str(response.json())
            return []
        except Exception as e:
            logger.error(f"list_ipu_areas failed: {e}")
            return []

    async def list_ipu_areas_with_metadata(self) -> list[dict[str, Any]]:
        """List all IPU areas with semantic metadata about their type and capabilities.

        Returns:
            List of dictionaries with ID, type, purpose, capabilities, and usage info
        """
        try:
            areas = await self.list_ipu_areas()
            return enrich_area_list(areas)
        except Exception as e:
            logger.error(f"list_ipu_areas_with_metadata failed: {e}")
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
        cortical_id: str | None = None,
        group_id: int = 0,
        data_type_configs_by_subunit: dict[str, int] | None = None,
        per_device_dimensions: list[int] | None = None,
        brain_region_id: str | None = None,
        skip_placement_validation: bool = False,
    ) -> dict[str, Any]:
        """Create a new cortical area.

        Args:
            name: Human-readable name (shown in BV; use role/circuit-based names, never
                prefix with ``Mcp``/``MCP`` — see feagi-mcp docs ``Cortical area naming policy``)
            cortical_type: "OPU", "IPU", "CUSTOM", or "MEMORY"
            dimensions: [width, height, depth] in voxels (for CUSTOM/MEMORY only)
            position: [x, y, z] 3D coordinates
            neurons_per_voxel: Number of neurons per voxel (default: 1)
            device_count: Number of devices for IPU/OPU (default: 1)
            properties: Optional additional properties
            brain_region_id: Required for CUSTOM/MEMORY (parent brain region / circuit UUID).
                May be omitted if ``properties`` includes ``brain_region_id``.
            skip_placement_validation: If True, skip MCP placement checks (origin exclusion
                and spacing vs existing areas). Use only when necessary.
            cortical_id: For OPU/IPU: type key like "opse", "isvi" (required for OPU/IPU)
            group_id: For OPU/IPU: group identifier 0-255 (default: 0)
            data_type_configs_by_subunit: For OPU/IPU: map of subunit index to config
                e.g. {"0": 256, "1": 256, "2": 256} for 3-subunit servo with absolute+linear
            per_device_dimensions: For OPU/IPU: override per-device dimensions [x,y,z]
                e.g. [1, 1, 32] for single-joint servo with 32-angle resolution
                Total X = per_device_dimensions[0] * device_count

        Returns:
            Created area info with cortical_id(s)
        """
        try:
            if cortical_type in ["OPU", "IPU"]:
                if not cortical_id:
                    return {"error": "cortical_id required for OPU/IPU (e.g. 'opse', 'isvi')"}
                if data_type_configs_by_subunit is None:
                    return {"error": "data_type_configs_by_subunit required for OPU/IPU"}

                request_data = {
                    "cortical_id": cortical_id,
                    "cortical_type": cortical_type,
                    "group_id": group_id,
                    "device_count": device_count,
                    "coordinates_3d": position,
                    "neurons_per_voxel": neurons_per_voxel,
                    "data_type_configs_by_subunit": data_type_configs_by_subunit,
                }
                if per_device_dimensions is not None:
                    request_data["per_device_dimensions"] = per_device_dimensions

                response = await self._client.post(
                    f"{self.base_url}/v1/cortical_area/cortical_area",
                    json=request_data,
                )
            else:
                request_data = {
                    "cortical_name": name,
                    "cortical_type": cortical_type,
                    "cortical_dimensions": dimensions,
                    "coordinates_3d": position,
                }
                if properties:
                    request_data.update(properties)
                resolved_region = brain_region_id
                if not resolved_region:
                    br = request_data.get("brain_region_id")
                    if isinstance(br, str):
                        resolved_region = br.strip() or None
                if not resolved_region:
                    return {
                        "error": "brain_region_id is required for CUSTOM and MEMORY cortical areas",
                    }
                request_data["brain_region_id"] = resolved_region

                if not skip_placement_validation:
                    if origin_err := check_origin_exclusion(position):
                        return {"error": origin_err}
                    geom = await self.get_cortical_area_geometry()
                    if (
                        isinstance(geom, dict)
                        and "error" not in geom
                        and (sep_err := check_min_separation_to_existing(position, geom))
                    ):
                        return {"error": sep_err}

                response = await self._client.post(
                    f"{self.base_url}/v1/cortical_area/custom_cortical_area",
                    json=request_data,
                )

            if response.status_code == 200:
                return _as_json_dict(response.json())
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
                return _as_json_dict(response.json())
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"update_cortical_area failed: {e}")
            return {"error": str(e)}

    async def delete_cortical_area(self, cortical_id: str) -> dict[str, Any]:
        """Delete a cortical area."""
        try:
            response = await self._client.request(
                "DELETE",
                f"{self.base_url}/v1/cortical_area/cortical_area",
                json={"cortical_id": cortical_id},
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
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
                # Rules may be a JSON list or object depending on FEAGI version.
                return {
                    "src_area": src_area,
                    "dst_area": dst_area,
                    "rules": response.json(),
                }
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
                return _as_json_dict(response.json())
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"update_cortical_mapping failed: {e}")
            return {"error": str(e)}

    async def delete_cortical_mapping(self, src_area: str, dst_area: str) -> dict[str, Any]:
        """Delete connections between two cortical areas."""
        try:
            response = await self._client.delete(
                f"{self.base_url}/v1/cortical_mapping/mapping",
                params={"src_cortical_area": src_area, "dst_cortical_area": dst_area},
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {"error": f"HTTP {response.status_code}", "message": response.text}
        except Exception as e:
            logger.error(f"delete_cortical_mapping failed: {e}")
            return {"error": str(e)}

    async def get_area_semantic_info(self, area_id: str) -> dict[str, Any]:
        """Get semantic information about a cortical area.

        Args:
            area_id: Encoded cortical ID

        Returns:
            Dictionary with semantic metadata including type, purpose, capabilities, usage
        """
        try:
            info = get_semantic_info(area_id)

            genome = await self.download_genome()
            if "error" not in genome:
                blueprint = genome.get("blueprint", {})
                for key, value in blueprint.items():
                    if area_id in key and "__name-t" in key:
                        info["name"] = value
                        device_count_key = key.replace("__name-t", "devcnt-i")
                        info["device_count"] = blueprint.get(device_count_key, 0)
                        break

            return info
        except Exception as e:
            logger.error(f"get_area_semantic_info failed: {e}")
            return {"error": str(e)}

    @staticmethod
    def _stringify_query(query: dict[str, Any] | None) -> dict[str, str] | None:
        if not query:
            return None
        return {str(k): str(v) for k, v in query.items()}

    def _response_to_payload(self, response: httpx.Response) -> dict[str, Any] | list[Any] | Any:
        if not (200 <= response.status_code < 300):
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        if response.status_code == 204 or not response.content:
            return {"status": "success", "http_status": response.status_code}
        ct = response.headers.get("content-type", "")
        if "json" in ct:
            try:
                data = response.json()
                if isinstance(data, dict):
                    return cast(dict[str, Any], data)
                if isinstance(data, list):
                    return data
                return cast(dict[str, Any] | list[Any] | Any, data)
            except Exception:
                return {"raw": response.text}
        return {"text": response.text}

    async def brain_visualizer_operation(
        self,
        operation_id: str,
        *,
        path_params: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> dict[str, Any] | list[Any] | Any:
        """Run any Brain Visualizer whitelisted REST operation (see bv_operations.BV_OPERATIONS).

        This is the comprehensive escape hatch matching FEAGIHTTPAddressList routes.

        Voxel/neuron inspection: use ``get_cortical_area_voxel_neurons`` with query
        ``cortical_id``, ``x``, ``y``, ``z``, optional ``synapse_page`` (GET
        ``/v1/cortical_area/voxel_neurons``).

        Args:
            operation_id: e.g. get_system_health_check, get_cortical_area_voxel_neurons,
                put_cortical_area, post_mapping_afferents
            path_params: For paths containing {region_id}, {agent_id}, etc.
            query: URL query parameters
            json_body: JSON body for POST/PUT/PATCH, or for multipart upload op:
                post_genome_amalgamation_by_upload_multipart: {\"genome_json\": \"...\"} (string)
        """
        spec = BV_OPERATION_BY_ID.get(operation_id)
        if spec is None:
            return {
                "error": "unknown_operation_id",
                "operation_id": operation_id,
                "hint": "Use list_brain_visualizer_operations to list valid operation_id values",
            }

        try:
            path = resolve_path(spec.path_template, path_params)
        except ValueError as e:
            return {"error": "invalid_path", "message": str(e)}

        url = f"{self.base_url}{path}"
        q = self._stringify_query(query)

        try:
            if operation_id == "post_genome_amalgamation_by_upload_multipart":
                if not isinstance(json_body, dict) or "genome_json" not in json_body:
                    return {
                        "error": "invalid_body",
                        "message": 'json_body must be {"genome_json": "<utf-8 json string>"}',
                    }
                payload = str(json_body["genome_json"])
                files = {
                    "file": (
                        "genome.json",
                        payload.encode("utf-8"),
                        "application/json",
                    ),
                }
                response = await self._client.post(url, files=files)
                return self._response_to_payload(response)

            kwargs: dict[str, Any] = {}
            if q is not None:
                kwargs["params"] = q

            if spec.method == "GET":
                response = await self._client.get(url, **kwargs)
            elif spec.method == "POST":
                response = await self._client.post(url, json=json_body, **kwargs)
            elif spec.method == "PUT":
                response = await self._client.put(url, json=json_body, **kwargs)
            elif spec.method == "DELETE":
                response = await self._client.request("DELETE", url, json=json_body, **kwargs)
            else:
                return {"error": "unsupported_method", "method": spec.method}

            return self._response_to_payload(response)
        except Exception as e:
            logger.error("brain_visualizer_operation failed: %s", e)
            return {"error": "request_failed", "message": str(e)}
