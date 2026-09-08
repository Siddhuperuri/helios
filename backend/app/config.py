"""Application configuration.

All tunable values live here rather than being scattered through the code. Anything that
could reasonably differ between a laptop and a deployment is read from the environment,
with a safe default.

The upstream *data* services remain keyless and public — that has not changed. What has
changed is everything around them: accounts, sessions, transactional email and shared
infrastructure all require real secrets, so this module now reads them from the
environment and refuses to start a production process that is still holding defaults.
See :meth:`Settings.production_problems`.

Development defaults are deliberately zero-configuration (SQLite on disk, an in-process
stand-in for Redis) so that `pytest` and `uvicorn` run on a laptop with nothing installed.
Those fallbacks are fail-closed: with ``SOLAR_ENV=production`` they are rejected at
startup rather than silently making the backend stateful again.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(key: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in _env_str(key, default).split(",") if item.strip())


def _env_first(default: str, *keys: str) -> str:
    """First environment variable that is set, else the default.

    Exists so the deployment-standard names (``DATABASE_URL``, ``REDIS_URL``) work
    alongside this project's own ``SOLAR_`` vocabulary without either becoming the odd
    one out.
    """
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


@dataclass(frozen=True)
class DataSourceSettings:
    """Upstream data services. Both are keyless, public, and rate-limited by the provider."""

    archive_url: str = _env_str(
        "SOLAR_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive"
    )
    forecast_url: str = _env_str(
        "SOLAR_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
    )
    geocoding_url: str = _env_str(
        "SOLAR_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
    )
    elevation_url: str = _env_str(
        "SOLAR_ELEVATION_URL", "https://api.open-meteo.com/v1/elevation"
    )
    # Reverse geocoding — turning a GPS fix or a dropped map pin back into a place name —
    # is the one capability Open-Meteo does not offer, so it comes from OpenStreetMap's
    # Nominatim. Their usage policy requires an identifying User-Agent and asks that
    # results be cached rather than re-requested; both are honoured. Coordinates are
    # rounded before the request, which improves the cache hit rate and sends a third
    # party less precision about where the user is standing.
    reverse_geocoding_url: str = _env_str(
        "SOLAR_REVERSE_GEOCODING_URL", "https://nominatim.openstreetmap.org/reverse"
    )
    reverse_geocoding_precision: int = _env_int("SOLAR_REVERSE_PRECISION", 3)
    request_timeout_s: float = _env_float("SOLAR_HTTP_TIMEOUT", 45.0)
    max_retries: int = _env_int("SOLAR_HTTP_RETRIES", 3)
    retry_backoff_s: float = _env_float("SOLAR_HTTP_BACKOFF", 1.5)

    # Attribution is a licence condition, not a courtesy. Rendered in the UI footer
    # and embedded in every exported report.
    attribution: str = (
        "Weather and irradiance data from Open-Meteo (CC-BY 4.0), derived from "
        "ECMWF ERA5 / ERA5-Land reanalysis (Copernicus Climate Change Service)."
    )
    dataset_name: str = "Open-Meteo Historical Weather API (ERA5 reanalysis)"


@dataclass(frozen=True)
class CacheSettings:
    """On-disk cache for upstream responses.

    Caching is a scientific requirement here, not just a performance one: a cached raw
    payload is what makes a past experiment reproducible after the upstream service has
    revised its reanalysis.
    """

    directory: Path = field(
        default_factory=lambda: Path(
            _env_str("SOLAR_CACHE_DIR", str(BACKEND_ROOT / "var" / "cache"))
        )
    )
    enabled: bool = _env_bool("SOLAR_CACHE_ENABLED", True)
    ttl_seconds: int = _env_int("SOLAR_CACHE_TTL", 60 * 60 * 24 * 30)
    # The cache now lives in Redis so that every replica shares one copy. The directory
    # above remains as a last-resort tier used only when Redis is unreachable: a weather
    # fetch costs tens of seconds, and losing the cache during a Redis incident would turn
    # a degraded dependency into a visibly broken product. It is per-replica and therefore
    # not shared state — it is a miss-avoidance tier, and the reproducibility guarantee
    # rests on Redis persistence, not on it.
    disk_fallback: bool = _env_bool("SOLAR_CACHE_DISK_FALLBACK", True)


@dataclass(frozen=True)
class StoreSettings:
    """Local persistence for experiments and trained model artefacts."""

    directory: Path = field(
        default_factory=lambda: Path(
            _env_str("SOLAR_STORE_DIR", str(BACKEND_ROOT / "var" / "store"))
        )
    )
    max_experiments: int = _env_int("SOLAR_MAX_EXPERIMENTS", 200)
    # How long a saved consumer estimate is kept. Swept at startup, because nothing else
    # will ever delete one: estimates have no owner to tidy up after them.
    estimate_retention_days: int = _env_int("SOLAR_ESTIMATE_RETENTION_DAYS", 365)


@dataclass(frozen=True)
class ValidationLimits:
    """Hard input limits. These are enforced at the API boundary.

    They exist for two separate reasons that happen to coincide: they keep scientifically
    meaningless requests out of the pipeline, and they bound the work a single unauthenticated
    request can cause the server to do.
    """

    min_latitude: float = -90.0
    max_latitude: float = 90.0
    min_longitude: float = -180.0
    max_longitude: float = 180.0

    # Open-Meteo's ERA5 archive begins in 1940; we start in 2000 where ERA5-Land quality
    # and station density are materially better.
    earliest_date: str = "2000-01-01"

    # ERA5 reanalysis is published on a delay; requesting the last few days returns gaps.
    archive_lag_days: int = _env_int("SOLAR_ARCHIVE_LAG_DAYS", 6)

    min_training_days: int = _env_int("SOLAR_MIN_TRAIN_DAYS", 60)
    max_training_days: int = _env_int("SOLAR_MAX_TRAIN_DAYS", 3650)
    default_training_days: int = _env_int("SOLAR_DEFAULT_TRAIN_DAYS", 730)

    # Forecast horizon in hours. The upper bound is not arbitrary: Open-Meteo's public
    # forecast endpoint publishes 16 days, and Hobbs & Joshi [P1] evaluate scheduling
    # windows up to 7 days. Beyond the validated horizon the API warns explicitly.
    min_horizon_hours: int = 1
    max_horizon_hours: int = 16 * 24
    validated_horizon_hours: int = _env_int("SOLAR_VALIDATED_HORIZON", 7 * 24)

    max_upload_bytes: int = _env_int("SOLAR_MAX_UPLOAD_BYTES", 8 * 1024 * 1024)
    max_scenario_count: int = 12


@dataclass(frozen=True)
class ModellingDefaults:
    """Defaults for the modelling pipeline, all overridable per request."""

    random_seed: int = _env_int("SOLAR_SEED", 20240617)

    # Fraction of the (chronologically ordered) record held out as a final test set.
    test_fraction: float = _env_float("SOLAR_TEST_FRACTION", 0.2)

    # Rolling-origin folds for time-aware cross-validation.
    cv_splits: int = _env_int("SOLAR_CV_SPLITS", 5)

    # A gap between train and validation in each fold. Adjacent hours are strongly
    # autocorrelated, so touching folds leak information across the boundary even when
    # the split is chronological. Measured in hours.
    cv_gap_hours: int = _env_int("SOLAR_CV_GAP_HOURS", 24)

    # Quantiles used to form prediction intervals. The pair (0.1, 0.9) gives a nominal
    # 80 % interval; (0.025, 0.975) a nominal 95 %.
    quantiles: tuple[float, ...] = (0.025, 0.1, 0.5, 0.9, 0.975)

    # Modelling target. "clear_sky_index" removes the deterministic diurnal and seasonal
    # signal before fitting, leaving the model to learn only the atmospheric attenuation.
    default_target: str = _env_str("SOLAR_TARGET", "clear_sky_index")

    default_model: str = _env_str("SOLAR_MODEL", "random_forest")


@dataclass(frozen=True)
class DatabaseSettings:
    """Durable application state: users, OAuth links, estimates, experiments.

    The default is a SQLite file so a fresh checkout runs its test suite and its dev
    server with nothing installed. Every deployment beyond a laptop points ``DATABASE_URL``
    at PostgreSQL — in the shipped topology, at PgBouncer in front of PostgreSQL, so that
    connection count does not grow linearly with the number of backend replicas.

    The pool is deliberately small for the same reason. PgBouncer multiplexes; a large
    per-process pool would defeat the point of putting it there.
    """

    url: str = field(
        default_factory=lambda: _env_first(
            f"sqlite:///{BACKEND_ROOT / 'var' / 'helios.db'}",
            "DATABASE_URL",
            "SOLAR_DATABASE_URL",
        )
    )
    pool_size: int = field(default_factory=lambda: _env_int("SOLAR_DB_POOL_SIZE", 5))
    max_overflow: int = field(default_factory=lambda: _env_int("SOLAR_DB_MAX_OVERFLOW", 5))
    pool_timeout_s: int = field(default_factory=lambda: _env_int("SOLAR_DB_POOL_TIMEOUT", 30))
    pool_recycle_s: int = field(default_factory=lambda: _env_int("SOLAR_DB_POOL_RECYCLE", 1800))
    echo: bool = field(default_factory=lambda: _env_bool("SOLAR_DB_ECHO", False))

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.url.startswith(("postgresql", "postgres:"))

    @property
    def safe_url(self) -> str:
        """The URL with any password removed, for logs and health payloads."""
        if "@" not in self.url:
            return self.url
        scheme, _, rest = self.url.partition("://")
        credentials, _, host = rest.rpartition("@")
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}" if user else f"{scheme}://***@{host}"


@dataclass(frozen=True)
class RedisSettings:
    """Shared ephemeral state: cache, rate limits, and short-lived authentication tokens.

    ``memory://`` selects a process-shared stand-in used by the test suite and by a laptop
    with no Redis running. It is rejected in production, because a rate limiter or an
    OAuth state store that lives in one process's memory is precisely the failure this
    architecture exists to remove.
    """

    url: str = field(
        default_factory=lambda: _env_first("memory://", "REDIS_URL", "SOLAR_REDIS_URL")
    )
    socket_timeout_s: float = field(
        default_factory=lambda: _env_float("SOLAR_REDIS_TIMEOUT", 3.0)
    )
    connect_timeout_s: float = field(
        default_factory=lambda: _env_float("SOLAR_REDIS_CONNECT_TIMEOUT", 3.0)
    )
    max_connections: int = field(
        default_factory=lambda: _env_int("SOLAR_REDIS_MAX_CONNECTIONS", 32)
    )
    key_prefix: str = field(default_factory=lambda: _env_str("SOLAR_REDIS_PREFIX", "helios"))

    @property
    def is_memory(self) -> bool:
        return self.url.startswith("memory://")


# Long enough to clear PyJWT's minimum-key-length warning, and named so that it cannot
# be mistaken for a real secret in a log line or a config dump.
_DEV_JWT_SECRET = "dev-insecure-secret-change-me-before-production"


@dataclass(frozen=True)
class AuthSettings:
    """Tokens, hashing and cookies.

    Access tokens are short-lived JWTs carried in the ``Authorization`` header. Refresh
    tokens are opaque, stored only as a hash in Redis, rotated on every use, and delivered
    in an httpOnly cookie — which is why the CSRF protection below is not optional.
    """

    jwt_secret: str = field(
        default_factory=lambda: _env_first(
            _DEV_JWT_SECRET, "JWT_SECRET", "SOLAR_JWT_SECRET"
        )
    )
    jwt_algorithm: str = field(default_factory=lambda: _env_str("JWT_ALGORITHM", "HS256"))
    jwt_issuer: str = field(default_factory=lambda: _env_str("JWT_ISSUER", "helios"))
    jwt_audience: str = field(default_factory=lambda: _env_str("JWT_AUDIENCE", "helios-api"))

    access_ttl_minutes: int = field(default_factory=lambda: _env_int("JWT_ACCESS_TTL_MIN", 15))
    refresh_ttl_days: int = field(default_factory=lambda: _env_int("JWT_REFRESH_TTL_DAYS", 30))
    verification_ttl_hours: int = field(
        default_factory=lambda: _env_int("VERIFICATION_TOKEN_TTL_HOURS", 24)
    )
    password_reset_ttl_hours: int = field(
        default_factory=lambda: _env_int("PASSWORD_RESET_TOKEN_TTL_HOURS", 1)
    )
    oauth_state_ttl_seconds: int = field(
        default_factory=lambda: _env_int("OAUTH_STATE_TTL_SECONDS", 600)
    )

    refresh_cookie_name: str = field(
        default_factory=lambda: _env_str("SOLAR_REFRESH_COOKIE", "helios_refresh")
    )
    csrf_cookie_name: str = field(
        default_factory=lambda: _env_str("SOLAR_CSRF_COOKIE", "helios_csrf")
    )
    csrf_header_name: str = field(
        default_factory=lambda: _env_str("SOLAR_CSRF_HEADER", "X-CSRF-Token")
    )
    # Host-only cookies by default. Set this only when the frontend and the API are on
    # sibling subdomains of one registrable domain; never to a public suffix.
    cookie_domain: str | None = field(
        default_factory=lambda: _env_str("SOLAR_COOKIE_DOMAIN", "") or None
    )
    cookie_secure: bool = field(default_factory=lambda: _env_bool("SOLAR_COOKIE_SECURE", False))
    cookie_samesite: str = field(default_factory=lambda: _env_str("SOLAR_COOKIE_SAMESITE", "lax"))

    min_password_length: int = field(
        default_factory=lambda: _env_int("SOLAR_MIN_PASSWORD_LENGTH", 10)
    )
    max_password_length: int = field(
        default_factory=lambda: _env_int("SOLAR_MAX_PASSWORD_LENGTH", 256)
    )

    # Argon2id work factors. The defaults are the OWASP Password Storage Cheat Sheet's
    # low-memory configuration (19 MiB, t=2, p=1), which argon2-cffi also ships as a
    # named profile. Raise the memory cost, not the iteration count, if you have room.
    argon2_time_cost: int = field(default_factory=lambda: _env_int("SOLAR_ARGON2_TIME_COST", 2))
    argon2_memory_kib: int = field(
        default_factory=lambda: _env_int("SOLAR_ARGON2_MEMORY_KIB", 19 * 1024)
    )
    argon2_parallelism: int = field(
        default_factory=lambda: _env_int("SOLAR_ARGON2_PARALLELISM", 1)
    )

    # Aggressive limits on the endpoints that mint credentials or send mail. Separate from
    # the general API limit because the threat is different: not resource exhaustion but
    # credential stuffing and mailbox flooding.
    login_attempts: int = field(default_factory=lambda: _env_int("SOLAR_LOGIN_RATE_LIMIT", 10))
    login_window_s: int = field(default_factory=lambda: _env_int("SOLAR_LOGIN_RATE_WINDOW", 900))
    register_attempts: int = field(
        default_factory=lambda: _env_int("SOLAR_REGISTER_RATE_LIMIT", 5)
    )
    register_window_s: int = field(
        default_factory=lambda: _env_int("SOLAR_REGISTER_RATE_WINDOW", 3600)
    )
    # One verification mail every two minutes per account, per the architecture note.
    resend_window_s: int = field(default_factory=lambda: _env_int("SOLAR_RESEND_WINDOW", 120))

    @property
    def uses_default_secret(self) -> bool:
        return self.jwt_secret == _DEV_JWT_SECRET


@dataclass(frozen=True)
class OAuthProviderSettings:
    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass(frozen=True)
class OAuthSettings:
    """Google and GitHub sign-in.

    ``redirect_base`` is the API's own public origin; callback URLs are derived from it and
    must match what is registered with the provider exactly. The post-login hop back into
    the frontend is checked against ``allowed_redirects`` rather than trusted, because a
    callback that forwards to an attacker-supplied URL is an open redirect with a freshly
    minted session attached to it.
    """

    redirect_base: str = field(
        default_factory=lambda: _env_str(
            "OAUTH_REDIRECT_BASE", "http://127.0.0.1:8000"
        ).rstrip("/")
    )
    frontend_base: str = field(
        default_factory=lambda: _env_str(
            "SOLAR_FRONTEND_BASE", "http://localhost:3000"
        ).rstrip("/")
    )
    allowed_redirects: tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "SOLAR_OAUTH_ALLOWED_REDIRECTS", "http://localhost:3000,http://127.0.0.1:3000"
        )
    )

    google: OAuthProviderSettings = field(
        default_factory=lambda: OAuthProviderSettings(
            name="google",
            client_id=_env_str("GOOGLE_OAUTH_CLIENT_ID", ""),
            client_secret=_env_str("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scope="openid email profile",
        )
    )
    github: OAuthProviderSettings = field(
        default_factory=lambda: OAuthProviderSettings(
            name="github",
            client_id=_env_str("GITHUB_OAUTH_CLIENT_ID", ""),
            client_secret=_env_str("GITHUB_OAUTH_CLIENT_SECRET", ""),
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            scope="read:user user:email",
        )
    )

    def provider(self, name: str) -> OAuthProviderSettings | None:
        return {"google": self.google, "github": self.github}.get(name)

    def callback_url(self, provider: str) -> str:
        return f"{self.redirect_base}/api/auth/oauth/{provider}/callback"

    @property
    def configured_providers(self) -> tuple[str, ...]:
        return tuple(p.name for p in (self.google, self.github) if p.configured)


@dataclass(frozen=True)
class EmailSettings:
    """Transactional email.

    The provider is chosen by name and never hard-coded into a call site: a verification
    message is addressed to a person, and which vendor carries it is an operational
    detail. ``console`` prints the message and is the development default; ``memory``
    captures it for tests.
    """

    provider: str = field(default_factory=lambda: _env_str("EMAIL_PROVIDER", "console").lower())
    api_key: str = field(default_factory=lambda: _env_str("EMAIL_PROVIDER_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: _env_str("EMAIL_PROVIDER_API_SECRET", ""))
    from_address: str = field(
        default_factory=lambda: _env_str("EMAIL_FROM_ADDRESS", "no-reply@helios.local")
    )
    from_name: str = field(default_factory=lambda: _env_str("EMAIL_FROM_NAME", "Helios"))
    region: str = field(default_factory=lambda: _env_str("EMAIL_PROVIDER_REGION", "us-east-1"))
    timeout_s: float = field(default_factory=lambda: _env_float("EMAIL_TIMEOUT_S", 10.0))
    # Where the links inside those messages point: the frontend, not the API.
    link_base: str = field(
        default_factory=lambda: _env_str(
            "SOLAR_FRONTEND_BASE", "http://localhost:3000"
        ).rstrip("/")
    )


@dataclass(frozen=True)
class ObservabilitySettings:
    """Logs, metrics, traces and error reporting."""

    json_logs: bool = field(default_factory=lambda: _env_bool("SOLAR_JSON_LOGS", False))
    instance_id: str = field(
        default_factory=lambda: _env_first("", "SOLAR_INSTANCE_ID", "HOSTNAME", "COMPUTERNAME")
        or "local"
    )
    metrics_enabled: bool = field(default_factory=lambda: _env_bool("SOLAR_METRICS_ENABLED", True))
    metrics_path: str = field(default_factory=lambda: _env_str("SOLAR_METRICS_PATH", "/api/metrics"))
    tracing_enabled: bool = field(default_factory=lambda: _env_bool("SOLAR_TRACING_ENABLED", False))
    otlp_endpoint: str = field(default_factory=lambda: _env_str("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    service_name: str = field(default_factory=lambda: _env_str("OTEL_SERVICE_NAME", "helios-backend"))
    sentry_dsn: str = field(default_factory=lambda: _env_str("SENTRY_DSN", ""))
    sentry_traces_sample_rate: float = field(
        default_factory=lambda: _env_float("SENTRY_TRACES_SAMPLE_RATE", 0.05)
    )
    release: str = field(default_factory=lambda: _env_str("SOLAR_RELEASE", "dev"))
    # Shutdown budget. Long enough for a console analysis to finish, short enough that a
    # rolling deployment does not stall on one wedged worker.
    shutdown_grace_s: int = field(default_factory=lambda: _env_int("SOLAR_SHUTDOWN_GRACE_S", 45))


@dataclass(frozen=True)
class ServerSettings:
    """The HTTP surface.

    Unlike the older sections above, every field here is read through a
    ``default_factory`` — that is, when a ``Settings`` object is *constructed* rather than
    when this module is *imported*. In a deployment the two are indistinguishable, because
    the environment is set before the process starts. It matters because
    :meth:`Settings.production_problems` inspects ``cors_origins``, and a safety check that
    cannot see the configuration it is meant to be checking is not a safety check.
    """

    host: str = field(default_factory=lambda: _env_str("SOLAR_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("SOLAR_PORT", 8000))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: _env_csv(
            "SOLAR_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        )
    )
    # General API rate limit, enforced in Redis so that it is one budget per client across
    # every backend replica rather than one budget per replica. It stops a single client
    # from monopolising the training workers.
    rate_limit_requests: int = field(default_factory=lambda: _env_int("SOLAR_RATE_LIMIT", 60))
    rate_limit_window_s: int = field(default_factory=lambda: _env_int("SOLAR_RATE_WINDOW", 60))
    log_level: str = field(default_factory=lambda: _env_str("SOLAR_LOG_LEVEL", "INFO"))
    # How many proxy hops in front of this process are ours. X-Forwarded-For is a list a
    # client can prepend to, so the trustworthy entry is counted from the right-hand end;
    # taking the leftmost would let anyone spoof their rate-limit identity with a header.
    trusted_proxy_hops: int = field(
        default_factory=lambda: _env_int("SOLAR_TRUSTED_PROXY_HOPS", 0)
    )


@dataclass(frozen=True)
class Settings:
    app_name: str = "Helios — Solar Intelligence Platform"
    version: str = "2.0.0"
    # development | test | production. Selects how strict startup validation is.
    environment: str = field(
        default_factory=lambda: _env_str("SOLAR_ENV", "development").strip().lower()
    )
    data: DataSourceSettings = field(default_factory=DataSourceSettings)
    cache: CacheSettings = field(default_factory=CacheSettings)
    store: StoreSettings = field(default_factory=StoreSettings)
    limits: ValidationLimits = field(default_factory=ValidationLimits)
    modelling: ModellingDefaults = field(default_factory=ModellingDefaults)
    server: ServerSettings = field(default_factory=ServerSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    redis: RedisSettings = field(default_factory=RedisSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    oauth: OAuthSettings = field(default_factory=OAuthSettings)
    email: EmailSettings = field(default_factory=EmailSettings)
    observability: ObservabilitySettings = field(default_factory=ObservabilitySettings)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    def ensure_directories(self) -> None:
        self.cache.directory.mkdir(parents=True, exist_ok=True)
        self.store.directory.mkdir(parents=True, exist_ok=True)

    def production_problems(self) -> list[str]:
        """Configuration that is fine on a laptop and unacceptable in production.

        Returned rather than raised so the caller decides what to do with it: startup
        aborts on this list, while the readiness endpoint reports it. Every entry names a
        way the deployment would either lose shared state or leak a credential.
        """
        problems: list[str] = []

        if self.database.is_sqlite:
            problems.append(
                "DATABASE_URL still points at SQLite. Estimates, experiments and accounts "
                "would live on one container's disk, so backend replicas would not share "
                "them. Point it at PostgreSQL (through PgBouncer)."
            )
        if self.redis.is_memory:
            problems.append(
                "REDIS_URL is the in-process stand-in. Rate limits, OAuth state and "
                "refresh-token revocation would be per-process, so a client could evade a "
                "limit by being routed to another replica and an OAuth callback landing on "
                "a different replica would fail. Point it at Redis."
            )
        if self.auth.uses_default_secret:
            problems.append(
                "JWT_SECRET is the built-in development value. Anyone with a copy of this "
                "source could mint valid access tokens. Set a random secret of at least 32 "
                "bytes."
            )
        elif len(self.auth.jwt_secret) < 32:
            problems.append("JWT_SECRET is shorter than 32 characters.")
        if not self.auth.cookie_secure:
            problems.append(
                "SOLAR_COOKIE_SECURE is off, so the refresh cookie would be sent over "
                "plaintext HTTP."
            )
        if self.email.provider in {"console", "memory"}:
            problems.append(
                f"EMAIL_PROVIDER is '{self.email.provider}', which does not deliver mail. "
                "Nobody could verify an address or reset a password. Configure a real "
                "provider."
            )
        if "*" in self.server.cors_origins:
            problems.append(
                "SOLAR_CORS_ORIGINS contains '*'. Credentialed requests require an exact "
                "origin allowlist."
            )
        if self.observability.tracing_enabled and not self.observability.otlp_endpoint:
            problems.append("Tracing is enabled but OTEL_EXPORTER_OTLP_ENDPOINT is unset.")
        return problems


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_directories()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings so the next call re-reads the environment.

    For tests and for the handful of scripts that need to run against a different
    database than the ambient environment names. Not used at runtime.
    """
    global _settings
    _settings = None
