from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from reckon_api.dependencies import get_database_session

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get("/health/ready", response_model=LivenessResponse)
def readiness(session: Session = Depends(get_database_session)) -> LivenessResponse:
    session.execute(text("SELECT 1"))
    return LivenessResponse(status="ok")
