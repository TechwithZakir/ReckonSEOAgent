"""AI-drafted SEO fixes that become approval-gated proposals (never applied directly)."""

import asyncio
import hashlib
from datetime import timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.specialist_runtime import build_specialist_runtime, model_error_to_http
from reckon_api.tenant_access import resolve_organization_access
from reckon_api.tool_metering import meter_tool_call
from reckon_core.action_lifecycle import SeoActionLifecycle
from reckon_core.crawler import CrawlDisallowed, CrawlPolicyError, CrawlUnavailable
from reckon_core.fix_drafting import DraftField, FixDraftingAgent, page_context
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.persistence import Website
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import AuthenticatedPrincipal, TenantAccessDenied

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/websites/{website_id}/fix-drafts",
    tags=["AI fix drafts"],
    dependencies=[Depends(meter_tool_call)],
)


class FixDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["meta_title", "meta_description", "heading"]
    target_url: Annotated[str, Field(min_length=1, max_length=2048)]
    # Optional WordPress identity when the caller already resolved the post (REST execution).
    wp_type: Literal["posts", "pages"] | None = None
    wp_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,11}$")] | None = None
    wp_modified_gmt: Annotated[str, Field(min_length=1, max_length=64)] | None = None

    @model_validator(mode="after")
    def wordpress_identity_is_all_or_none(self) -> "FixDraftRequest":
        given = [self.wp_type, self.wp_id, self.wp_modified_gmt]
        if any(given) and not all(given):
            raise ValueError("wp_type, wp_id and wp_modified_gmt must be provided together.")
        return self


class FixDraftResponse(BaseModel):
    proposal_id: UUID
    status: Literal["proposed"]
    field: DraftField
    target_url: str
    before_value: str
    proposed_value: str
    rationale: str
    risk: Literal["low"]
    expires_at: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@router.post("", response_model=FixDraftResponse)
async def draft_fix(
    http_request: Request,
    response: Response,
    organization_id: UUID,
    website_id: UUID,
    payload: FixDraftRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128,
               pattern=r"^[A-Za-z0-9._:-]{8,128}$"),
    ],
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> FixDraftResponse:
    response.headers["Cache-Control"] = "no-store"
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
    except TenantAccessDenied:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Organization manager access is required."
        ) from None

    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.org_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
    website = session.scalar(
        select(Website).where(
            Website.organization_id == organization_id, Website.id == website_id
        )
    )
    if website is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Website not found.")
    if not website.is_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verify the website before drafting fixes.")
    parsed = urlsplit(payload.target_url)
    if (parsed.hostname or "").lower() != website.host.lower():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The page must belong to the selected website."
        )

    crawler = http_request.app.state.homepage_crawler
    try:
        snapshot = await asyncio.to_thread(
            crawler.snapshot_page, website.scheme, website.host, payload.target_url
        )
    except CrawlDisallowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "robots.txt does not allow Reckon to read that page."
        ) from None
    except CrawlPolicyError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That page cannot be read under the crawl policy."
        ) from None
    except CrawlUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The page could not be fetched right now."
        ) from None
    if snapshot.status != "fetched":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That URL did not return an HTML page."
        )
    page = page_context(payload.field, snapshot)

    runtime = build_specialist_runtime(
        http_request, session, context,
        max_input_tokens=24576, max_output_tokens=400, use_agent_budget=True,
    )
    task_id = uuid5(
        organization_id,
        "specialist:fix-drafting:"
        f"{website_id}:{payload.field}:{hashlib.sha256(snapshot.url.encode()).hexdigest()}:"
        f"{idempotency_key}",
    )
    agent = FixDraftingAgent(
        runtime.factory,
        Path(__file__).resolve().parents[5] / "skills",
        runtime.gateway,
        runtime.provider,
        runtime.model,
    )
    try:
        async with asyncio.timeout(16.0):
            result = await agent.draft(
                context, website.host, payload.field, page, task_id,
                http_request.state.request_id, idempotency_key,
            )
    except TenantAccessDenied:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization or website not found.") from None
    except Exception as error:  # noqa: BLE001 - mapped below, re-raised if unknown
        mapped = model_error_to_http(error)
        if mapped is None:
            raise
        raise mapped from None
    if result.status == "unknown":
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The provider response could not be verified; charges may be unknown.",
        )
    if result.status != "completed" or result.value is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The AI draft failed Reckon's safety checks and was discarded. Try again.",
        )

    before = page.current_value or ""
    before_state = {"value": before}
    if payload.wp_type and payload.wp_id and payload.wp_modified_gmt:
        before_state.update({"wp_type": payload.wp_type, "wp_id": payload.wp_id})
        target_version = payload.wp_modified_gmt
    else:
        fingerprint = hashlib.sha256(
            "\x1f".join((page.current_value or "", page.title or "", page.h1 or "")).encode()
        ).hexdigest()[:16]
        target_version = f"page:{fingerprint}"
    reason = f"AI draft ({payload.field}): {result.rationale or 'fits the page content'}"[:200]
    try:
        proposal = SeoActionLifecycle(session).propose(
            context=context,
            website_id=website_id,
            action_type=payload.field,
            target_url=snapshot.url,
            target_version=target_version,
            before_state=before_state,
            proposed_state={"value": result.value},
            risk="low",
            reason=reason,
            idempotency_key=f"draft-{task_id.hex}",
            request_id=http_request.state.request_id,
        )
        session.commit()
    except IdempotencyConflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This draft was already proposed differently."
        ) from None
    except TenantAccessDenied:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Organization manager access is required."
        ) from None
    except (LookupError, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    expires = proposal.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return FixDraftResponse(
        proposal_id=proposal.id,
        status="proposed",
        field=payload.field,
        target_url=snapshot.url,
        before_value=before,
        proposed_value=result.value,
        rationale=result.rationale or "",
        risk="low",
        expires_at=expires.isoformat(),
        input_tokens=result.usage.input_tokens if result.usage else None,
        output_tokens=result.usage.output_tokens if result.usage else None,
    )
