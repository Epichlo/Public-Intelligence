"""Tests for security token authentication."""

import pytest
from httpx import ASGITransport, AsyncClient

from scheduler.core.config import Settings, get_settings
from scheduler.main import create_app


def _make_unauthorized_client() -> AsyncClient:
    app = create_app()
    settings = Settings(
        environment="development",
        debug=True,
        log_level="debug",
        network_auth_token="test-auth-token",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestAuthenticationEnforcement:
    """Verify that protected API endpoints enforce X-Network-Auth-Token."""

    async def test_register_node_unauthorized_missing_token(self):
        async with _make_unauthorized_client() as clean_client:
            response = await clean_client.post(
                "/nodes/register",
                json={
                    "node_id": "test-node",
                    "hostname": "test-host",
                    "ip_address": "127.0.0.1",
                    "region": "us-east-1",
                    "gpu": {
                        "name": "NVIDIA A10G",
                        "vram_total_gb": 24.0,
                        "vram_available_gb": 24.0,
                    },
                    "cpu_cores": 8,
                    "ram_total_gb": 32.0,
                    "available_models": ["llama-3"],
                },
            )
        assert response.status_code == 401
        assert response.json()["detail"] == "Unauthorized"

    async def test_register_node_unauthorized_invalid_token(self):
        async with _make_unauthorized_client() as clean_client:
            response = await clean_client.post(
                "/nodes/register",
                json={},
                headers={"X-Network-Auth-Token": "bad-token"},
            )
        assert response.status_code == 401

    async def test_heartbeat_unauthorized_missing_token(self):
        async with _make_unauthorized_client() as clean_client:
            response = await clean_client.post(
                "/heartbeat",
                json={
                    "node_id": "test-node",
                    "timestamp": "2026-07-16T12:00:00Z",
                    "status": "online",
                    "queue_length": 0,
                    "cpu_utilization": 0.0,
                    "ram_available_gb": 32.0,
                    "gpu_utilization": 0.0,
                    "vram_available_gb": 24.0,
                },
            )
        assert response.status_code == 401

    async def test_heartbeat_unauthorized_invalid_token(self):
        async with _make_unauthorized_client() as clean_client:
            response = await clean_client.post(
                "/heartbeat",
                json={},
                headers={"X-Network-Auth-Token": "bad-token"},
            )
        assert response.status_code == 401

    async def test_schedule_unauthorized_missing_token(self):
        async with _make_unauthorized_client() as clean_client:
            response = await clean_client.post(
                "/schedule",
                json={"model_name": "llama-3"},
            )
        assert response.status_code == 401

    async def test_schedule_unauthorized_invalid_token(self):
        async with _make_unauthorized_client() as clean_client:
            response = await clean_client.post(
                "/schedule",
                json={"model_name": "llama-3"},
                headers={"X-Network-Auth-Token": "bad-token"},
            )
        assert response.status_code == 401


class TestUnconfiguredTokenFailsClosed:
    """No configured fleet token must refuse everyone, not admit everyone.

    `verify_auth_token` enforced nothing while `settings.network_auth_token` was
    None -- which is its factory default -- while the server binds 0.0.0.0 by
    default. A fresh deployment therefore served every guarded route to the
    internet until an operator happened to set a token. The JWT gateway already
    fails closed in exactly this situation (an unconfigured key refuses every
    request), and the fleet token now behaves the same way -- with a loud
    startup warning, mirroring `InviteRegistry.warn_if_open`, so the refusing
    state is impossible to be in unknowingly.
    """

    def _client_without_token(self) -> AsyncClient:
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: Settings(network_auth_token=None)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_a_read_is_refused_when_no_token_is_configured(self):
        async with self._client_without_token() as clean_client:
            response = await clean_client.get("/nodes")
        assert response.status_code == 401
        assert "not configured" in response.json()["detail"]

    async def test_registration_is_refused_when_no_token_is_configured(self):
        body = {
            "node_id": "test-node",
            "hostname": "test-host",
            "ip_address": "127.0.0.1",
            "region": "us-east-1",
            "gpu": {"name": "NVIDIA A10G", "vram_total_gb": 24.0, "vram_available_gb": 24.0},
            "cpu_cores": 8,
            "ram_total_gb": 32.0,
            "available_models": ["llama-3"],
        }
        # Even WITH a header presented: there is nothing to compare it against,
        # so presenting one must not become a bypass.
        async with self._client_without_token() as clean_client:
            response = await clean_client.post(
                "/nodes/register",
                json=body,
                headers={"X-Network-Auth-Token": "anything"},
            )
        assert response.status_code == 401
        assert "not configured" in response.json()["detail"]


class TestUnconfiguredTokenWarnsAtStartup:
    """Fail-closed is only survivable if the operator is told, loudly, why."""

    def test_the_warning_fires_when_the_token_is_unset(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from scheduler.api.auth import warn_if_auth_disabled

        with caplog.at_level("WARNING"):
            warn_if_auth_disabled(Settings(network_auth_token=None))

        assert "network_auth_disabled" in caplog.text
        assert "SCHEDULER_NETWORK_AUTH_TOKEN" in caplog.text

    def test_a_configured_token_stays_quiet(self, caplog: pytest.LogCaptureFixture) -> None:
        from scheduler.api.auth import warn_if_auth_disabled

        with caplog.at_level("WARNING"):
            warn_if_auth_disabled(Settings(network_auth_token="set"))

        assert "network_auth_disabled" not in caplog.text
