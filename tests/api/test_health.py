import asyncio
from collections.abc import Iterator
from unittest.mock import Mock
from uuid import UUID

import httpx
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reckon_api.config import Settings
from reckon_api.dependencies import get_database_session
from reckon_api.main import create_app


def test_liveness_returns_typed_success_response() -> None:
    async def get_liveness() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=create_app(Settings(_env_file=None, environment="test"))
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/health/live")

    response = asyncio.run(get_liveness())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    request_id = response.headers["x-request-id"]
    assert str(UUID(request_id)) == request_id


def test_readiness_reports_unconfigured_database() -> None:
    async def get_readiness() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=create_app(Settings(_env_file=None, environment="test"))
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/health/ready")

    response = asyncio.run(get_readiness())

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is not configured."}


def test_readiness_reports_database_outage_without_leaking_driver_error() -> None:
    async def get_readiness() -> httpx.Response:
        app = create_app(Settings(_env_file=None, environment="test"))
        session = Mock(spec=Session)
        session.execute.side_effect = OperationalError(
            "SELECT 1",
            {},
            ConnectionError("private connection detail"),
        )

        def failing_session() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_database_session] = failing_session
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/health/ready")

    response = asyncio.run(get_readiness())

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable."}
    assert "private connection detail" not in response.text
