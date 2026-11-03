"""Composer client for Brain Hub block datasheets.

Only the public, unauthenticated release read is implemented. The draft write and the preview
are owner routes behind Composer login and feagi-mcp holds no Composer credential, so they are
deliberately absent (see ``DRAFT_PATH`` / ``PREVIEW_PATH``, kept here so they align in one place
once an authenticated route exists).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from feagi_mcp.composer_simulator_packs import ComposerSimulatorPacksClient

logger = logging.getLogger(__name__)

# --- Composer URL paths: align with nrs-composer routers/v1/brain_releases.py here only. ---
#: Public release read (api.py mounts hub_router at /v1/public/global/hub). The release body
#: carries ``datasheet`` and ``ports_summary`` per the contract.
RELEASE_PATH = "/v1/public/global/hub/items/{item_id}/releases/{version}"
#: Owner routes (login required; NOT used by feagi-mcp, no Composer credential exists).
DRAFT_PATH = "/v1/public/regional/auth/user/brain-releases/genomes/{working_id}/datasheet-draft"
PREVIEW_PATH = "/v1/public/regional/auth/user/brain-releases/genomes/{working_id}/datasheet-preview"
# ------------------------------------------------------------------------------------------


class ComposerDatasheetClient(ComposerSimulatorPacksClient):
    """Read a release's datasheet from Composer (public, no auth)."""

    def _disabled_error(self) -> dict[str, Any]:
        return {
            "error": "composer_base_url_not_configured",
            "message": (
                "Set FEAGI_COMPOSER_BASE_URL to the Composer public API root "
                "(e.g. https://staging-api.brainsforrobots.com). "
                "Block datasheets are served from Composer, not FEAGI Core."
            ),
        }

    async def get_release_datasheet(self, item_id: str, version: int) -> dict[str, Any]:
        """GET the release and return its ``datasheet`` (and ``ports_summary``) or an error."""
        if self._client is None:
            return self._disabled_error()
        url = RELEASE_PATH.format(item_id=quote(item_id, safe=""), version=int(version))
        try:
            response = await self._client.get(url)
        except Exception as exc:
            logger.error("composer get_release_datasheet failed: %s", exc)
            return {"error": "request_failed", "message": str(exc)}
        body = self._consume_json(response)
        if body.get("error"):
            return body
        data = body.get("data")
        release: dict[str, Any] = data if isinstance(data, dict) else body
        datasheet = release.get("datasheet")
        if not isinstance(datasheet, dict):
            return {
                "error": "no_datasheet",
                "message": "This release has no datasheet (published without one, or taken down).",
                "http_status": body.get("http_status"),
            }
        return {
            "item_id": item_id,
            "version": version,
            "datasheet": datasheet,
            "ports_summary": release.get("ports_summary"),
        }
