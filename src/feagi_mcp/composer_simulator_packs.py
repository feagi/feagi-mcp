"""HTTP helpers for Composer public simulator-asset-pack APIs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_PACKS_PREFIX = "/v1/public/global/simulator-packs"


def _as_json_dict(data: Any) -> dict[str, Any]:
    """Narrow decoded JSON payloads to mapping type."""
    if isinstance(data, dict):
        return data
    return {}


class ComposerSimulatorPacksClient:
    """Read-only Composer client for `/v1/public/global/simulator-packs`.

    Disabled when ``base_url`` is empty after strip; callers get a structured error.
    """

    def __init__(self, *, base_url: str, timeout: float) -> None:
        trimmed = base_url.strip().rstrip("/")
        self._base = trimmed
        self._timeout = timeout
        self._client: httpx.AsyncClient | None
        if self._base:
            # Composer may 308 from trailing-slash or host aliases; follow redirects.
            self._client = httpx.AsyncClient(
                base_url=self._base,
                timeout=timeout,
                follow_redirects=True,
            )
        else:
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _disabled_error(self) -> dict[str, Any]:
        return {
            "error": "composer_base_url_not_configured",
            "message": (
                "Set FEAGI_COMPOSER_BASE_URL to the Composer public API root "
                "(e.g. https://staging-api.brainsforrobots.com). "
                "Simulator pack listings are served from Composer, not FEAGI Core."
            ),
        }

    async def list_simulator_packs(
        self,
        *,
        engine: str | None = None,
        kind: str | None = None,
        state: str = "active",
    ) -> dict[str, Any]:
        """GET /simulator-packs with optional filters."""
        if self._client is None:
            return self._disabled_error()
        params: dict[str, str] = {}
        if engine is not None and engine.strip():
            params["engine"] = engine.strip()
        if kind is not None and kind.strip():
            params["kind"] = kind.strip()
        if state and state.strip():
            params["state"] = state.strip()
        try:
            response = await self._client.get(_PACKS_PREFIX, params=params or None)
        except Exception as exc:
            logger.error("composer list_simulator_packs failed: %s", exc)
            return {"error": "request_failed", "message": str(exc)}
        return self._consume_json(response)

    async def get_pack_version_summary(
        self, pack_id: str, *, engine: str | None = None
    ) -> dict[str, Any]:
        """GET /simulator-packs/{pack_id} (version index)."""
        if self._client is None:
            return self._disabled_error()
        slug = quote(pack_id, safe="")
        params: dict[str, str] = {}
        if engine is not None and engine.strip():
            params["engine"] = engine.strip()
        url = f"{_PACKS_PREFIX}/{slug}"
        try:
            response = await self._client.get(url, params=params or None)
        except Exception as exc:
            logger.error("composer get_pack_version_summary failed: %s", exc)
            return {"error": "request_failed", "message": str(exc)}
        return self._consume_json(response)

    async def get_pack_resolved(
        self, pack_id: str, semver: str, *, engine: str | None = None
    ) -> dict[str, Any]:
        """GET /simulator-packs/{pack_id}/versions/{semver}/resolved."""
        if self._client is None:
            return self._disabled_error()
        p = quote(pack_id, safe="")
        v = quote(semver, safe="")
        params: dict[str, str] = {}
        if engine is not None and engine.strip():
            params["engine"] = engine.strip()
        url = f"{_PACKS_PREFIX}/{p}/versions/{v}/resolved"
        try:
            response = await self._client.get(url, params=params or None)
        except Exception as exc:
            logger.error("composer get_pack_resolved failed: %s", exc)
            return {"error": "request_failed", "message": str(exc)}
        return self._consume_json(response)

    def _consume_json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except Exception:
            return {
                "error": "invalid_json",
                "http_status": response.status_code,
                "text_excerpt": (response.text or "")[:2048],
            }
        merged = _as_json_dict(body)
        merged.setdefault("http_status", response.status_code)
        if response.status_code < 200 or response.status_code >= 300:
            merged.setdefault(
                "error",
                merged.get("detail") if isinstance(merged.get("detail"), str) else "http_error",
            )
        return merged

    async def download_pack_bundle(
        self,
        output_directory: str,
        pack_id: str,
        semver: str,
        *,
        engine: str | None = None,
    ) -> dict[str, Any]:
        """Fetch resolved manifest, then download each file URL into ``output_directory``."""
        resolved = await self.get_pack_resolved(pack_id, semver, engine=engine)
        if resolved.get("error") == "composer_base_url_not_configured":
            return resolved
        http_st = resolved.get("http_status")
        if isinstance(http_st, int) and not (200 <= http_st < 300):
            err = dict(resolved)
            err.setdefault("error", "resolved_fetch_failed")
            return err
        if resolved.get("error"):
            return resolved
        payload = resolved.get("data")
        if not isinstance(payload, dict):
            return {
                "error": "unexpected_resolved_shape",
                "message": "Expected top-level {'data': {...}} from Composer resolved endpoint.",
                "http_status": resolved.get("http_status"),
            }
        files_map = payload.get("files")
        if not isinstance(files_map, dict):
            return {
                "error": "resolved_missing_files",
                "message": "Resolved manifest has no ``files`` object.",
            }

        out = Path(os.path.expanduser(output_directory)).resolve()
        out.mkdir(parents=True, exist_ok=True)

        if self._client is None:
            return self._disabled_error()

        saved: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as dl_http:
            for logical_name, file_url in files_map.items():
                if not isinstance(logical_name, str) or not isinstance(file_url, str):
                    continue
                name = logical_name.strip().replace("\\", "/").split("/")[-1]
                if not name or name in {".", ".."}:
                    return {
                        "error": "unsafe_file_entry",
                        "message": f"Rejected illegal pack file key {logical_name!r}",
                    }
                # Only single-segment filenames (Composer uses flat manifests).
                if logical_name.strip().replace("\\", "/").count("/") > 0:
                    return {
                        "error": "unsafe_file_entry",
                        "message": f"Rejected nested pack file key {logical_name!r}",
                    }

                dest = out / name
                try:
                    dl_resp = await dl_http.get(file_url)
                except Exception as exc:
                    logger.error("download_pack_bundle GET %s failed: %s", file_url, exc)
                    return {
                        "error": "download_failed",
                        "url": file_url,
                        "message": str(exc),
                        "saved_so_far": saved,
                    }
                if dl_resp.status_code < 200 or dl_resp.status_code >= 300:
                    return {
                        "error": "download_http_error",
                        "url": file_url,
                        "http_status": dl_resp.status_code,
                        "text_excerpt": (dl_resp.text or "")[:2048],
                        "saved_so_far": saved,
                    }
                dest.write_bytes(dl_resp.content)

                saved.append(
                    {
                        "logical_name": logical_name,
                        "path": str(dest),
                        "bytes_written": dest.stat().st_size,
                        "url": file_url,
                    }
                )

        return {
            "output_directory": str(out),
            "pack_id": pack_id,
            "semver": semver,
            "canonical_id": payload.get("canonical_id"),
            "content_hash": payload.get("content_hash"),
            "saved": saved,
        }
