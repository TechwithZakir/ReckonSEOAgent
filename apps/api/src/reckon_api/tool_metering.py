"""FastAPI dependency that meters organization-scoped tool and action calls."""

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.tenancy import AuthenticatedPrincipal
from reckon_core.tool_metering import ToolCallBudgetExceeded, ToolCallMeter


def _call_name(request: Request) -> str:
    segments = request.url.path.split("/")
    if "tools" in segments[:-1]:
        return segments[segments.index("tools") + 1]
    if "seo-actions" in segments:
        suffix = segments[segments.index("seo-actions") + 2 :]
        return f"seo-actions.{request.method.lower()}.{suffix[0] if suffix else 'collection'}"
    if "advanced-audit" in segments:
        return "advanced-audit.post"
    if "fix-drafts" in segments:
        return "fix-drafts.post"
    return "unknown"


def meter_tool_call(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> None:
    """Meter every organization-scoped call against the daily cap (after authentication)."""
    raw_organization_id = request.path_params.get("organization_id")
    if raw_organization_id is None:
        return
    try:
        organization_id = UUID(str(raw_organization_id))
    except ValueError:
        return
    context = resolve_organization_access(principal, organization_id, session)
    try:
        ToolCallMeter(session).record(
            context,
            _call_name(request),
            request.state.request_id,
            request.app.state.settings.mcp_daily_tool_call_limit,
        )
    except ToolCallBudgetExceeded:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The organization has reached its daily tool-call limit.",
        ) from None
    session.commit()
