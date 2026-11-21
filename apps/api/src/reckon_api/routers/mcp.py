from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.repositories import SqlAlchemyCrawlRepository
from reckon_core.tenancy import AuthenticatedPrincipal, TenantAccessDenied


router = APIRouter(prefix="/api/v1/mcp", tags=["MCP"])


McpToolName = Literal[
    "reckon.crawl.list",
    "reckon.crawl.schedule.list",
]


class McpToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    website_id: UUID
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class McpTool(BaseModel):
    name: McpToolName
    read_only: bool
    tenant_scoped: bool


class McpInvokeResponse(BaseModel):
    tool: McpToolName
    result: list[dict[str, object]]


@router.get("/tools", response_model=list[McpTool])
def list_mcp_tools() -> list[McpTool]:
    return [
        McpTool(
            name="reckon.crawl.list",
            read_only=True,
            tenant_scoped=True,
        ),
        McpTool(
            name="reckon.crawl.schedule.list",
            read_only=True,
            tenant_scoped=True,
        ),
    ]


@router.post(
    "/organizations/{organization_id}/tools/{tool_name}/invoke",
    response_model=McpInvokeResponse,
)
def invoke_mcp_tool(
    organization_id: UUID,
    tool_name: McpToolName,
    payload: McpToolRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> McpInvokeResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.CRAWL_VIEW)
    except TenantAccessDenied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization crawl access is required.",
        ) from None

    repository = SqlAlchemyCrawlRepository(session)
    if tool_name == "reckon.crawl.list":
        runs = repository.list_for_website(
            context.organization_id,
            payload.website_id,
            limit=payload.limit,
            offset=payload.offset,
        )
        result = [
            {
                "crawl_id": str(run.id),
                "website_id": str(run.website_id),
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "completed_at": (
                    run.completed_at.isoformat()
                    if run.completed_at is not None
                    else None
                ),
                "audit_version": run.audit_version,
                "error_code": run.error_code,
            }
            for run in runs
        ]
    else:
        schedules = repository.list_schedules(
            organization_id=context.organization_id,
            website_id=payload.website_id,
        )
        result = [
            {
                "schedule_id": str(schedule.id),
                "website_id": str(schedule.website_id),
                "frequency": schedule.frequency,
                "active": schedule.active,
                "next_run_at": schedule.next_run_at.isoformat(),
                "last_run_id": (
                    str(schedule.last_run_id)
                    if schedule.last_run_id is not None
                    else None
                ),
            }
            for schedule in schedules
        ]
    return McpInvokeResponse(tool=tool_name, result=result)
