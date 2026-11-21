from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.cms_adapters import CmsAdapterUnavailable, WordPressCmsAdapter
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.tenancy import AuthenticatedPrincipal, TenantAccessDenied
from pydantic import SecretStr


router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/cms",
    tags=["CMS"],
)


class CmsCapabilityResponse(BaseModel):
    name: str
    read_supported: bool
    write_supported: bool
    approval_required: bool


class CmsDiscoveryResponse(BaseModel):
    provider: Literal["wordpress"]
    base_url: str
    verified: bool
    capabilities: list[CmsCapabilityResponse]


@router.get("/wordpress/discover", response_model=CmsDiscoveryResponse)
async def discover_wordpress(
    http_request: Request,
    organization_id: UUID,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> CmsDiscoveryResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.WEBSITE_VERIFY)
    except TenantAccessDenied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization administrator access is required.",
        ) from None
    settings = http_request.app.state.settings
    if (
        not settings.cms_wordpress_enabled
        or not settings.cms_wordpress_base_url
        or not settings.cms_wordpress_username
        or not settings.cms_wordpress_app_password
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WordPress CMS discovery is not configured.",
        )
    try:
        adapter = WordPressCmsAdapter(
            settings.cms_wordpress_base_url,
            settings.cms_wordpress_username,
            SecretStr(settings.cms_wordpress_app_password.get_secret_value()),
            transport=getattr(http_request.app.state, "cms_transport", None),
        )
        discovered = await adapter.discover(timeout_seconds=10.0)
    except (ValueError, CmsAdapterUnavailable) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WordPress CMS capabilities could not be verified.",
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return CmsDiscoveryResponse(
        provider=discovered.provider,
        base_url=discovered.base_url,
        verified=discovered.verified,
        capabilities=[
            CmsCapabilityResponse(
                name=capability.name,
                read_supported=capability.read_supported,
                write_supported=capability.write_supported,
                approval_required=capability.approval_required,
            )
            for capability in discovered.capabilities
        ],
    )
