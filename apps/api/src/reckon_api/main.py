from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
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
from reckon_api.routers.health import router as health_router
from reckon_api.routers.organizations import router as organizations_router
from reckon_api.routers.websites import router as websites_router
from reckon_core.crawler import HomepageCrawler
from reckon_core.oidc import OidcTokenVerifier


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

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = uuid4()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        return response

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
    return app


app = create_app()
