from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.plugin_tokens import (
    ALLOWED_SCOPES,
    DEFAULT_SCOPES,
    PluginTokenError,
    PluginTokenRepository,
)
from reckon_core.tenancy import AuthenticatedPrincipal, TenantAccessDenied

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/plugin-tokens",
    tags=["Plugin tokens"],
)


class PluginTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    scopes: list[str] | None = Field(default=None, max_length=len(ALLOWED_SCOPES))
    lifetime_days: int = Field(default=30, ge=1, le=90)


class PluginTokenView(BaseModel):
    token_id: UUID
    label: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class PluginTokenIssued(PluginTokenView):
    token: str


def _view(row) -> dict:
    return {
        "token_id": row.id,
        "label": row.label,
        "scopes": list(row.scopes),
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "last_used_at": row.last_used_at,
    }


def _context(organization_id: UUID, principal: AuthenticatedPrincipal, session: Session):
    # Plugin tokens never reach this router (they are accepted only on MCP tool routes), so a
    # plugin can never mint or extend its own credentials.
    context = resolve_organization_access(principal, organization_id, session)
    return context


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Organization manager access is required.",
    )


@router.get("/scopes", response_model=dict[str, list[str]])
def list_scopes() -> dict[str, list[str]]:
    return {"allowed": sorted(ALLOWED_SCOPES), "default": list(DEFAULT_SCOPES)}


@router.post("", response_model=PluginTokenIssued, status_code=status.HTTP_201_CREATED)
def issue_token(
    http_request: Request,
    organization_id: UUID,
    payload: PluginTokenCreate,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> dict:
    context = _context(organization_id, principal, session)
    try:
        token, row = PluginTokenRepository(session).issue(
            context,
            payload.label,
            payload.scopes,
            payload.lifetime_days,
            http_request.state.request_id,
        )
        session.commit()
    except TenantAccessDenied:
        raise _forbidden() from None
    except PluginTokenError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {**_view(row), "token": token}


@router.get("", response_model=list[PluginTokenView])
def list_tokens(
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[dict]:
    context = _context(organization_id, principal, session)
    try:
        return [_view(row) for row in PluginTokenRepository(session).list(context)]
    except TenantAccessDenied:
        raise _forbidden() from None


@router.delete("/{token_id}", response_model=PluginTokenView)
def revoke_token(
    http_request: Request,
    organization_id: UUID,
    token_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> dict:
    context = _context(organization_id, principal, session)
    try:
        row = PluginTokenRepository(session).revoke(
            context, token_id, http_request.state.request_id
        )
        session.commit()
    except TenantAccessDenied:
        raise _forbidden() from None
    except LookupError:
        raise HTTPException(status_code=404, detail="Plugin token not found.") from None
    return _view(row)
