"""Application configuration via environment variables."""

import json
from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Environment(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via environment variables prefixed
    with ``SCHEDULER_``. For example: ``SCHEDULER_LOG_LEVEL=debug``.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "info"
    # B104 (bind-all-interfaces) is suppressed on the default below, and that is
    # deliberate, not accidental: Render (and Scheduler/Dockerfile's
    # `uvicorn --host 0.0.0.0`) routes external traffic into the container, where
    # loopback would be unreachable and health checks would fail. Operators wanting
    # a specific interface override it via SCHEDULER_HOST.
    #
    # This explanation must not begin with the `nosec` token: bandit parses the
    # words following it as test IDs and warns on each one.
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    network_auth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCHEDULER_NETWORK_AUTH_TOKEN", "NETWORK_AUTH_TOKEN"),
        description="Secure network authentication token.",
    )
    node_api_port: int = Field(
        default=8080,
        validation_alias=AliasChoices("SCHEDULER_NODE_API_PORT", "NODE_API_PORT"),
        description="HTTP port used to reach registered Node inference APIs.",
    )
    database_path: str | None = Field(
        # ON by default as of ROADMAP C3. It used to default to None, and the
        # reasoning was sound at the time: a default path on an ephemeral filesystem
        # (Render's free tier) survives a process restart and is wiped by every
        # redeploy -- durability that looks like it works and does not.
        #
        # docs/decisions/D6-is-there-a-network.md removed that deployment. This is a
        # self-hosted product, so the operator has a real disk, and the balance
        # flips: NOTHING set this, so nothing persisted anywhere, and the ledger is
        # the unrecoverable half of the state. A node re-registers itself after a 404
        # heartbeat (ROADMAP 1.6), so losing the registry is a recovery window;
        # nothing but the Scheduler ever knew a credit balance.
        #
        # `create_app()` still does not read this -- build_store() is the only
        # reader -- which matters MORE now, not less: without that, every test in the
        # repo would share one file. Pinned by
        # test_persistence_and_limits_are_honest.py.
        default="scheduler-state.db",
        validation_alias=AliasChoices("SCHEDULER_DATABASE_PATH", "DATABASE_PATH"),
        description=(
            "SQLite file for durable node and credit state, relative to the working "
            "directory. Set to an empty string to run with no persistence, in which "
            "case every restart loses every credit balance. "
            "See specs/scheduler-persistence.md."
        ),
    )

    jwt_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCHEDULER_JWT_PUBLIC_KEY", "JWT_PUBLIC_KEY"),
        description=(
            "PEM public key that verifies requester JWTs. Unset means the gateway "
            "refuses every request: there is deliberately no fallback key, because "
            "the one that used to be here was a literal of unknown provenance."
        ),
    )
    jwt_public_key_secondary: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SCHEDULER_JWT_PUBLIC_KEY_SECONDARY", "JWT_PUBLIC_KEY_SECONDARY"
        ),
        description=(
            "Second PEM public key accepted during rotation, addressed as kid "
            "'secondary'. Set this to the OUTGOING key while tokens minted under it "
            "are still live, then clear it. Rotation without this is an outage: "
            "replacing the single key invalidates every issued token at once."
        ),
    )

    rate_limit_capacity: int = Field(
        default=5,
        validation_alias=AliasChoices("SCHEDULER_RATE_LIMIT_CAPACITY", "RATE_LIMIT_CAPACITY"),
        description=(
            "Burst capacity of the per-tenant token bucket. This limiter is "
            "in-memory and PER-INSTANCE: it resets on restart and would not hold "
            "across replicas, so it is an abuse dampener and not a quota. Adequate "
            "because the deployment is a single instance "
            "(docs/decisions/D5-decentralisation-claim.md)."
        ),
    )
    rate_limit_refill_per_second: float = Field(
        default=0.5,
        validation_alias=AliasChoices(
            "SCHEDULER_RATE_LIMIT_REFILL", "RATE_LIMIT_REFILL_PER_SECOND"
        ),
        description=(
            "Token refill rate per second, per tenant. Per-instance and in-memory; "
            "see rate_limit_capacity. Default 0.5 is one request every two seconds "
            "sustained, bursting to rate_limit_capacity."
        ),
    )

    node_stale_after_seconds: float = Field(
        default=90.0,
        validation_alias=AliasChoices("SCHEDULER_NODE_STALE_AFTER", "NODE_STALE_AFTER"),
        description=(
            "Evict a node whose last VERIFIED heartbeat is older than this. Default is "
            "three missed heartbeats at the node's 30s default interval. This is the "
            "only thing that ages nodes out: a dropped Zenoh liveliness token no longer "
            "unregisters anything, because a liveliness token carries no payload to sign "
            "and its node id comes from a key expression the publisher chose. "
            "See specs/authenticated-mesh-ingress.md."
        ),
    )
    stale_sweep_interval_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices("SCHEDULER_STALE_SWEEP_INTERVAL", "STALE_SWEEP_INTERVAL"),
        description="How often to look for nodes that have gone quiet.",
    )

    # Mirrored by `node.core.configuration.Settings.cors_allow_origins` -- two FastAPI
    # apps with separate settings classes, so there is no shared module to change.
    # If this field or its validator changes, change that one too.
    cors_allow_origins: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("SCHEDULER_CORS_ALLOW_ORIGINS", "CORS_ALLOW_ORIGINS"),
        description=(
            "Browser origins permitted to read this Scheduler's responses cross-origin. "
            "Empty (the default) installs no CORS middleware at all, which is correct "
            "for every deployment today: every browser fetch in packages/website goes to "
            "a same-origin Next.js route that reaches this service server-side. "
            "See specs/close-the-open-http-surface.md."
        ),
    )

    # Zenoh WAN Networking
    zenoh_listen_endpoints: list[str] = Field(
        default_factory=lambda: ["tcp/0.0.0.0:7447"],
        validation_alias=AliasChoices("SCHEDULER_ZENOH_LISTEN_ENDPOINTS", "ZENOH_LISTEN_ENDPOINTS"),
        description="Zenoh TCP endpoints to listen on for WAN node connections.",
    )
    zenoh_peer_endpoints: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("SCHEDULER_ZENOH_PEER_ENDPOINTS", "ZENOH_PEER_ENDPOINTS"),
        description="Zenoh WAN endpoints of peer Schedulers.",
    )
    bootstrap_routers: list[str] = Field(
        default_factory=lambda: ["tcp/bootstrap.public-intelligence.net:7447"],
        validation_alias=AliasChoices("SCHEDULER_BOOTSTRAP_ROUTERS", "BOOTSTRAP_ROUTERS"),
        description="Fallback Zenoh bootstrap routers for dynamic WAN peer join.",
    )
    zenoh_gossip_scouting: bool = Field(
        default=True,
        validation_alias=AliasChoices("SCHEDULER_ZENOH_GOSSIP_SCOUTING", "ZENOH_GOSSIP_SCOUTING"),
        description="Enable/disable Zenoh gossip scouting for dynamic WAN peer join.",
    )
    zenoh_multicast_scouting: bool = Field(
        default=True,
        description="Enable/disable local LAN multicast scouting.",
    )
    mesh_inference_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("SCHEDULER_MESH_INFERENCE_ENABLED", "MESH_INFERENCE_ENABLED"),
        description=(
            "Route inference to nodes over the Zenoh mesh when they have been seen there. "
            "Disable to force the HTTP path for every node."
        ),
    )
    mesh_inference_timeout_seconds: float = Field(
        default=120.0,
        validation_alias=AliasChoices("SCHEDULER_MESH_INFERENCE_TIMEOUT", "MESH_INFERENCE_TIMEOUT"),
        description=(
            "Total seconds a mesh inference query may run. Must exceed generation time "
            "for the largest model a host serves, or long completions are cut off."
        ),
    )
    mesh_inference_first_reply_timeout_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "SCHEDULER_MESH_INFERENCE_FIRST_REPLY_TIMEOUT",
            "MESH_INFERENCE_FIRST_REPLY_TIMEOUT",
        ),
        description=(
            "Seconds to wait for a node's first mesh reply before falling back to HTTP. "
            "Bounds what a node that is on the mesh but not serving costs per request, so "
            "it is deliberately far shorter than the total timeout."
        ),
    )
    split_inference_timeout_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "SCHEDULER_SPLIT_INFERENCE_TIMEOUT", "SPLIT_INFERENCE_TIMEOUT"
        ),
        description="Timeout in seconds for remote split-stage activation responses.",
    )

    @field_validator("cors_allow_origins")
    @classmethod
    def reject_wildcard_origin(cls, v: list[str]) -> list[str]:
        """Refuse `*`, which does not mean what an operator setting it expects.

        Starlette does not send `Access-Control-Allow-Origin: *` when credentials
        are enabled -- it **reflects the caller's own Origin** and sets
        `Access-Control-Allow-Credentials: true`. So `*` is not a permissive-but-
        anonymous setting; it is "every origin, individually, with credentials",
        which is the exact defect ROADMAP 2.3 exists to remove. Failing at boot with
        this message beats a service that reads as configured and answers everyone.

        Mirrored by `node.core.configuration.Settings.reject_wildcard_origin`.
        """
        if any(origin.strip() == "*" for origin in v):
            msg = (
                "cors_allow_origins must not contain '*': with credentials enabled "
                "Starlette does not send a wildcard, it reflects the caller's Origin "
                "back, allowing every origin individually. List the origins instead."
            )
            raise ValueError(msg)
        return v

    @field_validator(
        "zenoh_listen_endpoints",
        "zenoh_peer_endpoints",
        "bootstrap_routers",
        "cors_allow_origins",
        mode="before",
    )
    @classmethod
    def parse_string_list(cls, v: Any) -> list[str]:
        """Parse list of strings from comma-separated string, JSON, or list."""
        raw_items: list[Any] = []
        if isinstance(v, list):
            raw_items = v
        elif isinstance(v, str):
            val = v.strip()
            if not val:
                return []
            if val.startswith("[") and val.endswith("]"):
                try:
                    parsed = json.loads(val)
                    raw_items = parsed if isinstance(parsed, list) else [val]
                except json.JSONDecodeError:
                    raw_items = [val]
            else:
                raw_items = val.split(",")
        else:
            return []

        parsed_items: list[str] = []
        for item in raw_items:
            item_str = str(item).strip()
            if not item_str:
                raise ValueError("List element cannot be empty or whitespace-only.")
            parsed_items.append(item_str)
        return parsed_items

    @classmethod
    def settings_customise_sources(
        cls,
        _settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customise settings sources to allow lenient list parsing in env / dotenv."""
        if hasattr(env_settings, "decode_complex_value"):
            orig_env_decode = env_settings.decode_complex_value

            def custom_env_decode(field_name: str, field: Any, value: Any) -> Any:
                if field_name in (
                    "zenoh_listen_endpoints",
                    "zenoh_peer_endpoints",
                    "bootstrap_routers",
                    "cors_allow_origins",
                ):
                    try:
                        return json.loads(value)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        return value
                return orig_env_decode(field_name, field, value)

            env_settings.decode_complex_value = custom_env_decode  # type: ignore

        if hasattr(dotenv_settings, "decode_complex_value"):
            orig_dotenv_decode = dotenv_settings.decode_complex_value

            def custom_dotenv_decode(field_name: str, field: Any, value: Any) -> Any:
                if field_name in (
                    "zenoh_listen_endpoints",
                    "zenoh_peer_endpoints",
                    "bootstrap_routers",
                    "cors_allow_origins",
                ):
                    try:
                        return json.loads(value)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        return value
                return orig_dotenv_decode(field_name, field, value)

            dotenv_settings.decode_complex_value = custom_dotenv_decode  # type: ignore

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings.

    Uses ``lru_cache`` so environment variables are read once at startup.
    Override in tests via ``app.dependency_overrides[get_settings]``.
    """
    return Settings()
