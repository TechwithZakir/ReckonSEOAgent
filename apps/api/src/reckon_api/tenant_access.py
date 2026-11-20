from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from reckon_core.repositories import SqlAlchemyMembershipRepository
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    TenantAccessDenied,
    TenantAccessService,
    TenantContext,
)


def resolve_organization_access(
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    session: Session,
) -> TenantContext:
    access = TenantAccessService(SqlAlchemyMembershipRepository(session))
    try:
        return access.resolve(principal, organization_id)
    except TenantAccessDenied as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        ) from error
