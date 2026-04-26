"""HTTP client for FEAGI REST API."""

import asyncio
import logging
import math
from typing import Any, cast

import httpx

from feagi_mcp.area_metadata import enrich_area_list, enrich_area_with_name, get_semantic_info
from feagi_mcp.bv_operations import BV_OPERATION_BY_ID, resolve_path
from feagi_mcp.introspection_discovery import (
    IntrospectionEndpoint,
    discover_endpoint,
)
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
        """Check FEAGI reachability and full system health (incl. amalgamation_pending).

        Uses GET /v1/system/health_check so callers can see pending amalgamation state
        (``amalgamation_pending``) and ``brain_regions_root`` for placement. Falls back to
        GET /v1/genome/name if the system endpoint is unavailable.
        """
        try:
            response = await self._client.get(f"{self.base_url}/v1/system/health_check")
            if response.status_code == 200:
                data = _as_json_dict(response.json())
                data.setdefault("status", "ok")
                return data
            logger.warning(
                "health_check: GET /v1/system/health_check returned HTTP %s; falling back",
                response.status_code,
            )
        except Exception as e:
            logger.warning("health_check: system health_check failed (%s); falling back", e)

        try:
            response = await self._client.get(f"{self.base_url}/v1/genome/name")
            if response.status_code == 200:
                return {"status": "ok", "genome_name": response.json()}
            return {
                "status": "error",
                "message": response.text,
                "http_status": response.status_code,
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "error", "message": str(e)}

    async def monitor_activity(
        self,
        area_id: str,
        duration_ms: int = 1000,
        include_lifetime_stats: bool = True,
        lifetime_neuron_cap: int = 64,
    ) -> dict[str, Any]:
        """Monitor cortical area activity with optional lifetime fire-count enrichment.

        The base REST endpoint reports only the spikes observed within the sample
        window, which can incorrectly suggest a neuron is dead when it is merely
        quiet at sample time. When ``include_lifetime_stats`` is True (default),
        the result is enriched with ``lifetime_stats`` carrying per-neuron
        ``consecutive_fire_count`` aggregates across the area. This answers the
        "is this circuit silent right now, or never wired?" question in one call.

        Args:
            area_id: Cortical area identifier.
            duration_ms: Sample window in milliseconds.
            include_lifetime_stats: When True, attach ``lifetime_stats`` block.
            lifetime_neuron_cap: Maximum neurons to inspect for lifetime stats
                (caps fan-out for large areas; first ``N`` neurons are sampled).

        Returns:
            Activity data including ``firing_statistics`` (sample window) and,
            when enabled, ``lifetime_stats`` (lifetime fire counters).
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/monitoring/cortical_activity",
                params={"area": area_id, "duration": duration_ms / 1000.0},
            )
            if response.status_code != 200:
                return {
                    "error": f"HTTP {response.status_code}",
                    "message": response.text,
                }
            result = _as_json_dict(response.json())
        except Exception as e:
            logger.error(f"monitor_activity failed: {e}")
            return {"error": "request_failed", "message": str(e)}

        if include_lifetime_stats:
            result["lifetime_stats"] = await self._compute_area_lifetime_stats(
                area_id, lifetime_neuron_cap
            )
        return result

    async def _compute_area_lifetime_stats(
        self,
        area_id: str,
        neuron_cap: int,
    ) -> dict[str, Any]:
        """Aggregate lifetime fire counters across (a sample of) area neurons.

        Walks ``/v1/connectome/cortical_area/{id}/neurons`` for the neuron-id
        list, then fans out ``/v1/connectome/neuron/{id}/properties`` in
        parallel (capped at ``neuron_cap``) to gather ``consecutive_fire_count``.

        Returns a dict with:
            * ``total_neurons_in_area`` - reported area size.
            * ``neurons_inspected`` - count actually sampled (<= ``neuron_cap``).
            * ``lifetime_active_count`` - neurons with ``consecutive_fire_count > 0``.
            * ``max_consecutive_fire_count`` - max across sampled neurons.
            * ``top_neurons`` - up to 5 highest fire-count neurons with id/coords.
            * ``error`` - present only on failure; never raises.
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/connectome/cortical_area/{area_id}/neurons"
            )
            if response.status_code != 200:
                return {
                    "error": f"HTTP {response.status_code}",
                    "message": response.text,
                }
            neuron_ids_raw = response.json()
            if not isinstance(neuron_ids_raw, list):
                return {"error": "unexpected_payload", "message": "neuron list not a JSON array"}
            total_in_area = len(neuron_ids_raw)
            sampled_ids = [str(nid) for nid in neuron_ids_raw[: max(0, int(neuron_cap))]]
            if not sampled_ids:
                return {
                    "total_neurons_in_area": total_in_area,
                    "neurons_inspected": 0,
                    "lifetime_active_count": 0,
                    "max_consecutive_fire_count": 0,
                    "top_neurons": [],
                }

            async def _fetch(nid: str) -> dict[str, Any] | None:
                try:
                    r = await self._client.get(
                        f"{self.base_url}/v1/connectome/neuron/{nid}/properties"
                    )
                    if r.status_code != 200:
                        return None
                    return _as_json_dict(r.json())
                except Exception as exc:
                    logger.debug("lifetime stats: neuron %s fetch failed: %s", nid, exc)
                    return None

            properties = await asyncio.gather(*[_fetch(nid) for nid in sampled_ids])
            inspected = [p for p in properties if p is not None]
            counts = [int(p.get("consecutive_fire_count", 0) or 0) for p in inspected]
            active_count = sum(1 for c in counts if c > 0)
            max_count = max(counts) if counts else 0
            ranked = sorted(
                [
                    {
                        "neuron_id": p.get("neuron_id"),
                        "x": p.get("x"),
                        "y": p.get("y"),
                        "z": p.get("z"),
                        "consecutive_fire_count": int(p.get("consecutive_fire_count", 0) or 0),
                        "membrane_potential": p.get("membrane_potential"),
                    }
                    for p in inspected
                ],
                key=lambda d: d["consecutive_fire_count"],
                reverse=True,
            )
            top_neurons = [d for d in ranked if d["consecutive_fire_count"] > 0][:5]
            return {
                "total_neurons_in_area": total_in_area,
                "neurons_inspected": len(inspected),
                "lifetime_active_count": active_count,
                "max_consecutive_fire_count": max_count,
                "top_neurons": top_neurons,
            }
        except Exception as e:
            logger.warning("_compute_area_lifetime_stats failed for %s: %s", area_id, e)
            return {"error": "lifetime_stats_failed", "message": str(e)}

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

    # ------------------------------------------------------------------
    # Runtime taps & log surface (server-side endpoints added to feagi-core
    # to address MCP debugging gaps #4 motor-output tap, #5 sensor read,
    # #8 log tail).
    # ------------------------------------------------------------------

    async def get_motor_snapshot_last(
        self, agent_id: str | None = None
    ) -> dict[str, Any]:
        """GET /v1/output/motor_snapshot/last - latest motor output captured by the burst loop.

        Args:
            agent_id: Optional agent filter applied to the per-agent publish stats.

        Returns:
            Dict with ``burst_num``, ``timestamp_ms``, ``has_data``, ``total_areas``,
            ``total_neurons``, ``areas`` (per-cortical-area firing samples), and
            ``agents`` (per-agent publish stats including ``published`` and ``last_error``).
        """
        try:
            params: dict[str, str] = {}
            if isinstance(agent_id, str) and agent_id.strip():
                params["agent_id"] = agent_id.strip()
            response = await self._client.get(
                f"{self.base_url}/v1/output/motor_snapshot/last",
                params=params or None,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_motor_snapshot_last failed: %s", e)
            return {"error": str(e)}

    async def get_sensor_snapshot_last(
        self, cortical_id: str | None = None
    ) -> dict[str, Any]:
        """GET /v1/input/sensor_snapshot/last - latest sensory input decoded this burst.

        Args:
            cortical_id: Optional base64 cortical id filter.

        Returns:
            Dict with ``burst_num``, ``timestamp_ms``, ``has_data``, ``total_areas``,
            ``total_neurons``, and ``areas`` (per-cortical-area decoded XYZP samples).
        """
        try:
            params: dict[str, str] = {}
            if isinstance(cortical_id, str) and cortical_id.strip():
                params["cortical_id"] = cortical_id.strip()
            response = await self._client.get(
                f"{self.base_url}/v1/input/sensor_snapshot/last",
                params=params or None,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_sensor_snapshot_last failed: %s", e)
            return {"error": str(e)}

    async def get_log_tail(
        self,
        level: str | None = None,
        target_prefix: str | None = None,
        since_ts_ms: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """GET /v1/system/log_tail - recent log records from the in-process tracing ring buffer.

        Args:
            level: Minimum severity (TRACE/DEBUG/INFO/WARN/ERROR).
            target_prefix: Restrict to tracing targets starting with this prefix.
            since_ts_ms: Only return records emitted at or after this Unix timestamp (ms).
            limit: Maximum records to return.

        Returns:
            Dict with ``enabled`` (False if FEAGI_LOG_RING_BUFFER_CAPACITY=0),
            ``capacity``, ``returned``, and ``records`` (oldest-first list of
            ``timestamp_ms``/``level``/``target``/``file``/``line``/``message``/``fields``).
        """
        try:
            params: dict[str, str] = {}
            if isinstance(level, str) and level.strip():
                params["level"] = level.strip()
            if isinstance(target_prefix, str) and target_prefix.strip():
                params["target_prefix"] = target_prefix.strip()
            if isinstance(since_ts_ms, int):
                params["since_ts_ms"] = str(int(since_ts_ms))
            if isinstance(limit, int) and limit > 0:
                params["limit"] = str(int(limit))
            response = await self._client.get(
                f"{self.base_url}/v1/system/log_tail",
                params=params or None,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_log_tail failed: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Burst engine control & state inspection (deficiency #9 -
    # deterministic step-debug). These thin wrappers expose burst control
    # to the LLM without forcing it through the BV escape hatch.
    # ------------------------------------------------------------------

    async def get_burst_counter(self) -> dict[str, Any]:
        """GET /v1/burst_engine/burst_counter - current burst index."""
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/burst_engine/burst_counter"
            )
            if response.status_code == 200:
                return {"burst_counter": int(response.json())}
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_burst_counter failed: %s", e)
            return {"error": str(e)}

    async def get_burst_engine_config(self) -> dict[str, Any]:
        """GET /v1/burst_engine/config - frequency, run/pause flags, interval."""
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/burst_engine/config"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_burst_engine_config failed: %s", e)
            return {"error": str(e)}

    async def set_burst_engine_frequency(self, frequency_hz: float) -> dict[str, Any]:
        """PUT /v1/burst_engine/config - set burst frequency in Hz.

        Slowing the engine (e.g. 1-5 Hz) makes circuit debugging deterministic by
        giving the LLM time to inspect state between bursts.
        """
        try:
            if not isinstance(frequency_hz, (int, float)) or frequency_hz <= 0:
                return {"error": "frequency_hz must be positive"}
            response = await self._client.put(
                f"{self.base_url}/v1/burst_engine/config",
                json={"burst_frequency_hz": float(frequency_hz)},
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("set_burst_engine_frequency failed: %s", e)
            return {"error": str(e)}

    async def control_burst_engine(self, action: str) -> dict[str, Any]:
        """POST /v1/burst_engine/control - start/pause/stop the burst engine.

        Args:
            action: One of ``start``, ``resume``, ``pause``, or ``stop``.
        """
        normalized = action.strip().lower() if isinstance(action, str) else ""
        valid_actions = {"start", "resume", "pause", "stop"}
        if normalized not in valid_actions:
            return {
                "error": "invalid_action",
                "message": f"action must be one of {sorted(valid_actions)}",
            }
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/burst_engine/control",
                json={"action": normalized},
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("control_burst_engine failed: %s", e)
            return {"error": str(e)}

    async def pause_burst_engine(self) -> dict[str, Any]:
        """POST /v1/burst_engine/hold - explicit hold endpoint (LLM-friendly alias)."""
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/burst_engine/hold"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("pause_burst_engine failed: %s", e)
            return {"error": str(e)}

    async def resume_burst_engine(self) -> dict[str, Any]:
        """POST /v1/burst_engine/resume - resume after a hold."""
        try:
            response = await self._client.post(
                f"{self.base_url}/v1/burst_engine/resume"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("resume_burst_engine failed: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Neuron / synapse runtime inspection (deficiencies #1 inspect_neuron_state,
    # #2 list placed synapses, plus bonus voxel/neuron-id tools).
    # ------------------------------------------------------------------

    async def inspect_neuron_state_at(
        self,
        cortical_id: str,
        x: int,
        y: int,
        z: int,
    ) -> dict[str, Any]:
        """GET /v1/connectome/neuron_properties_at - neuron runtime properties at a voxel.

        Returns neuron-level state (membrane potential, threshold, refractory,
        last_input, etc.) for the neuron at the given coordinate.
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/connectome/neuron_properties_at",
                params={
                    "cortical_id": str(cortical_id),
                    "x": str(int(x)),
                    "y": str(int(y)),
                    "z": str(int(z)),
                },
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("inspect_neuron_state_at failed: %s", e)
            return {"error": str(e)}

    async def get_neuron_state_by_id(self, neuron_id: str) -> dict[str, Any]:
        """GET /v1/connectome/neuron/{neuron_id}/properties - neuron state by stable id."""
        nid = str(neuron_id).strip()
        if not nid:
            return {"error": "neuron_id must be non-empty"}
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/connectome/neuron/{nid}/properties"
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_neuron_state_by_id failed: %s", e)
            return {"error": str(e)}

    async def get_voxel_neurons(
        self,
        cortical_id: str,
        x: int,
        y: int,
        z: int,
        synapse_page: int | None = None,
    ) -> dict[str, Any]:
        """GET /v1/cortical_area/voxel_neurons - all neurons + synapses at a voxel.

        Same payload Brain Visualizer uses for its voxel inspector. ``synapse_page``
        (0-based) requests a paginated incoming/outgoing synapse list.
        """
        try:
            params: dict[str, str] = {
                "cortical_id": str(cortical_id),
                "x": str(int(x)),
                "y": str(int(y)),
                "z": str(int(z)),
            }
            if isinstance(synapse_page, int) and synapse_page >= 0:
                params["synapse_page"] = str(int(synapse_page))
            response = await self._client.get(
                f"{self.base_url}/v1/cortical_area/voxel_neurons",
                params=params,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("get_voxel_neurons failed: %s", e)
            return {"error": str(e)}

    async def list_area_synapses(self, cortical_area_id: str) -> dict[str, Any]:
        """GET /v1/connectome/{cortical_area_id}/synapses - placed synapses for one area.

        Returns the actual realized per-synapse list (source/target neuron ids,
        weights, postsynaptic potentials, type) - not just morphology rules.
        """
        area = str(cortical_area_id).strip()
        if not area:
            return {"error": "cortical_area_id must be non-empty"}
        try:
            response = await self._client.get(
                f"{self.base_url}/v1/connectome/{area}/synapses"
            )
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, list):
                    return {
                        "cortical_area_id": area,
                        "synapse_count": len(payload),
                        "synapses": payload,
                    }
                return _as_json_dict(payload)
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("list_area_synapses failed: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Agent / monitoring helpers (#3 capabilities diagnostic, #7 batched
    # monitoring).
    # ------------------------------------------------------------------

    async def list_agent_capabilities_all(
        self, include_device_registrations: bool = True
    ) -> dict[str, Any]:
        """GET /v1/agent/capabilities/all - raw multi-agent capabilities payload.

        Diagnostic for cases where ``get_agent_device_registrations`` returns empty
        but devices are clearly active. Returns the full FEAGI response unmodified.
        """
        try:
            params = {
                "include_device_registrations": (
                    "true" if include_device_registrations else "false"
                )
            }
            response = await self._client.get(
                f"{self.base_url}/v1/agent/capabilities/all",
                params=params,
            )
            if response.status_code == 200:
                return _as_json_dict(response.json())
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("list_agent_capabilities_all failed: %s", e)
            return {"error": str(e)}

    async def monitor_activity_batch(
        self,
        area_ids: list[str],
        duration_ms: int = 1000,
        include_lifetime_stats: bool = True,
        lifetime_neuron_cap: int = 64,
    ) -> dict[str, Any]:
        """Fan out :meth:`monitor_activity` over multiple areas in parallel.

        Composes the existing ``GET /v1/monitoring/cortical_activity`` endpoint
        (no new server route) but issues all requests concurrently so a typical
        4-6 area inspection completes in roughly the duration of a single call.
        Lifetime-stats enrichment is forwarded per-area; disable for very large
        batches if the extra per-neuron fan-out is unwanted.

        Returns:
            Dict mapping ``area_id`` -> per-area activity payload (or error dict).
        """
        if not isinstance(area_ids, list) or not area_ids:
            return {"error": "area_ids must be a non-empty list"}
        clean_ids: list[str] = []
        for raw in area_ids:
            if not isinstance(raw, str) or not raw.strip():
                return {"error": "area_ids must contain non-empty strings"}
            clean_ids.append(raw.strip())
        try:
            results = await asyncio.gather(
                *(
                    self.monitor_activity(
                        aid,
                        duration_ms,
                        include_lifetime_stats=include_lifetime_stats,
                        lifetime_neuron_cap=lifetime_neuron_cap,
                    )
                    for aid in clean_ids
                ),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error("monitor_activity_batch fan-out failed: %s", e)
            return {"error": str(e)}

        per_area: dict[str, Any] = {}
        for aid, outcome in zip(clean_ids, results, strict=True):
            if isinstance(outcome, BaseException):
                per_area[aid] = {"error": "request_failed", "message": str(outcome)}
            else:
                per_area[aid] = outcome
        return {
            "duration_ms": duration_ms,
            "area_count": len(clean_ids),
            "results": per_area,
        }

    # ------------------------------------------------------------------
    # Slim/paginated views (Tier 1 MCP improvements)
    # ------------------------------------------------------------------

    async def list_morphologies_summary(
        self,
        name_substring: str | None = None,
        type_filter: str | None = None,
        class_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Slim morphology listing: returns ``{name, type, class, pattern_count}`` only.

        Wraps :meth:`list_morphologies` (which returns full pattern arrays for ~70+
        morphologies) and projects to a ~30-byte-per-row summary. This avoids the
        token wall when the full payload is too large for an MCP response.

        Args:
            name_substring: Optional case-insensitive substring filter on name.
            type_filter: Exact match on ``type`` field (e.g. ``"patterns"``).
            class_filter: Exact match on ``class`` field (e.g. ``"core"`` or ``"custom"``).
            limit: Max rows to return (default 50, hard cap 500).
            offset: Skip first N rows after filtering (for pagination).

        Returns:
            Dict with ``total_unfiltered``, ``total_filtered``, ``returned``, ``offset``,
            ``limit``, and ``items`` (list of slim row dicts).
        """
        try:
            limit = max(1, min(int(limit), 500))
            offset = max(0, int(offset))
            full = await self.list_morphologies()
            if not isinstance(full, dict) or "error" in full:
                return full if isinstance(full, dict) else {"error": "bad_payload"}
            total_unfiltered = len(full)
            name_needle = (name_substring or "").lower().strip()
            type_needle = (type_filter or "").strip()
            class_needle = (class_filter or "").strip()

            rows: list[dict[str, Any]] = []
            for morph_name, morph_data in full.items():
                if not isinstance(morph_data, dict):
                    continue
                if name_needle and name_needle not in str(morph_name).lower():
                    continue
                m_type = str(morph_data.get("type", ""))
                if type_needle and m_type != type_needle:
                    continue
                m_class = str(morph_data.get("class", ""))
                if class_needle and m_class != class_needle:
                    continue
                params = morph_data.get("parameters") or {}
                pattern_count = 0
                if isinstance(params, dict):
                    if isinstance(params.get("patterns"), list):
                        pattern_count = len(params["patterns"])
                    elif isinstance(params.get("vectors"), list):
                        pattern_count = len(params["vectors"])
                rows.append(
                    {
                        "name": str(morph_name),
                        "type": m_type,
                        "class": m_class,
                        "pattern_count": pattern_count,
                        "source": str(morph_data.get("source", "")),
                    }
                )
            rows.sort(key=lambda r: r["name"])
            total_filtered = len(rows)
            window = rows[offset : offset + limit]
            return {
                "total_unfiltered": total_unfiltered,
                "total_filtered": total_filtered,
                "returned": len(window),
                "offset": offset,
                "limit": limit,
                "items": window,
            }
        except Exception as e:
            logger.error("list_morphologies_summary failed: %s", e)
            return {"error": str(e)}

    async def get_connectivity_summary(
        self,
        src_filter: str | None = None,
        dst_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Slim connectivity table: ``[{src, dst, morphology, psc_mult, plasticity}]``.

        Reads the cortical_map_detailed payload (smaller than the full genome blueprint)
        and emits a tabular summary suitable for one-shot MCP responses. Filters apply
        to the underlying cortical IDs before pagination.

        Args:
            src_filter: Optional cortical ID substring filter (matched against src).
            dst_filter: Optional cortical ID substring filter (matched against dst).
            limit: Max rows to return (default 100, hard cap 2000).
            offset: Skip first N rows after filtering.

        Returns:
            Dict with ``total_filtered``, ``returned``, ``offset``, ``limit``, ``items``.
        """
        try:
            limit = max(1, min(int(limit), 2000))
            offset = max(0, int(offset))
            detailed = await self.get_cortical_map_detailed()
            if not isinstance(detailed, dict) or "error" in detailed:
                return detailed if isinstance(detailed, dict) else {"error": "bad_payload"}
            src_needle = (src_filter or "").strip()
            dst_needle = (dst_filter or "").strip()

            rows: list[dict[str, Any]] = []
            for src_id, dst_map in detailed.items():
                if src_needle and src_needle not in src_id:
                    continue
                if not isinstance(dst_map, dict):
                    continue
                for dst_id, mapping_rules in dst_map.items():
                    if dst_needle and dst_needle not in dst_id:
                        continue
                    if not isinstance(mapping_rules, list):
                        continue
                    for rule in mapping_rules:
                        if not isinstance(rule, dict):
                            continue
                        rows.append(
                            {
                                "src": src_id,
                                "dst": dst_id,
                                "morphology": rule.get("morphology_id", ""),
                                "psc_mult": rule.get("postSynapticCurrent_multiplier"),
                                "plasticity": bool(rule.get("plasticity_flag", False)),
                                "plasticity_constant": rule.get("plasticity_constant"),
                            }
                        )
            rows.sort(key=lambda r: (r["src"], r["dst"], str(r["morphology"])))
            total_filtered = len(rows)
            window = rows[offset : offset + limit]
            return {
                "total_filtered": total_filtered,
                "returned": len(window),
                "offset": offset,
                "limit": limit,
                "items": window,
            }
        except Exception as e:
            logger.error("get_connectivity_summary failed: %s", e)
            return {"error": str(e)}

    # Plasticity-relevant fields surfaced by inspect_cortical_areas_minimal.
    # Kept short and stable so MCP consumers can rely on a known shape.
    _MINIMAL_AREA_FIELDS: tuple[str, ...] = (
        "cortical_name",
        "area_type",
        "cortical_dimensions",
        "neuron_count",
        "neuron_fire_threshold",
        "neuron_post_synaptic_potential",
        "neuron_post_synaptic_potential_max",
        "neuron_excitability",
        "neuron_leak_coefficient",
        "neuron_refractory_period",
        "neuron_snooze_period",
        "neuron_consecutive_fire_count",
        "neuron_plasticity_constant",
        "neuron_psp_uniform_distribution",
        "neuron_mp_charge_accumulation",
        "neuron_burst_engine_active",
        "incoming_synapse_count",
        "outgoing_synapse_count",
    )

    async def inspect_cortical_areas_minimal(
        self,
        cortical_ids: list[str],
    ) -> dict[str, Any]:
        """Project full inspection payload to ~18 plasticity-relevant fields per area.

        Wraps :meth:`fetch_multi_cortical_area_properties` and discards verbose fields
        (visualization geometry, encoding option lists, properties dict, etc.) so a
        five-area sweep fits comfortably in a single MCP response.

        Returns:
            Dict mapping ``cortical_id`` -> projected field dict.
        """
        try:
            if not isinstance(cortical_ids, list) or not cortical_ids:
                return {"error": "cortical_ids must be a non-empty list"}
            clean_ids: list[str] = []
            for raw in cortical_ids:
                if not isinstance(raw, str) or not raw.strip():
                    return {"error": "cortical_ids must contain non-empty strings"}
                clean_ids.append(raw.strip())
            full = await self.fetch_multi_cortical_area_properties(clean_ids)
            if not isinstance(full, dict) or "error" in full:
                return full if isinstance(full, dict) else {"error": "bad_payload"}
            slim: dict[str, Any] = {}
            for cid, area in full.items():
                if not isinstance(area, dict):
                    slim[cid] = {"error": "bad_area_record"}
                    continue
                projected: dict[str, Any] = {}
                for field in self._MINIMAL_AREA_FIELDS:
                    if field in area:
                        projected[field] = area[field]
                slim[cid] = projected
            return slim
        except Exception as e:
            logger.error("inspect_cortical_areas_minimal failed: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Circuit-design primitives
    # ------------------------------------------------------------------

    async def build_reflex_mapping(
        self,
        src_area_id: str,
        dst_area_id: str,
        morphology_name: str,
        voxel_mappings: list[dict[str, Any]],
        postsynaptic_current_multiplier: int,
        plasticity_flag: bool = False,
        plasticity_constant: int = 0,
        ltp_multiplier: int = 1,
        ltd_multiplier: int = 1,
        plasticity_window: int = 10,
        synaptic_delay_bursts: int = 0,
        morphology_scalar: list[int] | None = None,
        replace_existing: bool = False,
        plasticity_mode: str | None = None,
        eligibility_decay_bursts: int | None = None,
        reward_source_area: str | None = None,
        punishment_source_area: str | None = None,
        max_weight: float | None = None,
        plasticity_eta: float | None = None,
    ) -> dict[str, Any]:
        """Create a custom ``patterns`` morphology and wire src->dst with it in one call.

        Compiles ``voxel_mappings`` (each ``{"src": [x,y,z], "dst": [x,y,z]}``) to the
        FEAGI patterns morphology JSON, registers it via :meth:`create_morphology`, then
        attaches it to a new mapping entry between ``src_area_id`` and ``dst_area_id``
        via :meth:`update_cortical_mapping`. By default the new entry is appended to
        any existing mapping rules; pass ``replace_existing=True`` to overwrite.

        Args:
            src_area_id: Base64 source cortical ID.
            dst_area_id: Base64 destination cortical ID.
            morphology_name: Unique name for the new morphology (e.g. ``"hinge_to_cart"``).
            voxel_mappings: List of ``{"src":[x,y,z], "dst":[x,y,z]}`` dicts. Wildcards
                are supported by passing the string ``"*"``, ``"?"``, or ``"!"`` in place
                of an integer (FEAGI pattern semantics).
            postsynaptic_current_multiplier: Synaptic gain. Positive = excite, negative = inhibit.
            plasticity_flag: Enable STDP on this mapping rule.
            plasticity_constant: STDP base learning rate (integer; FEAGI scales internally).
            ltp_multiplier / ltd_multiplier: Each must fit server ``i8`` range ``-128..127``;
                use ``plasticity_eta`` for sub-unit step sizes on the weight commit.
            ltp_multiplier / ltd_multiplier / plasticity_window / synaptic_delay_bursts:
                Pass-through STDP parameters; defaults are sensible for an excitatory
                Hebbian rule with no axonal delay.
            morphology_scalar: Optional ``[x,y,z]`` scalar override; usually ``None``.
            replace_existing: If True, overwrite all current mapping rules with this one.
            max_weight: Optional cap on positive weight commits; server validates.
            plasticity_eta: Optional scale on ``w += eta * R * e`` (server default 1.0).

        Returns:
            Dict with ``morphology_create``, ``mapping_update``, and ``rule`` (the
            assembled mapping rule that was sent), or ``error`` on failure.
        """
        try:
            if not isinstance(voxel_mappings, list) or not voxel_mappings:
                return {"error": "voxel_mappings must be a non-empty list"}
            patterns: list[Any] = []
            for idx, vm in enumerate(voxel_mappings):
                if not isinstance(vm, dict):
                    return {"error": f"voxel_mappings[{idx}] must be a dict"}
                src_xyz = vm.get("src")
                dst_xyz = vm.get("dst")
                if (
                    not isinstance(src_xyz, list)
                    or not isinstance(dst_xyz, list)
                    or len(src_xyz) != 3
                    or len(dst_xyz) != 3
                ):
                    return {
                        "error": (
                            f"voxel_mappings[{idx}] must have 'src' and 'dst' lists of length 3"
                        )
                    }
                patterns.append([list(src_xyz), list(dst_xyz)])
            morph_create = await self.create_morphology(
                morphology_name=morphology_name,
                morphology_type="patterns",
                morphology_parameters={"patterns": patterns},
            )
            if isinstance(morph_create, dict) and "error" in morph_create:
                return {
                    "error": "create_morphology_failed",
                    "morphology_create": morph_create,
                }

            for name, m in (
                ("ltp_multiplier", ltp_multiplier),
                ("ltd_multiplier", ltd_multiplier),
            ):
                mi = int(m)
                if mi < -128 or mi > 127:
                    return {
                        "error": (
                            f"{name} must fit in i8 range -128..127 (got {m!r}); "
                            "use plasticity_eta for sub-unit learning rates"
                        )
                    }

            scalar = morphology_scalar if morphology_scalar is not None else [1, 1, 1]
            new_rule: dict[str, Any] = {
                "morphology_id": morphology_name,
                "morphology_scalar": scalar,
                "postSynapticCurrent_multiplier": int(postsynaptic_current_multiplier),
                "plasticity_flag": bool(plasticity_flag),
                "plasticity_constant": int(plasticity_constant),
                "ltp_multiplier": int(ltp_multiplier),
                "ltd_multiplier": int(ltd_multiplier),
                "plasticity_window": int(plasticity_window),
                "synaptic_delay_bursts": int(synaptic_delay_bursts),
            }

            # R-STDP optional fields. Server validates the combination; we forward as-is.
            if plasticity_mode is not None:
                mode_normalized = str(plasticity_mode).strip().lower()
                if mode_normalized not in {"off", "stdp", "rstdp", "r-stdp"}:
                    return {
                        "error": (
                            f"plasticity_mode must be one of 'off', 'stdp', 'rstdp'; "
                            f"got '{plasticity_mode}'"
                        )
                    }
                new_rule["plasticity_mode"] = mode_normalized
            if eligibility_decay_bursts is not None:
                if int(eligibility_decay_bursts) < 0:
                    return {"error": "eligibility_decay_bursts must be >= 0"}
                new_rule["eligibility_decay_bursts"] = int(eligibility_decay_bursts)
            if reward_source_area is not None:
                new_rule["reward_source_area"] = str(reward_source_area)
            if punishment_source_area is not None:
                new_rule["punishment_source_area"] = str(punishment_source_area)
            if max_weight is not None:
                try:
                    mw = float(max_weight)
                except (TypeError, ValueError):
                    return {"error": "max_weight must be a number or None"}
                if mw != mw or mw <= 0.0:
                    return {
                        "error": (
                            "max_weight must be strictly positive and not NaN; "
                            f"got {max_weight!r}"
                        )
                    }
                new_rule["max_weight"] = mw
            if plasticity_eta is not None:
                try:
                    pe = float(plasticity_eta)
                except (TypeError, ValueError):
                    return {"error": "plasticity_eta must be a number or None"}
                if pe != pe or pe <= 0.0 or not math.isfinite(pe):
                    return {
                        "error": (
                            "plasticity_eta must be finite and strictly positive; "
                            f"got {plasticity_eta!r}"
                        )
                    }
                new_rule["plasticity_eta"] = pe

            if replace_existing:
                rules: list[dict[str, Any]] = [new_rule]
            else:
                existing = await self.get_cortical_mapping(src_area_id, dst_area_id)
                rules = []
                if isinstance(existing, dict):
                    raw_rules = existing.get("rules")
                    if isinstance(raw_rules, list):
                        for r in raw_rules:
                            if isinstance(r, dict):
                                rules.append(r)
                rules.append(new_rule)

            mapping_update = await self.update_cortical_mapping(
                src_area=src_area_id,
                dst_area=dst_area_id,
                mapping_rules=rules,
            )
            return {
                "morphology_create": morph_create,
                "mapping_update": mapping_update,
                "rule": new_rule,
                "patterns_count": len(patterns),
            }
        except Exception as e:
            logger.error("build_reflex_mapping failed: %s", e)
            return {"error": str(e)}

    async def auto_polarity_probe(
        self,
        opu_id: str,
        sensor_id: str,
        columns: list[int] | None = None,
        intensity_z: int = 5,
        repeats: int = 3,
        settle_ms: int = 400,
    ) -> dict[str, Any]:
        """Force-fire each column of an OPU and report the sensor delta it produces.

        For each ``x`` in ``columns``: stimulate ``(x, 0, intensity_z)`` for ``repeats``
        bursts, wait ``settle_ms``, then compare the latest sensor snapshot for
        ``sensor_id`` against the pre-stimulation baseline. Useful for discovering
        which OPU column drives an actuator in which physical direction without
        having to hand-decode encoder voxels.

        IMPORTANT: This requires the embodiment agent to be subscribed to motor
        output for ``opu_id``. If no agent is subscribed, the cart will not move
        and the deltas will be zero.

        Args:
            opu_id: Base64 OPU cortical ID to probe (e.g. cart motor).
            sensor_id: Base64 IPU cortical ID to observe (e.g. cart-velocity sensor).
            columns: List of x-coordinates to probe. Defaults to ``[0, 1]``.
            intensity_z: Z coordinate to use during stimulation.
            repeats: Number of force-fire stimuli per column.
            settle_ms: Time to wait between stimulation and post-stim snapshot.

        Returns:
            Dict with ``baseline``, per-column probe results (``stim_xyz``,
            ``post_samples``, ``observed_z_shift``), and ``inferred_direction_map``
            mapping each probed column to a coarse ``"positive_z"`` / ``"negative_z"``
            / ``"no_change"`` label based on weighted z-centroid shift.
        """
        import asyncio

        try:
            cols = list(columns) if columns else [0, 1]
            cols = [int(c) for c in cols]

            async def _sensor_centroid_z() -> float | None:
                snap = await self.get_sensor_snapshot_last(sensor_id)
                if not isinstance(snap, dict) or "error" in snap:
                    return None
                areas = snap.get("areas")
                if not isinstance(areas, list) or not areas:
                    return None
                samples = areas[0].get("samples") if isinstance(areas[0], dict) else None
                if not isinstance(samples, list) or not samples:
                    return None
                total_w = 0.0
                weighted = 0.0
                for s in samples:
                    if not isinstance(s, dict):
                        continue
                    z_val = float(s.get("z", 0))
                    p = float(s.get("potential", 0.0))
                    if p <= 0:
                        continue
                    weighted += z_val * p
                    total_w += p
                return weighted / total_w if total_w > 0 else None

            baseline_z = await _sensor_centroid_z()

            results: list[dict[str, Any]] = []
            for col in cols:
                stim_payload = {opu_id: [[col, 0, int(intensity_z)]] * max(1, int(repeats))}
                stim = await self.stimulate_areas(stim_payload, mode="force_fire")
                await asyncio.sleep(max(0, int(settle_ms)) / 1000.0)
                post_z = await _sensor_centroid_z()
                shift = (
                    None
                    if baseline_z is None or post_z is None
                    else (post_z - baseline_z)
                )
                results.append(
                    {
                        "stim_xyz": [col, 0, int(intensity_z)],
                        "stimulation_result": stim,
                        "baseline_z_centroid": baseline_z,
                        "post_z_centroid": post_z,
                        "observed_z_shift": shift,
                    }
                )

            inferred: dict[str, str] = {}
            shift_threshold = 0.25
            for r in results:
                key = f"col_{r['stim_xyz'][0]}"
                shift = r.get("observed_z_shift")
                if shift is None:
                    inferred[key] = "indeterminate"
                elif shift > shift_threshold:
                    inferred[key] = "positive_z"
                elif shift < -shift_threshold:
                    inferred[key] = "negative_z"
                else:
                    inferred[key] = "no_change"

            return {
                "opu_id": opu_id,
                "sensor_id": sensor_id,
                "columns": cols,
                "intensity_z": int(intensity_z),
                "repeats": int(repeats),
                "settle_ms": int(settle_ms),
                "baseline_z_centroid": baseline_z,
                "results": results,
                "inferred_direction_map": inferred,
            }
        except Exception as e:
            logger.error("auto_polarity_probe failed: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Embodiment introspection (proxies to controller-side endpoints)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_introspection_url(
        introspection_url: str | None,
        controller_id: str,
    ) -> tuple[str | None, IntrospectionEndpoint | None]:
        """Return (url, descriptor) for an explicit URL or auto-discovery.

        Explicit URLs always win; discovery is only attempted when the caller
        omits the URL. Returning the descriptor (when present) lets callers
        surface metadata such as PID and controller version for diagnostics.
        """
        if introspection_url and introspection_url.strip():
            return introspection_url.strip(), None
        descriptor = discover_endpoint(controller_id)
        if descriptor is None:
            return None, None
        return descriptor.url, descriptor

    async def embodiment_discover_introspection_endpoint(
        self,
        controller_id: str = "mujoco",
    ) -> dict[str, Any]:
        """Locate the introspection HTTP endpoint for a launched controller.

        Reads the descriptor written by feagi-desktop's launcher when it
        spawns a controller with introspection enabled. Returns a structured
        payload so MCP clients can surface diagnostics (PID, version, when
        the controller started) in addition to the URL.

        Args:
            controller_id: Controller bundle id (must match the id used by
                the launcher); defaults to ``"mujoco"``.

        Returns:
            ``{"found": bool, "controller_id": str, ...}`` — when ``found``
            is ``True`` the payload includes ``url``, ``host``, ``port``,
            ``pid``, ``controller_version``, ``started_at``,
            ``descriptor_path``, and ``schema_version``.
        """
        try:
            descriptor = discover_endpoint(controller_id)
        except ValueError as exc:
            return {
                "found": False,
                "controller_id": controller_id,
                "error": str(exc),
            }
        if descriptor is None:
            return {
                "found": False,
                "controller_id": controller_id,
                "message": (
                    "No introspection descriptor found. Ensure the "
                    "controller was launched via feagi-desktop with "
                    "introspection enabled."
                ),
            }
        return {"found": True, **descriptor.as_dict()}

    async def embodiment_get_physics_state(
        self,
        introspection_url: str | None = None,
        timeout_s: float = 2.0,
        controller_id: str = "mujoco",
    ) -> dict[str, Any]:
        """GET <introspection_url>/v1/state - raw embodiment physics state.

        Proxies to a small HTTP endpoint exposed by the embodiment controller
        (currently implemented for the MuJoCo controller). Provides ground truth
        joint positions, velocities, applied forces, and sensor scalars without
        going through the FEAGI encoder pipeline.

        Args:
            introspection_url: Base URL of the controller's introspection
                server, e.g. ``"http://127.0.0.1:9173"``. When omitted, the
                URL is auto-discovered via the launcher-written descriptor
                under ``<runtime_root>/controllers/.introspection/<id>.json``.
            timeout_s: HTTP timeout.
            controller_id: Controller bundle id used during auto-discovery.

        Returns:
            Whatever the controller exposes; typically
            ``{"time": float, "joints": {...}, "actuators": {...}, "sensors": {...}}``.
        """
        url, descriptor = self._resolve_introspection_url(
            introspection_url, controller_id
        )
        if url is None:
            return {
                "error": "introspection_url_unavailable",
                "message": (
                    f"No introspection URL provided and no descriptor found "
                    f"for controller_id={controller_id!r}."
                ),
            }
        try:
            full_url = url.rstrip("/") + "/v1/state"
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.get(full_url)
            if response.status_code == 200:
                payload = _as_json_dict(response.json())
                if descriptor is not None:
                    payload.setdefault("_introspection_source", "auto-discovered")
                    payload.setdefault("_descriptor_path", descriptor.descriptor_path)
                return payload
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("embodiment_get_physics_state failed: %s", e)
            return {"error": str(e)}

    async def embodiment_set_joint_state(
        self,
        introspection_url: str | None = None,
        joint_qpos: dict[str, float] | None = None,
        joint_qvel: dict[str, float] | None = None,
        timeout_s: float = 2.0,
        controller_id: str = "mujoco",
    ) -> dict[str, Any]:
        """POST <introspection_url>/v1/set_state - place joints deterministically.

        Use to test reflex polarity (e.g. "what does my circuit do when the
        pendulum is at +30 degrees?") without waiting for natural fall.

        Args:
            introspection_url: Base URL of the controller's introspection
                server. When omitted, auto-discovered via the launcher-written
                descriptor.
            joint_qpos: Mapping ``joint_name -> qpos_value``.
            joint_qvel: Mapping ``joint_name -> qvel_value``.
            timeout_s: HTTP timeout.
            controller_id: Controller bundle id used during auto-discovery.
        """
        url, descriptor = self._resolve_introspection_url(
            introspection_url, controller_id
        )
        if url is None:
            return {
                "error": "introspection_url_unavailable",
                "message": (
                    f"No introspection URL provided and no descriptor found "
                    f"for controller_id={controller_id!r}."
                ),
            }
        try:
            payload: dict[str, Any] = {}
            if joint_qpos:
                payload["joint_qpos"] = {str(k): float(v) for k, v in joint_qpos.items()}
            if joint_qvel:
                payload["joint_qvel"] = {str(k): float(v) for k, v in joint_qvel.items()}
            if not payload:
                return {"error": "joint_qpos or joint_qvel must be provided"}
            full_url = url.rstrip("/") + "/v1/set_state"
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(full_url, json=payload)
            if 200 <= response.status_code < 300:
                payload_out = _as_json_dict(response.json()) or {"status": "ok"}
                if descriptor is not None:
                    payload_out.setdefault(
                        "_introspection_source", "auto-discovered"
                    )
                    payload_out.setdefault(
                        "_descriptor_path", descriptor.descriptor_path
                    )
                return payload_out
            return {
                "error": f"HTTP {response.status_code}",
                "message": response.text,
            }
        except Exception as e:
            logger.error("embodiment_set_joint_state failed: %s", e)
            return {"error": str(e)}
