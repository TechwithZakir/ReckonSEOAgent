from datetime import datetime, timezone
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from reckon_api.dependencies import (
    get_authenticated_principal,
    get_database_session,
)
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.repositories import (
    IdempotencyConflict,
    SqlAlchemyCrawlRepository,
    SqlAlchemyMembershipRepository,
    SqlAlchemyOrganizationRepository,
    utc_day,
)
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantAccessService,
)
from reckon_core.permissions import OrganizationPermission, require_permission

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


class CreateOrganizationRequest(BaseModel):
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=200,
        ),
    ]


class OrganizationContextResponse(BaseModel):
    organization_id: UUID
    role: OrganizationRole


class OrganizationSummary(BaseModel):
    organization_id: UUID
    name: str
    role: OrganizationRole


class OrganizationPage(BaseModel):
    items: list[OrganizationSummary]
    next_cursor: UUID | None


class OrganizationMember(BaseModel):
    user_id: UUID
    email: str | None
    role: OrganizationRole


class OrganizationMemberPage(BaseModel):
    items: list[OrganizationMember]
    next_cursor: UUID | None


class CrawlUsageResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    used: int
    limit: int
    remaining: int


@router.get("", response_model=OrganizationPage)
def list_organizations(
    response: Response,
    after: UUID | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> OrganizationPage:
    rows, cursor = SqlAlchemyOrganizationRepository(session).list_for_user(
        principal.user_id, limit, after
    )
    response.headers["Cache-Control"] = "no-store"
    return OrganizationPage(
        items=[
            OrganizationSummary(organization_id=org_id, name=name, role=role)
            for org_id, name, role in rows
        ],
        next_cursor=cursor,
    )


@router.get(
    "/{organization_id}/members",
    response_model=OrganizationMemberPage,
)
def list_organization_members(
    response: Response,
    organization_id: UUID,
    after: UUID | None = None,
    limit: int = Query(default=25, ge=1, le=50),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> OrganizationMemberPage:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.MEMBER_VIEW)
    except TenantAccessDenied:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.")
    try:
        rows, cursor = SqlAlchemyOrganizationRepository(session).list_members(context, limit, after)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.") from error
    response.headers["Cache-Control"] = "no-store"
    return OrganizationMemberPage(
        items=[OrganizationMember(user_id=user_id, email=email, role=role) for user_id, email, role in rows],
        next_cursor=cursor,
    )


@router.get(
    "/{organization_id}/crawl-usage",
    response_model=CrawlUsageResponse,
)
def get_crawl_usage(
    request: Request,
    response: Response,
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> CrawlUsageResponse:
    context = resolve_organization_access(principal, organization_id, session)
    start, end = utc_day(datetime.now(timezone.utc))
    used = SqlAlchemyCrawlRepository(session).count_for_period(
        context.organization_id, start, end
    )
    limit = request.app.state.settings.crawl_daily_limit
    response.headers["Cache-Control"] = "no-store"
    return CrawlUsageResponse(
        period_start=start,
        period_end=end,
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
    )


@router.get(
    "/{organization_id}/context",
    response_model=OrganizationContextResponse,
)
def get_organization_context(
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> OrganizationContextResponse:
    access = TenantAccessService(SqlAlchemyMembershipRepository(session))
    try:
        context = access.resolve(principal, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        ) from error

    return OrganizationContextResponse(
        organization_id=context.organization_id,
        role=context.role,
    )


@router.post(
    "",
    response_model=OrganizationContextResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    http_request: Request,
    request: CreateOrganizationRequest,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]{8,128}$",
        ),
    ],
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> OrganizationContextResponse:
    try:
        organization_id, role = SqlAlchemyOrganizationRepository(
            session
        ).create_for_owner(
            principal.user_id,
            request.name,
            idempotency_key,
            http_request.state.request_id,
        )
    except IdempotencyConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for a different request.",
        ) from error
    except TenantAccessDenied as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        ) from error
    session.commit()
    return OrganizationContextResponse(
        organization_id=organization_id,
        role=role,
    )
