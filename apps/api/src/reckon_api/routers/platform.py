from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_core.persistence import (
    AuditEvent,
    NativeAccount,
    NativeSession,
    Organization,
    OrganizationMembership,
    PlatformAdministrator,
)
from reckon_core.tenancy import AuthenticatedPrincipal

router = APIRouter(prefix="/api/v1/platform", tags=["platform access"])


class PlatformAccessResponse(BaseModel):
    is_platform_admin: bool


class PlatformSummaryResponse(BaseModel):
    organization_count: int
    active_member_count: int
    native_account_count: int
    active_native_session_count: int


class PlatformAuditEventResponse(BaseModel):
    event_id: UUID
    organization_id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    request_id: UUID
    created_at: datetime


@router.get("/access", response_model=PlatformAccessResponse)
def platform_access(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> PlatformAccessResponse:
    response.headers["Cache-Control"] = "no-store"
    administrator = session.scalar(
        select(PlatformAdministrator.user_id).where(PlatformAdministrator.user_id == principal.user_id)
    )
    return PlatformAccessResponse(is_platform_admin=administrator is not None)


def _require_platform_admin(
    principal: AuthenticatedPrincipal,
    session: Session,
) -> None:
    administrator = session.scalar(
        select(PlatformAdministrator.user_id).where(
            PlatformAdministrator.user_id == principal.user_id
        )
    )
    if administrator is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access is required.",
        )


@router.get("/summary", response_model=PlatformSummaryResponse)
def platform_summary(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> PlatformSummaryResponse:
    _require_platform_admin(principal, session)
    now = datetime.now(timezone.utc)
    organization_count = session.scalar(select(func.count(Organization.id)))
    active_member_count = session.scalar(
        select(func.count()).select_from(OrganizationMembership).where(
            OrganizationMembership.is_active.is_(True)
        )
    )
    native_account_count = session.scalar(select(func.count(NativeAccount.user_id)))
    active_native_session_count = session.scalar(
        select(func.count(NativeSession.token_hash)).where(
            NativeSession.expires_at > now,
            NativeSession.revoked_at.is_(None),
        )
    )
    response.headers["Cache-Control"] = "no-store"
    return PlatformSummaryResponse(
        organization_count=int(organization_count or 0),
        active_member_count=int(active_member_count or 0),
        native_account_count=int(native_account_count or 0),
        active_native_session_count=int(active_native_session_count or 0),
    )


@router.get("/audit-events", response_model=list[PlatformAuditEventResponse])
def platform_audit_events(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[PlatformAuditEventResponse]:
    _require_platform_admin(principal, session)
    rows = session.scalars(
        select(AuditEvent)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    result: list[PlatformAuditEventResponse] = []
    for event in rows:
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        result.append(
            PlatformAuditEventResponse(
                event_id=event.id,
                organization_id=event.organization_id,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                request_id=event.request_id,
                created_at=created_at.astimezone(timezone.utc),
            )
        )
    return result
