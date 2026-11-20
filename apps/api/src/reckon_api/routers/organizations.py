from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from reckon_api.dependencies import (
    get_authenticated_principal,
    get_database_session,
)
from reckon_core.repositories import (
    IdempotencyConflict,
    SqlAlchemyMembershipRepository,
    SqlAlchemyOrganizationRepository,
)
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantAccessService,
)

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
