import asyncio

import httpx
from fastapi import FastAPI

from reckon_api.main import create_app
from reckon_api.config import Settings


def test_mcp_tool_discovery_is_typed_and_read_only() -> None:
    app: FastAPI = create_app(Settings(_env_file=None, environment="test"))

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/api/v1/mcp/tools")

    response = asyncio.run(run())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == [
        {
            "name": "reckon.crawl.list",
            "read_only": True,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.crawl.schedule.list",
            "read_only": True,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.audit.list",
            "read_only": True,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.seo_action.propose",
            "read_only": False,
            "tenant_scoped": True,
            "proposal_only": True,
        },
        {
            "name": "reckon.crawl.start",
            "read_only": False,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.website.evidence.get",
            "read_only": True,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.engine.audit.get",
            "read_only": True,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.seo_action.approved.list",
            "read_only": True,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.seo_action.claim",
            "read_only": False,
            "tenant_scoped": True,
            "proposal_only": False,
        },
        {
            "name": "reckon.seo_action.report",
            "read_only": False,
            "tenant_scoped": True,
            "proposal_only": False,
        },
    ]
