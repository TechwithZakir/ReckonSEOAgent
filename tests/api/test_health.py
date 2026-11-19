import asyncio

import httpx

from reckon_api.config import Settings
from reckon_api.main import create_app


def test_liveness_returns_typed_success_response() -> None:
    async def get_liveness() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(Settings(environment="test")))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/health/live")

    response = asyncio.run(get_liveness())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
