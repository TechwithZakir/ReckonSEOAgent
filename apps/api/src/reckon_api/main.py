import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from reckon_api.routers.crawls import router as crawls_router
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import sessionmaker

from reckon_api.config import Settings
from reckon_api.native_mail import SmtpVerificationMailer
from reckon_api.routers.health import router as health_router
from reckon_api.routers.organizations import router as organizations_router
from reckon_api.routers.model_settings import router as model_settings_router
from reckon_api.routers.model_settings import usage_router as model_usage_router
from reckon_api.routers.native_auth import router as native_auth_router
from reckon_api.routers.platform import router as platform_router
from reckon_api.routers.organization_management import router as organization_management_router
from reckon_api.routers.mcp import router as mcp_router
from reckon_api.routers.cms import router as cms_router
from reckon_api.routers.plugin_tokens import router as plugin_tokens_router
from reckon_api.routers.seo_actions import router as seo_actions_router
from reckon_api.routers.websites import router as websites_router
from reckon_core.crawler import HomepageCrawler
from reckon_core.crawl_security import PublicDnsAddressResolver
from reckon_core.oidc import OidcTokenVerifier
from reckon_api.crawl_worker import CeleryCrawlQueue, create_celery_app
from pydantic import SecretStr
from reckon_core.action_executor import FixtureActionExecutor
from reckon_core.public_page_verifier import PublicPageVerifier
from reckon_core.wordpress_executor import WordPressActionExecutor


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()
    engine: Engine | None = None
    session_factory = None
    if app_settings.database_url is not None:
        engine = create_engine(
            app_settings.database_url.get_secret_value(),
            pool_pre_ping=True,
        )
        session_factory = sessionmaker(engine, expire_on_commit=False)

    if (
        app_settings.oidc_issuer is not None
        and app_settings.oidc_audience is not None
        and app_settings.oidc_jwks_url is not None
    ):
        token_verifier = OidcTokenVerifier(
            issuer=app_settings.oidc_issuer,
            audience=app_settings.oidc_audience,
            jwks_url=app_settings.oidc_jwks_url,
        )
    else:
        token_verifier = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.session_factory = session_factory
    app.state.token_verifier = token_verifier
    app.state.homepage_crawler = HomepageCrawler()
    app.state.crawl_queue = (
        CeleryCrawlQueue(create_celery_app(app_settings))
        if app_settings.crawl_worker_enabled
        else None
    )
    app.state.model_test_slots = asyncio.Semaphore(2)
    app.state.model_test_resolver = PublicDnsAddressResolver(timeout_seconds=2.0)
    app.state.model_test_transport = None
    app.state.cms_transport = None
    if app_settings.environment == "test":
        app.state.seo_action_executor = FixtureActionExecutor()
    elif app_settings.cms_wordpress_execution_enabled:
        if (
            app_settings.cms_wordpress_base_url is None
            or app_settings.cms_wordpress_username is None
            or app_settings.cms_wordpress_app_password is None
        ):
            raise RuntimeError("WordPress execution requires base URL, username and app password.")
        app.state.seo_action_executor = WordPressActionExecutor(
            app_settings.cms_wordpress_base_url,
            app_settings.cms_wordpress_username,
            SecretStr(app_settings.cms_wordpress_app_password.get_secret_value()),
        )
    else:
        app.state.seo_action_executor = None
    app.state.seo_action_verifier = (
        PublicPageVerifier()
        if app_settings.environment != "test" and app_settings.cms_public_verification_enabled
        else None
    )
    app.state.verification_mailer = (
        SmtpVerificationMailer(app_settings)
        if app_settings.smtp_host and app_settings.smtp_from and app_settings.web_public_origin
        else None
    )

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = uuid4()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        path = request.url.path
        if (
            ("/ai-settings" in path and path.startswith("/api/v1/organizations/"))
            or ("/ai-usage" in path and path.startswith("/api/v1/organizations/"))
            or path.startswith("/api/v1/mcp")
            or ("/cms/" in path and path.startswith("/api/v1/organizations/"))
            or path.startswith("/api/v1/auth/")
            or path.startswith("/api/v1/invitations")
            or (path.startswith("/api/v1/organizations/") and "/changes" in path)
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, error: RequestValidationError
    ) -> Response:
        route = request.scope.get("route")
        name = getattr(route, "name", "")
        if name == "put_model_settings":
            return JSONResponse(status_code=422, content={"detail": "Invalid AI settings."})
        if name.startswith("native_"):
            return JSONResponse(status_code=422, content={"detail": "Invalid authentication request."})
        return await request_validation_exception_handler(request, error)

    @app.exception_handler(OperationalError)
    async def handle_database_operational_error(
        _: Request,
        __: OperationalError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is unavailable."},
        )

    @app.exception_handler(InterfaceError)
    async def handle_database_interface_error(
        _: Request,
        __: InterfaceError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is unavailable."},
        )

    app.include_router(health_router)
    app.include_router(organizations_router)
    app.include_router(websites_router)
    app.include_router(crawls_router)
    app.include_router(model_settings_router)
    app.include_router(model_usage_router)
    app.include_router(native_auth_router)
    app.include_router(platform_router)
    app.include_router(organization_management_router)
    app.include_router(mcp_router)
    app.include_router(cms_router)
    app.include_router(seo_actions_router)
    app.include_router(plugin_tokens_router)
    return app


app = create_app()
