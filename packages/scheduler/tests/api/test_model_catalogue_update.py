"""`PUT /nodes/{id}/models` keeps the advertised catalogue truthful (roadmap 1.4).

Registration captured a node's model list once and there was no way to change it:
`POST /nodes/register` is a create and answers 409 for a known node, and heartbeats
have no model field. So `GET /v1/models` and matchmaking described whatever the
node had pulled at the moment its process last started.

The node-side half -- when a refresh decides to push at all -- is in
`packages/node/tests/test_model_catalogue_refresh.py`.
"""

import pytest
from httpx import AsyncClient

from scheduler.models.node import Node
from tests.factories import make_node


async def register(client: AsyncClient, node: Node) -> None:
    """Register `node`, failing the test loudly if the fixture setup did not take."""
    response = await client.post("/nodes/register", json=node.model_dump(mode="json"))
    assert response.status_code == 201, response.text


@pytest.mark.anyio
async def test_update_replaces_the_catalogue(client: AsyncClient) -> None:
    """A pushed catalogue replaces what registration captured."""
    await register(client, make_node("n1", models=["llama3"]))

    response = await client.put(
        "/nodes/n1/models", json={"available_models": ["llama3", "mistral-7b"]}
    )

    assert response.status_code == 200
    assert response.json()["available_models"] == ["llama3", "mistral-7b"]

    listed = await client.get("/nodes/n1")
    assert listed.json()["available_models"] == ["llama3", "mistral-7b"]


@pytest.mark.anyio
async def test_update_can_remove_every_model(client: AsyncClient) -> None:
    """A node that has removed all its models can say so.

    An empty list is a real state, not a malformed request: the alternative is a
    node whose Ollama is empty being sent work it cannot do.
    """
    await register(client, make_node("n1", models=["llama3"]))

    response = await client.put("/nodes/n1/models", json={"available_models": []})

    assert response.status_code == 200
    assert response.json()["available_models"] == []


@pytest.mark.anyio
async def test_update_leaves_hardware_alone(client: AsyncClient) -> None:
    """The catalogue is the only thing this endpoint can change.

    Hardware is measured on the host once per process (roadmap 1.2) and is not
    runtime-variable. A refresh path that let a node restate it would be a way
    back to the self-asserted figures matchmaking used to score against.
    """
    await register(client, make_node("n1", vram=24.0, ram_total_gb=64.0, models=["llama3"]))

    response = await client.put(
        "/nodes/n1/models",
        json={
            "available_models": ["mistral-7b"],
            "gpu": {"name": "FAKE 9090", "vram_total_gb": 999.0, "vram_available_gb": 999.0},
            "ram_total_gb": 999.0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available_models"] == ["mistral-7b"]
    assert body["gpu"]["vram_total_gb"] == 24.0
    assert body["ram_total_gb"] == 64.0


@pytest.mark.anyio
async def test_update_for_an_unknown_node_is_404(client: AsyncClient) -> None:
    """Pushing a catalogue does not implicitly register the node."""
    response = await client.put("/nodes/ghost/models", json={"available_models": ["llama3"]})

    assert response.status_code == 404
    assert "ghost" in response.json()["detail"]


@pytest.mark.anyio
async def test_update_requires_authentication(client: AsyncClient) -> None:
    """The endpoint fails closed, like registration and unregistration."""
    await register(client, make_node("n1", models=["llama3"]))

    response = await client.put(
        "/nodes/n1/models",
        json={"available_models": ["mistral-7b"]},
        headers={"X-Network-Auth-Token": "wrong-token"},
    )

    assert response.status_code in (401, 403)

    unchanged = await client.get("/nodes/n1")
    assert unchanged.json()["available_models"] == ["llama3"]


@pytest.mark.anyio
async def test_update_preserves_reachability(client: AsyncClient) -> None:
    """The response is a NodeView, so it still reports how dispatch reaches the node."""
    await register(client, make_node("n1", models=["llama3"]))

    response = await client.put("/nodes/n1/models", json={"available_models": ["llama3"]})

    assert response.json()["reachability"] == "http"


# --- what the rest of the Scheduler sees ------------------------------------


@pytest.mark.anyio
async def test_pulled_model_becomes_routable(client: AsyncClient) -> None:
    """`GET /v1/models` gains a model the node pulled after it registered.

    This is failure mode 1: before the push existed, the model stayed invisible to
    the public catalogue and unroutable by the matchmaker until the node process
    restarted.
    """
    await register(client, make_node("n1", models=["llama3"]))

    before = await client.get("/v1/models")
    assert [m["id"] for m in before.json()["data"]] == ["llama3"]
    assert (await client.get("/v1/models/mistral-7b")).status_code == 404

    await client.put("/nodes/n1/models", json={"available_models": ["llama3", "mistral-7b"]})

    after = await client.get("/v1/models")
    assert [m["id"] for m in after.json()["data"]] == ["llama3", "mistral-7b"]
    assert (await client.get("/v1/models/mistral-7b")).status_code == 200


@pytest.mark.anyio
async def test_removed_model_stops_being_advertised(client: AsyncClient) -> None:
    """`GET /v1/models` drops a model the node deleted.

    This is failure mode 2, and the one that produced failures rather than just
    absences: the Scheduler kept selecting this node for a model whose weights were
    gone, and the node's own Ollama answered 404.
    """
    await register(client, make_node("n1", models=["llama3", "mistral-7b"]))

    await client.put("/nodes/n1/models", json={"available_models": ["llama3"]})

    after = await client.get("/v1/models")
    assert [m["id"] for m in after.json()["data"]] == ["llama3"]
    assert (await client.get("/v1/models/mistral-7b")).status_code == 404


@pytest.mark.anyio
async def test_update_does_not_affect_other_nodes(client: AsyncClient) -> None:
    """One node's refresh does not rewrite another's catalogue."""
    await register(client, make_node("n1", models=["llama3"]))
    await register(client, make_node("n2", models=["qwen2-7b"]))

    await client.put("/nodes/n1/models", json={"available_models": ["mistral-7b"]})

    n2 = await client.get("/nodes/n2")
    assert n2.json()["available_models"] == ["qwen2-7b"]

    catalogue = await client.get("/v1/models")
    assert [m["id"] for m in catalogue.json()["data"]] == ["mistral-7b", "qwen2-7b"]
