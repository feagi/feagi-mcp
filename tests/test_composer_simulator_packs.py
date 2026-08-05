"""Tests for Composer public simulator pack client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from feagi_mcp.composer_simulator_packs import ComposerSimulatorPacksClient


@pytest.fixture
def disabled_client() -> ComposerSimulatorPacksClient:
    return ComposerSimulatorPacksClient(base_url="  ", timeout=5.0)


@pytest.fixture
def mock_client() -> ComposerSimulatorPacksClient:
    c = ComposerSimulatorPacksClient(base_url="https://composer.example.invalid", timeout=5.0)
    c._client = AsyncMock()  # type: ignore[assignment]
    return c


def test_client_follows_redirects_when_enabled() -> None:
    """Composer hosts may 308; listing must follow redirects."""
    c = ComposerSimulatorPacksClient(base_url="https://composer.example.invalid", timeout=5.0)
    assert c._client is not None
    assert c._client.follow_redirects is True


@pytest.mark.asyncio
async def test_disabled_list_returns_guidance(
    disabled_client: ComposerSimulatorPacksClient,
) -> None:
    out = await disabled_client.list_simulator_packs(engine="mujoco")
    assert out["error"] == "composer_base_url_not_configured"
    await disabled_client.close()


@pytest.mark.asyncio
async def test_list_builds_path_and_query(mock_client: ComposerSimulatorPacksClient) -> None:
    mc = MagicMock()
    mc.status_code = 200
    mc.json.return_value = {"data": [{"pack_id": "x"}]}
    mock_client._client.get = AsyncMock(return_value=mc)

    seen = await mock_client.list_simulator_packs(engine="mujoco", kind=None, state="active")
    assert seen["http_status"] == 200
    assert seen["data"][0]["pack_id"] == "x"
    call = mock_client._client.get.await_args  # type: ignore[union-attr]
    assert str(call.args[0]).endswith("/v1/public/global/simulator-packs")
    assert call.kwargs["params"] == {"engine": "mujoco", "state": "active"}
    await mock_client.close()


@pytest.mark.asyncio
async def test_get_resolved_escapes_pack_id(mock_client: ComposerSimulatorPacksClient) -> None:
    mc = MagicMock()
    mc.status_code = 200
    mc.json.return_value = {"data": {"pack_id": "p"}}
    mock_client._client.get = AsyncMock(return_value=mc)

    seen = await mock_client.get_pack_resolved("a/b", "1.0.0")
    assert seen["http_status"] == 200
    args0 = mock_client._client.get.await_args.args[0]  # type: ignore[union-attr]
    assert "a%2Fb" in args0


@pytest.mark.asyncio
async def test_download_writes_files(
    mock_client: ComposerSimulatorPacksClient,
    tmp_path: Path,
) -> None:
    async def resolved_side_effect(*_: object, **__: object) -> dict:
        return {
            "http_status": 200,
            "data": {
                "pack_id": "demo",
                "semver": "1.0.0",
                "canonical_id": "mujoco:demo:1.0.0",
                "content_hash": "abc",
                "files": {
                    "tiny.txt": "https://blob.example.invalid/tiny.txt",
                },
            },
        }

    mock_client.get_pack_resolved = AsyncMock(side_effect=resolved_side_effect)

    dl = AsyncMock()

    mc_blob = MagicMock()
    mc_blob.status_code = 200
    mc_blob.content = b"hello pack"
    dl.get = AsyncMock(return_value=mc_blob)

    async def dl_ctx(*_: object, **__: object):  # noqa: ANN002
        return dl

    dl.__aenter__ = dl_ctx
    dl.__aexit__ = AsyncMock()

    import feagi_mcp.composer_simulator_packs as csp_mod

    orig_aclient = csp_mod.httpx.AsyncClient

    class _ACM:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN003
            _ = args, kwargs

        async def __aenter__(self) -> AsyncMock:
            return dl

        async def __aexit__(self, *args) -> None:  # noqa: ANN002
            return None

    csp_mod.httpx.AsyncClient = _ACM  # type: ignore[assignment]

    try:
        out_dir = tmp_path / "pack_out"
        out = await mock_client.download_pack_bundle(str(out_dir), "demo", "1.0.0")
        assert "error" not in out
        assert len(out["saved"]) == 1
        written = Path(out["saved"][0]["path"])
        assert written.read_bytes() == b"hello pack"
        assert written.name == "tiny.txt"
    finally:
        csp_mod.httpx.AsyncClient = orig_aclient  # type: ignore[assignment]
    await mock_client.close()


@pytest.mark.asyncio
async def test_download_rejects_nested_keys(
    mock_client: ComposerSimulatorPacksClient,
    tmp_path: Path,
) -> None:
    async def bad_resolved(*_: object, **__: object) -> dict:
        return {
            "http_status": 200,
            "data": {
                "files": {"../evil.xml": "https://blob.example.invalid/x"},
            },
        }

    mock_client.get_pack_resolved = AsyncMock(side_effect=bad_resolved)
    out = await mock_client.download_pack_bundle(str(tmp_path / "o"), "p", "1.0.0")
    assert out.get("error") == "unsafe_file_entry"


@pytest.mark.asyncio
async def test_download_fails_when_resolved_http_error(
    mock_client: ComposerSimulatorPacksClient,
    tmp_path: Path,
) -> None:
    mock_client.get_pack_resolved = AsyncMock(return_value={"http_status": 404, "detail": "nope"})
    out = await mock_client.download_pack_bundle(str(tmp_path / "o"), "p", "1.0.0")
    assert out["error"] == "resolved_fetch_failed"
