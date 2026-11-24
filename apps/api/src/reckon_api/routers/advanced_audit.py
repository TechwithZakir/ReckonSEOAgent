"""Advanced audit of a tenant's verified website (same engine as the public audit)."""

import asyncio
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.routers.public_audit import PublicAuditResponse
from reckon_api.tenant_access import resolve_organization_access
from reckon_api.tool_metering import meter_tool_call
from reckon_core.persistence import Website
from reckon_core.public_audit import PublicAuditTargetError, PublicAuditUnavailable, run_public_audit
from reckon_core.tenancy import AuthenticatedPrincipal

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/websites/{website_id}/advanced-audit",
    tags=["Advanced audit"],
    dependencies=[Depends(meter_tool_call)],
)


@router.post("", response_model=PublicAuditResponse)
async def advanced_audit(
    http_request: Request,
    response: Response,
    organization_id: UUID,
    website_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> PublicAuditResponse:
    response.headers["Cache-Control"] = "no-store"
    context = resolve_organization_access(principal, organization_id, session)
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.org_id', :organization_id, true)"),
            {"organization_id": str(context.organization_id)},
        )
    website = session.scalar(
        select(Website).where(
            Website.organization_id == context.organization_id, Website.id == website_id
        )
    )
    if website is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Website not found.")
    if not website.is_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verify the website before running an audit.")
    host, scheme = website.host, website.scheme
    session.rollback()  # release the connection before the slow crawl
    slots = getattr(http_request.app.state, "advanced_audit_slots", None)
    if slots is None:
        slots = http_request.app.state.advanced_audit_slots = asyncio.Semaphore(3)
    if slots.locked():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The audit service is busy. Try again in a minute."
        )
    async with slots:
        try:
            report = await run_in_threadpool(
                run_public_audit, http_request.app.state.homepage_crawler,
                f"{scheme}://{host}", 5, False,
            )
        except PublicAuditTargetError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
        except PublicAuditUnavailable as error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    return PublicAuditResponse(**asdict(report), cached=False)
