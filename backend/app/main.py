"""FastAPI application factory and lifespan management."""

import asyncio
import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.router import v1_router
from app.api.websocket.endpoint import router as ws_router
from app.config.constants import API_V1_PREFIX, APP_TITLE, APP_VERSION
from app.config.settings import Environment, get_settings
from app.core.exceptions import CVilWarError, RecordNotFoundError
from app.db import tenant as _tenant_filter  # noqa: F401  # registers do_orm_execute
from app.db.arq import close_arq_pool, init_arq_pool
from app.db.redis import close_redis_pool, init_redis_pool
from app.db.session import engine
from app.observability.logging import configure_logging

logger = structlog.get_logger(__name__)
settings = get_settings()


def metrics_authorized(cfg: object, authorization: str | None) -> bool:
    """Open in non-production; in production require a matching bearer token (fail-closed)."""
    if cfg.environment != Environment.PRODUCTION:  # type: ignore[attr-defined]
        return True
    token = cfg.metrics_token.get_secret_value()  # type: ignore[attr-defined]
    # Constant-time compare — the token is the only thing guarding /metrics in prod.
    return bool(token) and hmac.compare_digest(authorization or "", f"Bearer {token}")


def validate_production_settings(cfg: object) -> None:
    """Fail-closed at startup if production is misconfigured with insecure defaults.

    Mirrors the secrets-factory guard so a forgotten/placeholder secret can't silently ship
    (a default JWT key = trivial token forgery; a '*' credentialed CORS = any-origin access).
    """
    if cfg.environment != Environment.PRODUCTION:  # type: ignore[attr-defined]
        return
    problems: list[str] = []
    secret = cfg.auth.secret_key.get_secret_value()  # type: ignore[attr-defined]
    if secret in ("", "dev-insecure-change-me") or len(secret) < 16:
        problems.append("AUTH__SECRET_KEY must be a strong, non-default secret")
    if "*" in cfg.cors_origins:  # type: ignore[attr-defined]
        problems.append("CORS_ORIGINS must not contain '*' with credentialed CORS")
    storage = cfg.storage  # type: ignore[attr-defined]
    if storage.provider == "local" and storage.url_signing_secret.get_secret_value() == (
        "dev-insecure-change-me"
    ):
        problems.append("STORAGE__URL_SIGNING_SECRET must be set for local storage")
    if problems:
        raise RuntimeError("Invalid production configuration: " + "; ".join(problems))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown lifecycle."""
    # Startup
    configure_logging(settings.log_level, settings.environment.value)
    validate_production_settings(settings)  # fail fast on insecure prod config
    logger.info(
        "app_starting",
        version=APP_VERSION,
        environment=settings.environment.value,
    )

    # Schema is owned by Alembic — run `alembic upgrade head` before starting.
    logger.info("database_ready")

    await init_redis_pool(settings.redis_url)
    await init_arq_pool()

    yield

    # Shutdown
    await close_arq_pool()
    await close_redis_pool()
    await engine.dispose()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from app.observability.sentry import init_sentry

    init_sentry("api")  # no-op unless SENTRY_DSN is set

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != Environment.PRODUCTION else None,
        redoc_url="/redoc" if settings.environment != Environment.PRODUCTION else None,
    )

    # Security headers (defense-in-depth, independent of the reverse proxy).
    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if settings.environment == Environment.PRODUCTION:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Prometheus metrics: open in non-prod; in production require a bearer token
    # (fail-closed if METRICS_TOKEN is unset) so it isn't a public data leak.
    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        if not metrics_authorized(settings, request.headers.get("authorization")):
            return Response(status_code=401)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Exception handlers
    @app.exception_handler(CVilWarError)
    async def cvilwar_error_handler(
        request: Request,
        exc: CVilWarError,
    ) -> JSONResponse:
        """Convert domain exceptions to JSON error responses."""
        status_code = 500
        if isinstance(exc, RecordNotFoundError):
            status_code = 404
        elif exc.code.endswith("AUTH_ERROR"):
            status_code = 401
        elif exc.code.endswith("FORBIDDEN_ERROR"):
            status_code = 403
        elif exc.code.endswith("RATE_LIMIT"):
            status_code = 429
        elif exc.code.endswith("INTEGRITY_ERROR"):
            status_code = 409

        logger.warning(
            "domain_error",
            error_code=exc.code,
            message=exc.message,
            path=str(request.url),
        )

        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    # Routes
    app.include_router(v1_router, prefix=API_V1_PREFIX)
    app.include_router(ws_router)

    @app.get("/health")
    async def health_check(response: Response) -> dict[str, object]:
        """Readiness probe: verifies DB connectivity (hard) and reports everything else (soft).

        A dead database means the instance cannot serve, so it returns 503 — which lets a
        container healthcheck / uptime monitor detect it. Everything else (Redis, the LLM
        gateway, external job/comms APIs) degrades gracefully rather than failing the whole
        probe, but is still reported: a health check that only ever says "db: true" leaves an
        operator no way to tell "the app is up" from "the app is up and its actual
        dependencies — the LLM gateway, Reed, Adzuna — are configured and reachable".
        """
        from sqlalchemy import text

        from app.core.llm.discovery import discover as discover_llm_gateway
        from app.db.redis import is_redis_available
        from app.db.session import engine

        db_ok = True
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            db_ok = False
            logger.error("health_db_unavailable", error=str(exc))
        redis_ok = await is_redis_available()

        # `discover()` is cached (see core.llm.discovery) but a cold/expired cache means a
        # real network call with its own 8s budget — fine for a human clicking "Refresh
        # models", fatal for a machine-polled readiness probe: a slow gateway would make
        # /health itself slow, and a container orchestrator reading that as "unhealthy"
        # would restart a backend that was otherwise working fine. A short, health-specific
        # timeout bounds the worst case without touching discover()'s own contract. Skipped
        # entirely once the DB is already down — the probe is already failing; there is
        # nothing to gain from also waiting out a gateway check before returning 503.
        if db_ok:
            try:
                catalogue = await asyncio.wait_for(discover_llm_gateway(), timeout=2.0)
                llm_gateway = {"reachable": catalogue.reachable, "error": catalogue.error}
            except TimeoutError:
                llm_gateway = {"reachable": False, "error": "Gateway check timed out"}
        else:
            llm_gateway = {"reachable": False, "error": "Skipped — database is unavailable"}

        # Credential presence only, not a live probe — an external-API health check must not
        # itself become a source of flakiness (a slow or rate-limited third party would make
        # every readiness probe slow or fail) or leak whether a key happens to be valid right
        # now. "configured" is what an operator actually needs to diagnose "why is Reed not
        # returning results" without adding another network dependency to /health itself.
        settings = get_settings()
        external_apis = {
            "reed": bool(settings.reed_api_key.get_secret_value()),
            "adzuna": bool(
                settings.adzuna_app_id.get_secret_value()
                and settings.adzuna_app_key.get_secret_value()
            ),
            "exa": bool(settings.exa_api_key.get_secret_value()),
            "gmail": bool(
                settings.gmail_client_id.get_secret_value()
                and settings.gmail_client_secret.get_secret_value()
            ),
            "apollo": bool(settings.apollo_api_key.get_secret_value()),
        }

        if not db_ok:
            response.status_code = 503
        return {
            "status": "ok" if db_ok else "unavailable",
            "version": APP_VERSION,
            "db": db_ok,
            "redis": redis_ok,
            "llm_gateway": llm_gateway,
            "external_apis": external_apis,
        }

    return app


app = create_app()
