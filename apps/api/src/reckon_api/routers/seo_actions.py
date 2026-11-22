from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.tenant_access import resolve_organization_access
from reckon_api.tool_metering import meter_tool_call
from reckon_core.action_lifecycle import (
    ActionLifecycleConflict,
    SeoActionLifecycle,
)
from reckon_core.persistence import SeoActionProposal
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import AuthenticatedPrincipal, OrganizationRole, TenantAccessDenied


router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/seo-actions",
    tags=["SEO actions"],
    dependencies=[Depends(meter_tool_call)],
)


class ProposeSeoActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    website_id: UUID
    action_type: Literal[
        "meta_title",
        "meta_description",
        "canonical",
        "heading",
        "schema",
        "redirect",
        "internal_link",
        "other",
    ]
    target_url: Annotated[str, Field(min_length=1, max_length=2048)]
    target_version: Annotated[str, Field(min_length=1, max_length=64)]
    before_state: dict[str, str] = Field(default_factory=dict)
    proposed_state: dict[str, str] = Field(default_factory=dict)
    risk: Literal["low", "medium", "high"]
    reason: Annotated[str, Field(min_length=3, max_length=200)]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SeoActionResponse(BaseModel):
    proposal_id: UUID
    website_id: UUID
    action_type: str
    target_url: str
    target_version: str
    risk: Literal["low", "medium", "high"]
    status: Literal[
        "proposed",
        "approved",
        "rejected",
        "executing",
        "executed",
        "verified",
        "failed",
        "rolled_back",
    ]
    reason: str
    approval_hash: str
    before_state: dict[str, str]
    proposed_state: dict[str, str]
    executed_state: dict[str, str] | None
    verification_state: dict[str, str] | None
    rollback_state: dict[str, str] | None
    error_code: str | None
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None
    executed_at: datetime | None
    verified_at: datetime | None


def _response(proposal: SeoActionProposal) -> SeoActionResponse:
    def aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return SeoActionResponse(
        proposal_id=proposal.id,
        website_id=proposal.website_id,
        action_type=proposal.action_type,
        target_url=proposal.target_url,
        target_version=proposal.target_version,
        risk=proposal.risk,
        status=proposal.status,
        reason=proposal.reason,
        approval_hash=proposal.approval_hash,
        before_state=proposal.before_state,
        proposed_state=proposal.proposed_state,
        executed_state=proposal.executed_state,
        verification_state=proposal.verification_state,
        rollback_state=proposal.rollback_state,
        error_code=proposal.error_code,
        created_at=aware(proposal.created_at) or proposal.created_at,
        expires_at=aware(proposal.expires_at) or proposal.expires_at,
        approved_at=aware(proposal.approved_at),
        executed_at=aware(proposal.executed_at),
        verified_at=aware(proposal.verified_at),
    )


@router.post("", response_model=SeoActionResponse)
def propose_action(
    http_request: Request,
    organization_id: UUID,
    payload: ProposeSeoActionRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128,
               pattern=r"^[A-Za-z0-9._:-]{8,128}$"),
    ],
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> SeoActionResponse:
    context = resolve_organization_access(principal, organization_id, session)
    if payload.risk == "high" and context.role != OrganizationRole.OWNER:
        raise HTTPException(status_code=403, detail="Only owners can propose high-risk actions.")
    try:
        proposal = SeoActionLifecycle(session).propose(
            context=context,
            website_id=payload.website_id,
            action_type=payload.action_type,
            target_url=payload.target_url,
            target_version=payload.target_version,
            before_state=payload.before_state,
            proposed_state=payload.proposed_state,
            risk=payload.risk,
            reason=payload.reason,
            idempotency_key=idempotency_key,
            request_id=http_request.state.request_id,
        )
        session.commit()
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail="The idempotency key was used for a different action.") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization manager access is required.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    response = _response(proposal)
    return response


@router.get("", response_model=list[SeoActionResponse])
def list_actions(
    response: Response,
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[SeoActionResponse]:
    context = resolve_organization_access(principal, organization_id, session)
    rows = session.scalars(
        select(SeoActionProposal)
        .where(SeoActionProposal.organization_id == context.organization_id)
        .order_by(SeoActionProposal.created_at.desc(), SeoActionProposal.id.desc())
        .limit(100)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return [_response(row) for row in rows]


@router.post("/{proposal_id}/approve", response_model=SeoActionResponse)
def approve_action(
    organization_id: UUID,
    proposal_id: UUID,
    payload: ApprovalRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> SeoActionResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        proposal = SeoActionLifecycle(session).approve(
            context,
            proposal_id,
            payload.approval_hash,
            request.state.request_id,
        )
        session.commit()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ActionLifecycleConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization manager access is required.") from error
    return _response(proposal)


@router.post("/{proposal_id}/reject", response_model=SeoActionResponse)
def reject_action(
    organization_id: UUID,
    proposal_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> SeoActionResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        proposal = SeoActionLifecycle(session).reject(
            context,
            proposal_id,
            request.state.request_id,
        )
        session.commit()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ActionLifecycleConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization manager access is required.") from error
    return _response(proposal)


@router.post("/{proposal_id}/execute", response_model=SeoActionResponse)
def execute_action(
    http_request: Request,
    organization_id: UUID,
    proposal_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> SeoActionResponse:
    context = resolve_organization_access(principal, organization_id, session)
    executor = getattr(http_request.app.state, "seo_action_executor", None)
    if executor is None:
        raise HTTPException(
            status_code=503,
            detail="No confirmed staging CMS executor is configured. No external write was attempted.",
        )
    try:
        proposal = SeoActionLifecycle(session).execute(
            context,
            proposal_id,
            executor,
            http_request.state.request_id,
        )
        session.commit()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ActionLifecycleConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization manager access is required.") from error
    return _response(proposal)


@router.post("/{proposal_id}/rollback", response_model=SeoActionResponse)
def rollback_action(
    http_request: Request,
    organization_id: UUID,
    proposal_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> SeoActionResponse:
    context = resolve_organization_access(principal, organization_id, session)
    executor = getattr(http_request.app.state, "seo_action_executor", None)
    if executor is None:
        raise HTTPException(
            status_code=503,
            detail="No confirmed CMS executor is configured.",
        )
    try:
        proposal = SeoActionLifecycle(session).rollback(
            context,
            proposal_id,
            executor,
            http_request.state.request_id,
        )
        session.commit()
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ActionLifecycleConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization manager access is required.") from error
    return _response(proposal)
