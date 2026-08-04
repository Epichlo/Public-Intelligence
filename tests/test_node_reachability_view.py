"""`GET /nodes` reports how a node is actually reachable (roadmap 1.2).

Every installer-provisioned node registers `ip_address = 127.0.0.1`, so listing
that address alone implies each node is dialable at the Scheduler's own loopback.
It is not. Dispatch reaches these nodes over the Zenoh mesh (roadmap 1.1); the
registry knows which nodes it has observed there, and this surfaces it.

`reachability` is derived from the registry, never from the registration payload --
a node must not be able to assert that it is mesh-reachable.
"""

import pytest

NODE_BODY = {
    "node_id": "node-1",
    "hostname": "host",
    "ip_address": "127.0.0.1",
    "region": "local",
    "gpu": {"name": "NVIDIA GeForce RTX 4090", "vram_total_gb": 24.0, "vram_available_gb": 20.0},
    "cpu_cores": 8,
    "ram_total_gb": 32.0,
    "available_models": ["llama3"],
}


@pytest.mark.anyio
async def test_list_nodes_reports_http_before_mesh_is_observed(client) -> None:  # type: ignore[no-untyped-def]
    """A node not yet seen on the mesh is only reachable over HTTP."""
    assert (await client.post("/nodes/register", json=NODE_BODY)).status_code == 201

    body = (await client.get("/nodes")).json()

    assert len(body) == 1
    assert body[0]["reachability"] == "http"


@pytest.mark.anyio
async def test_list_nodes_reports_mesh_once_observed(client) -> None:  # type: ignore[no-untyped-def]
    """Once the registry has seen the node on the mesh, listing says so."""
    assert (await client.post("/nodes/register", json=NODE_BODY)).status_code == 201

    client._transport.app.state.registry.mark_mesh_reachable("node-1")

    body = (await client.get("/nodes")).json()

    assert body[0]["reachability"] == "mesh"


@pytest.mark.anyio
async def test_get_node_reports_reachability(client) -> None:  # type: ignore[no-untyped-def]
    """The single-node endpoint carries the same field."""
    assert (await client.post("/nodes/register", json=NODE_BODY)).status_code == 201
    client._transport.app.state.registry.mark_mesh_reachable("node-1")

    body = (await client.get("/nodes/node-1")).json()

    assert body["reachability"] == "mesh"
    assert body["node_id"] == "node-1"


@pytest.mark.anyio
async def test_reachability_cannot_be_asserted_by_the_node(client) -> None:  # type: ignore[no-untyped-def]
    """A node claiming mesh reachability at registration is not believed."""
    body = dict(NODE_BODY, reachability="mesh")

    assert (await client.post("/nodes/register", json=body)).status_code == 201

    listed = (await client.get("/nodes")).json()

    assert listed[0]["reachability"] == "http"


@pytest.mark.anyio
async def test_listing_still_never_leaks_the_node_token(client) -> None:  # type: ignore[no-untyped-def]
    """The new response model must not widen what GET /nodes exposes."""
    assert (
        await client.post(
            "/nodes/register",
            json=NODE_BODY,
            headers={"X-Network-Auth-Token": "test-auth-token"},
        )
    ).status_code == 201

    raw = (await client.get("/nodes")).text

    assert "test-auth-token" not in raw
    assert "token" not in raw.lower()
