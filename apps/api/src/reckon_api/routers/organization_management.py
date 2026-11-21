from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.native_mail import EmailDeliveryUnavailable, VerificationMailer
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.organization_management import (
    InvitationUnavailable, OrganizationChangeConflict, OrganizationManagement,
)
from reckon_core.persistence import Organization, OrganizationChange
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import AuthenticatedPrincipal, OrganizationRole, TenantAccessDenied

def _require_secure_transport(request: Request) -> None:
    if request.url.scheme == "https" or request.app.state.settings.environment == "test":
        return
    if (
        request.app.state.settings.environment == "local"
        and request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
    ):
        return
    raise HTTPException(status_code=400, detail="HTTPS is required for organization management.")


router = APIRouter(
    prefix="/api/v1", tags=["organization management"],
    dependencies=[Depends(_require_secure_transport)],
)


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["invite", "role_change"]
    role: OrganizationRole
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
    user_id: UUID | None = None
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)] | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "ChangeRequest":
        if self.action == "invite" and (self.email is None or self.user_id is not None):
            raise ValueError("An invitation requires an email address.")
        if self.action == "role_change" and (self.user_id is None or self.email is not None):
            raise ValueError("A role change requires a member.")
        return self


class ChangeResponse(BaseModel):
    id: UUID
    action: Literal["invite", "role_change"]
    role: OrganizationRole
    reason: str
    user_id: UUID | None
    email: str | None
    approval_hash: str
    expires_at: str
    approved: bool


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ApprovalResponse(BaseModel):
    approved: bool
    invitation_id: UUID | None
    notification_status: Literal["not_applicable", "unconfirmed", "smtp_accepted"]


class InvitationSummary(BaseModel):
    invitation_id: UUID
    organization_id: UUID
    organization_name: str
    role: OrganizationRole
    expires_at: str


class InvitationAccepted(BaseModel):
    organization_id: UUID
    role: OrganizationRole


class RenameOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]


class OrganizationProfileResponse(BaseModel):
    organization_id: UUID
    name: str
    role: OrganizationRole


def _change_response(change: OrganizationChange) -> ChangeResponse:
    return ChangeResponse(
        id=change.id, action=change.action, role=change.role, reason=change.reason,
        user_id=change.target_user_id, email=change.email, approval_hash=change.approval_hash,
        expires_at=change.expires_at.isoformat(), approved=change.approved_at is not None,
    )


@router.post("/organizations/{organization_id}/changes", response_model=ChangeResponse)
def propose_change(
    organization_id: UUID, payload: ChangeRequest, response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128,
                                           pattern=r"^[A-Za-z0-9._:-]{8,128}$")],
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> ChangeResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        change = OrganizationManagement(session).propose(
            context, payload.action, payload.role, payload.reason, idempotency_key, payload.user_id, payload.email,
        )
        result = _change_response(change)
        session.commit()
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="This role cannot manage the requested membership.") from error
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail="The idempotency key was used for another request.") from error
    except OrganizationChangeConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/organizations/{organization_id}/changes/{change_id}/approve", response_model=ApprovalResponse)
def approve_change(
    organization_id: UUID, change_id: UUID, payload: ApprovalRequest,
    request: Request, response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> ApprovalResponse:
    context = resolve_organization_access(principal, organization_id, session)
    service = OrganizationManagement(session)
    try:
        _, invitation, newly_approved = service.approve(
            context, change_id, payload.approval_hash, request.state.request_id,
        )
        mailer: VerificationMailer | None = request.app.state.verification_mailer
        if invitation is not None and newly_approved and mailer is None:
            raise HTTPException(status_code=503, detail="Invitation email is not configured.")
        org_name = session.scalar(select(Organization.name).where(Organization.id == organization_id))
        if org_name is None:
            raise TenantAccessDenied
        invite_id = invitation.id if invitation else None
        recipient = invitation.email if invitation else None
        delivery = invitation.delivery_state if invitation else "not_applicable"
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(status_code=403, detail="This role cannot manage the requested membership.") from error
    except OrganizationChangeConflict as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    if invitation is not None and newly_approved and recipient is not None and mailer is not None:
        try:
            mailer.send_organization_invitation(recipient, org_name)
        except EmailDeliveryUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail="Invitation created, but email delivery could not be confirmed. Do not retry blindly.",
            ) from error
        service.record_notification(organization_id, invitation.id, "smtp_accepted")
        session.commit()
        delivery = "smtp_accepted"
    response.headers["Cache-Control"] = "no-store"
    return ApprovalResponse(approved=True, invitation_id=invite_id, notification_status=delivery)


@router.patch("/organizations/{organization_id}/profile", response_model=OrganizationProfileResponse)
def rename_organization(
    organization_id: UUID,
    payload: RenameOrganizationRequest,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> OrganizationProfileResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        organization = OrganizationManagement(session).rename(
            context,
            request.state.request_id,
            payload.name,
        )
        session.commit()
    except TenantAccessDenied as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot manage the organization profile.",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return OrganizationProfileResponse(
        organization_id=organization.id,
        name=organization.name,
        role=context.role,
    )


@router.get("/invitations", response_model=list[InvitationSummary])
def list_invitations(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[InvitationSummary]:
    rows = OrganizationManagement(session).incoming(principal)
    response.headers["Cache-Control"] = "no-store"
    return [
        InvitationSummary(
            invitation_id=invite.id, organization_id=invite.organization_id,
            organization_name=name, role=invite.role, expires_at=invite.expires_at.isoformat(),
        ) for invite, name in rows
    ]


@router.post("/invitations/{invitation_id}/accept", response_model=InvitationAccepted)
def accept_invitation(
    invitation_id: UUID, request: Request, response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> InvitationAccepted:
    try:
        context = OrganizationManagement(session).accept(principal, invitation_id, request.state.request_id)
        session.commit()
    except InvitationUnavailable as error:
        session.rollback()
        raise HTTPException(status_code=404, detail="Invitation is unavailable.") from error
    response.headers["Cache-Control"] = "no-store"
    return InvitationAccepted(organization_id=context.organization_id, role=context.role)
