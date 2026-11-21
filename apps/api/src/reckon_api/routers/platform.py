from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_core.persistence import PlatformAdministrator
from reckon_core.tenancy import AuthenticatedPrincipal

router = APIRouter(prefix="/api/v1/platform", tags=["platform access"])


class PlatformAccessResponse(BaseModel):
    is_platform_admin: bool


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
