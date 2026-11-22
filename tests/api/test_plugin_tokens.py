import asyncio
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone


import httpx
from sqlalchemy import select

from reckon_core.persistence import AuditEvent, PluginToken
from test_seo_actions import action_api  # noqa: F401  (shared fixture)


def _run(app, work):
    async def go():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await work(client)

    return asyncio.run(go())


def test_plugin_token_is_scoped_to_its_org_tools_and_never_manages_tokens(action_api) -> None:  # noqa: F811
    app, factory, owner_token, viewer_token, organization_id, website_id = action_api
    base = f"/api/v1/organizations/{organization_id}/plugin-tokens"
    owner = {"Authorization": f"Bearer {owner_token}"}

    async def work(client):
        denied = await client.post(base, headers={"Authorization": f"Bearer {viewer_token}"},
                                   json={"label": "x"})
        assert denied.status_code == 403
        assert (await client.post(base, headers=owner, json={"label": "x", "scopes": ["bogus"]})
                ).status_code == 422
        assert (await client.post(base, headers=owner, json={"label": "x", "lifetime_days": 91})
                ).status_code == 422

        issued = await client.post(base, headers=owner, json={
            "label": "Claude plugin", "scopes": ["reckon.seo_action.approved.list"],
        })
        assert issued.status_code == 201
        body = issued.json()
        token = body["token"]
        assert token.startswith("rkpt_") and body["scopes"] == ["reckon.seo_action.approved.list"]
        plugin = {"Authorization": f"Bearer {token}"}
        tool = lambda org, name: f"/api/v1/mcp/organizations/{org}/tools/{name}/invoke"  # noqa: E731
        payload = {"website_id": str(website_id), "limit": 5}

        ok = await client.post(tool(organization_id, "reckon.seo_action.approved.list"),
                               headers=plugin, json=payload)
        assert ok.status_code == 200
        # Another tool, another organization, and token management are all refused.
        assert (await client.post(tool(organization_id, "reckon.seo_action.claim"),
                                  headers=plugin, json={"proposal_id": str(uuid4())})
                ).status_code == 401
        assert (await client.post(tool(uuid4(), "reckon.seo_action.approved.list"),
                                  headers=plugin, json=payload)).status_code == 401
        assert (await client.get(base, headers=plugin)).status_code == 401
        assert (await client.post(base, headers=plugin, json={"label": "self"})).status_code == 401

        listed = (await client.get(base, headers=owner)).json()
        assert [row["label"] for row in listed] == ["Claude plugin"]
        assert "token" not in listed[0] and listed[0]["last_used_at"] is not None

        revoked = await client.delete(f"{base}/{body['token_id']}", headers=owner)
        assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
        assert (await client.post(tool(organization_id, "reckon.seo_action.approved.list"),
                                  headers=plugin, json=payload)).status_code == 401
        assert (await client.delete(f"{base}/{uuid4()}", headers=owner)).status_code == 404

    _run(app, work)
    with factory() as session:
        stored = session.scalars(select(PluginToken)).all()
        assert len(stored) == 1 and len(stored[0].token_hash) == 64
        actions = {row.action for row in session.scalars(select(AuditEvent))}
        assert {"plugin_token.issued", "plugin_token.revoked"} <= actions


def test_expired_token_and_active_cap(action_api) -> None:  # noqa: F811
    app, factory, owner_token, _viewer, organization_id, website_id = action_api
    base = f"/api/v1/organizations/{organization_id}/plugin-tokens"
    owner = {"Authorization": f"Bearer {owner_token}"}

    async def work(client):
        first = (await client.post(base, headers=owner, json={"label": "a"})).json()
        with factory.begin() as session:
            row = session.scalar(select(PluginToken).where(PluginToken.id == UUID(first["token_id"])))
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        url = f"/api/v1/mcp/organizations/{organization_id}/tools/reckon.seo_action.approved.list/invoke"
        expired = await client.post(
            url, headers={"Authorization": f"Bearer {first['token']}"},
            json={"website_id": str(website_id)},
        )
        assert expired.status_code == 401
        for index in range(10):
            assert (await client.post(base, headers=owner, json={"label": f"t{index}"})
                    ).status_code == 201
        assert (await client.post(base, headers=owner, json={"label": "over"})).status_code == 422

    _run(app, work)
