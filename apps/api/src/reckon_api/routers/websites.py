from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from reckon_api.dependencies import (
    get_authenticated_principal,
    get_database_session,
)
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.persistence import Website
from reckon_core.dns import (
    DnsTxtLookup,
    DnsTxtLookupUnavailable,
    PublicDnsTxtResolver,
)
from reckon_core.repositories import (
    IdempotencyConflict,
    SqlAlchemyWebsiteRepository,
    WebsiteAlreadyExists,
    WebsiteNotFound,
)
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantContext,
)
from reckon_core.websites import (
    InvalidWebsiteUrl,
    has_website_verification_record,
    normalize_website_url,
    website_verification_record_name,
    website_verification_record_value,
)
from reckon_core.permissions import OrganizationPermission, require_permission

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/websites",
    tags=["websites"],
)


class CreateWebsiteRequest(BaseModel):
    url: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
    ]


class WebsiteResponse(BaseModel):
    website_id: UUID
    origin: str
    verification_status: Literal["pending", "verified"]
    dns_txt_name: str
    dns_txt_value: str | None


class WebsiteVerificationResponse(BaseModel):
    website_id: UUID
    verification_status: Literal["verified"]


def _require_permission(context: TenantContext, permission: OrganizationPermission) -> None:
    try:
        require_permission(context.role, permission)
    except TenantAccessDenied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization administrator access is required.",
        )


def _stored_website_response(
    website: Website,
    include_token: bool,
) -> WebsiteResponse:
    return WebsiteResponse(
        website_id=website.id,
        origin=f"{website.scheme}://{website.host}",
        verification_status="verified" if website.is_verified else "pending",
        dns_txt_name=website_verification_record_name(website.host),
        dns_txt_value=(
            website_verification_record_value(website.verification_token)
            if include_token and not website.is_verified
            else None
        ),
    )


@router.get("", response_model=list[WebsiteResponse])
def list_websites(
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[WebsiteResponse]:
    context = resolve_organization_access(principal, organization_id, session)
    include_token = context.role in {
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
    }
    websites = SqlAlchemyWebsiteRepository(session).list_for_organization(
        context.organization_id
    )
    return [
        _stored_website_response(website, include_token)
        for website in websites
    ]


@router.post(
    "",
    response_model=WebsiteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_website(
    http_request: Request,
    organization_id: UUID,
    request: CreateWebsiteRequest,
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
) -> WebsiteResponse:
    context = resolve_organization_access(principal, organization_id, session)
    _require_permission(context, OrganizationPermission.WEBSITE_CREATE)
    try:
        normalized = normalize_website_url(request.url)
    except InvalidWebsiteUrl as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    repository = SqlAlchemyWebsiteRepository(session)
    try:
        website = repository.create(
            organization_id=context.organization_id,
            actor_user_id=principal.user_id,
            scheme=normalized.scheme,
            host=normalized.host,
            idempotency_key=idempotency_key,
            request_id=http_request.state.request_id,
        )
    except IdempotencyConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for a different request.",
        ) from error
    except WebsiteAlreadyExists as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Website already exists in this organization.",
        ) from error
    except TenantAccessDenied as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        ) from error
    except WebsiteNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found.",
        ) from error
    session.commit()

    return _stored_website_response(website, include_token=True)


@router.post(
    "/{website_id}/verify",
    response_model=WebsiteVerificationResponse,
)
def verify_website(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> WebsiteVerificationResponse:
    context = resolve_organization_access(principal, organization_id, session)
    _require_permission(context, OrganizationPermission.WEBSITE_VERIFY)
    repository = SqlAlchemyWebsiteRepository(session)
    try:
        website = repository.get_for_verification(
            context.organization_id,
            website_id,
        )
    except WebsiteNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found.",
        ) from error

    if website.is_verified:
        return WebsiteVerificationResponse(
            website_id=website.id,
            verification_status="verified",
        )

    resolver: DnsTxtLookup = getattr(
        http_request.app.state,
        "dns_txt_resolver",
        None,
    ) or PublicDnsTxtResolver()
    record_name = website_verification_record_name(website.host)
    try:
        records = resolver.records(record_name)
    except DnsTxtLookupUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DNS verification is temporarily unavailable.",
        ) from error

    if not has_website_verification_record(records, website.verification_token):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The expected DNS TXT verification record was not found.",
        )

    website = repository.mark_verified(
        website,
        actor_user_id=principal.user_id,
        request_id=http_request.state.request_id,
    )
    session.commit()
    return WebsiteVerificationResponse(
        website_id=website.id,
        verification_status="verified",
    )
