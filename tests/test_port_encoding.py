"""Region port encoding: author-entry validation, ``set_port_encoding`` and its read paths.

Only the HTTP transport is replaced (``httpx.MockTransport``); the client method, the name
resolution and the validators run for real.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx

from feagi_mcp import server
from feagi_mcp.datasheet import FRAME_ENUM, KIND_ENUM, POSITIONING_ENUM
from feagi_mcp.feagi_client import FeagiClient
from feagi_mcp.port_encoding import (
    PORT_ENCODING_FIELDS,
    author_entry,
    author_entry_error,
    port_encoding_of,
    port_encoding_table,
)
from feagi_mcp.region_circuit import region_io_blockers, summarize_region_circuit


def _cid(raw: bytes) -> str:
    """Base64 cortical id from 8 raw bytes."""
    assert len(raw) == 8
    return base64.b64encode(raw).decode("ascii")


PORT = _cid(b"cport000")
OTHER = _cid(b"cother00")
REGION_ID = "region-1"
WIRING = {
    "kind": "Percentage",
    "signed": False,
    "frame": "Absolute",
    "positioning": "Linear",
    "source": "wiring",
}


class FakeFeagi:
    """A public-API stand-in: records requests, stores ``port_encoding`` like FEAGI does."""

    def __init__(self, put_status: int = 200, names: dict[str, str] | None = None) -> None:
        self.put_status = put_status
        self.names = names if names is not None else {PORT: "Level", OTHER: "Level2"}
        self.requests: list[httpx.Request] = []
        self.put_bodies: list[dict[str, Any]] = []
        self.encoding: dict[str, Any] = {PORT: dict(WIRING)}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/cortical_id_name_mapping"):
            return httpx.Response(200, json=self.names)
        if request.method == "GET" and path.endswith("/regions_members"):
            region = {"areas": [PORT, OTHER], "port_encoding": self.encoding}
            return httpx.Response(200, json={REGION_ID: region})
        if request.method == "PUT" and path.endswith("/v1/region/region"):
            body = json.loads(request.content)
            self.put_bodies.append(body)
            if self.put_status != 200:
                return httpx.Response(self.put_status, text=f"status {self.put_status}")
            for area_id, entry in body["port_encoding"].items():
                if entry is None:
                    self.encoding.pop(area_id, None)
                else:
                    self.encoding[area_id] = {**entry, "source": "author"}
            return httpx.Response(200, json={"message": "Brain region updated"})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    def client(self) -> FeagiClient:
        client = FeagiClient(host="localhost", port=8000)
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return client


class TestAuthorEntry:
    def test_vocabulary_is_the_shared_datasheet_vocabulary(self) -> None:
        assert PORT_ENCODING_FIELDS == ("kind", "signed", "frame", "positioning")
        for kind in KIND_ENUM:
            assert author_entry_error({"kind": kind}) is None
        for frame in FRAME_ENUM:
            assert author_entry_error({"frame": frame}) is None
        for positioning in POSITIONING_ENUM:
            assert author_entry_error({"positioning": positioning}) is None

    def test_bad_vocabulary_unknown_field_and_source_are_refused(self) -> None:
        assert "kind must be one of" in author_entry_error({"kind": "Float"})  # type: ignore[operator]
        assert "frame must be one of" in author_entry_error({"frame": "absolute"})  # type: ignore[operator]
        assert "positioning must be one of" in author_entry_error({"positioning": "Dense"})  # type: ignore[operator]
        assert "signed must be true or false" in author_entry_error({"signed": "yes"})  # type: ignore[operator]
        assert "unknown port_encoding field" in author_entry_error(  # type: ignore[operator]
            {"kind": "Boolean", "source": "author"}
        )

    def test_an_entry_needs_at_least_one_field(self) -> None:
        assert "clear=True" in author_entry_error(author_entry(None, None, None, None))  # type: ignore[operator]
        assert author_entry_error(author_entry(None, False, None, None)) is None

    def test_read_helpers_tolerate_missing_and_malformed_tables(self) -> None:
        region = {"port_encoding": {PORT: WIRING, "bad": "x"}}
        assert port_encoding_of(region, PORT) == WIRING
        assert port_encoding_of(region, OTHER) is None
        assert port_encoding_of("not a region", PORT) is None
        assert port_encoding_table(region) == {PORT: WIRING}
        assert port_encoding_table({}) == {}
        assert port_encoding_table({"port_encoding": []}) == {}


class TestSetPortEncoding:
    async def test_set_sends_only_the_delta_and_returns_the_resulting_entry(self) -> None:
        fake = FakeFeagi()
        out = await fake.client().set_port_encoding(
            REGION_ID, PORT, kind="SignedPercentage", signed=True, frame="Incremental"
        )
        assert fake.put_bodies == [
            {
                "region_id": REGION_ID,
                "port_encoding": {
                    PORT: {
                        "kind": "SignedPercentage",
                        "signed": True,
                        "frame": "Incremental",
                        "positioning": None,
                    }
                },
            }
        ]
        assert out["cleared"] is False and out["area_id"] == PORT
        assert out["port_encoding"] == {
            "kind": "SignedPercentage",
            "signed": True,
            "frame": "Incremental",
            "positioning": None,
            "source": "author",
        }

    async def test_clear_sends_null_and_wiring_derivation_result_is_returned(self) -> None:
        fake = FakeFeagi()
        client = fake.client()
        await client.set_port_encoding(REGION_ID, PORT, kind="Boolean")
        out = await client.set_port_encoding(REGION_ID, PORT, clear=True)
        assert fake.put_bodies[-1] == {"region_id": REGION_ID, "port_encoding": {PORT: None}}
        assert out["cleared"] is True
        assert out["port_encoding"] is None  # nothing derived for this fake region

    async def test_area_name_resolves_to_its_id(self) -> None:
        fake = FakeFeagi()
        out = await fake.client().set_port_encoding(REGION_ID, " Level ", kind="Boolean")
        assert list(fake.put_bodies[0]["port_encoding"]) == [PORT]
        assert out["area_id"] == PORT

    async def test_unknown_and_ambiguous_names_send_no_put(self) -> None:
        fake = FakeFeagi()
        unknown = await fake.client().set_port_encoding(REGION_ID, "Nope", kind="Boolean")
        assert "unknown cortical area" in unknown["error"]
        twin = FakeFeagi(names={PORT: "Same", OTHER: "Same"})
        ambiguous = await twin.client().set_port_encoding(REGION_ID, "Same", kind="Boolean")
        assert "matches 2 areas" in ambiguous["error"]
        assert fake.put_bodies == [] and twin.put_bodies == []

    async def test_local_validation_failures_make_no_http_request(self) -> None:
        fake = FakeFeagi()
        client = fake.client()
        bad_kind = await client.set_port_encoding(REGION_ID, PORT, kind="Float")
        empty = await client.set_port_encoding(REGION_ID, PORT)
        clear_with_field = await client.set_port_encoding(
            REGION_ID, PORT, kind="Boolean", clear=True
        )
        no_region = await client.set_port_encoding("  ", PORT, kind="Boolean")
        assert "kind must be one of" in bad_kind["error"]
        assert "at least one" in empty["error"]
        assert "clear=True takes no" in clear_with_field["error"]
        assert "region_id is required" in no_region["error"]
        assert fake.requests == []

    async def test_409_is_reported_as_area_not_designated(self) -> None:
        fake = FakeFeagi(put_status=409)
        out = await fake.client().set_port_encoding(REGION_ID, PORT, kind="Boolean")
        assert out["error"] == "area_not_designated"
        assert out["area_id"] == PORT and "designate" in out["hint"]

    async def test_400_and_404_are_named_and_other_statuses_pass_through(self) -> None:
        rejected = (
            await FakeFeagi(put_status=400)
            .client()
            .set_port_encoding(REGION_ID, PORT, kind="Boolean")
        )
        assert rejected["error"] == "rejected_by_feagi" and "400" in rejected["message"]
        missing = (
            await FakeFeagi(put_status=404)
            .client()
            .set_port_encoding(REGION_ID, PORT, kind="Boolean")
        )
        assert missing["error"] == "unknown_region"
        other = (
            await FakeFeagi(put_status=500)
            .client()
            .set_port_encoding(REGION_ID, PORT, kind="Boolean")
        )
        assert other["error"] == "HTTP 500"

    async def test_unknown_region_on_read_back_is_an_error(self) -> None:
        out = await FakeFeagi().client().set_port_encoding("other-region", PORT, kind="Boolean")
        assert out == {"error": "unknown_region", "region_id": "other-region"}


class TestToolRegistration:
    def test_tool_is_registered_with_the_documented_parameters(self) -> None:
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        tool = tools["set_port_encoding"]
        assert tool.annotations is None or not tool.annotations.readOnlyHint
        properties = tool.inputSchema["properties"]
        assert list(properties) == [
            "region_id",
            "area",
            "kind",
            "signed",
            "frame",
            "positioning",
            "clear",
        ]
        assert tool.inputSchema["required"] == ["region_id", "area"]

    async def test_tool_runs_through_the_client(self, monkeypatch: Any) -> None:
        fake = FakeFeagi()
        monkeypatch.setattr(server, "feagi", fake.client())
        out = await server.set_port_encoding(REGION_ID, "Level", positioning="Fractional")
        assert out["port_encoding"]["positioning"] == "Fractional"
        assert fake.put_bodies[0]["port_encoding"][PORT]["positioning"] == "Fractional"


class TestRegionViews:
    REGIONS = {
        REGION_ID: {
            "title": "Block",
            "areas": [PORT, OTHER],
            "regions": [],
            "designated_inputs": [PORT],
            "designated_outputs": [],
            "port_encoding": {PORT: WIRING},
        }
    }

    def test_region_circuit_echoes_the_port_encoding_table(self) -> None:
        out = summarize_region_circuit(self.REGIONS, {}, {}, REGION_ID)
        assert out["port_encoding"] == {PORT: WIRING}
        bare = {REGION_ID: {"title": "Block", "areas": [PORT]}}
        assert summarize_region_circuit(bare, {}, {}, REGION_ID)["port_encoding"] == {}

    def test_io_blockers_show_the_ports_entry(self) -> None:
        port = region_io_blockers(self.REGIONS, {}, {}, PORT)
        other = region_io_blockers(self.REGIONS, {}, {}, OTHER)
        assert port["port_encoding"] == WIRING
        assert other["port_encoding"] is None
