"""Unauthenticated, rate-limited SEO audit of any public website."""

import asyncio
from collections import deque
from dataclasses import asdict
from time import monotonic
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from reckon_core.public_audit import (
    PublicAuditReport,
    PublicAuditTargetError,
    PublicAuditUnavailable,
    normalize_target,
    run_public_audit,
)

router = APIRouter(prefix="/api/v1/public", tags=["public-audit"])

_WINDOW_SECONDS = 3600.0
_CACHE_SECONDS = 600.0
_MAX_TRACKED_CLIENTS = 5000
_MAX_CACHED_REPORTS = 200


class PublicAuditRequest(BaseModel):
    url: str = Field(min_length=1, max_length=300)


class PublicFindingModel(BaseModel):
    id: str
    category: str
    severity: Literal["high", "medium", "low"]
    title: str
    found: str
    why_it_matters: str
    how_to_fix: str
    url: str


class PublicCheckModel(BaseModel):
    category: str
    label: str
    passed: bool


class PublicAuditResponse(BaseModel):
    host: str
    final_url: str
    score: int
    grade: Literal["A", "B", "C", "D", "F"]
    pages_checked: int
    findings: list[PublicFindingModel]
    checks: list[PublicCheckModel]
    audit_version: str
    cached: bool = False


class PublicAuditGuard:
    """In-memory per-client sliding window, short result cache and a concurrency cap.

    State is per process; run a shared limiter (for example Redis) when scaling out. Behind
    a reverse proxy, make sure the proxy sets the client address the server sees.
    """

    def __init__(self, hourly_limit: int, concurrency: int = 3) -> None:
        self.hourly_limit = hourly_limit
        self.slots = asyncio.Semaphore(concurrency)
        self._hits: dict[str, deque[float]] = {}
        self._cache: dict[str, tuple[float, PublicAuditReport]] = {}

    def allow(self, client: str) -> bool:
        now = monotonic()
        if client not in self._hits and len(self._hits) >= _MAX_TRACKED_CLIENTS:
            for key in [k for k, v in self._hits.items() if not v or now - v[-1] > _WINDOW_SECONDS]:
                del self._hits[key]
            if len(self._hits) >= _MAX_TRACKED_CLIENTS:
                return False
        hits = self._hits.setdefault(client, deque())
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.hourly_limit:
            return False
        hits.append(now)
        return True

    def cached(self, host: str) -> PublicAuditReport | None:
        entry = self._cache.get(host)
        if entry and monotonic() - entry[0] < _CACHE_SECONDS:
            return entry[1]
        self._cache.pop(host, None)
        return None

    def store(self, host: str, report: PublicAuditReport) -> None:
        if len(self._cache) >= _MAX_CACHED_REPORTS:
            self._cache.pop(next(iter(self._cache)))
        self._cache[host] = (monotonic(), report)


def _response(report: PublicAuditReport, cached: bool) -> PublicAuditResponse:
    data = asdict(report)
    return PublicAuditResponse(**data, cached=cached)


@router.post("/audit", response_model=PublicAuditResponse)
async def public_audit(
    payload: PublicAuditRequest, request: Request, response: Response
) -> PublicAuditResponse:
    response.headers["Cache-Control"] = "no-store"
    guard: PublicAuditGuard = request.app.state.public_audit_guard
    if guard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The public audit is not enabled.")
    try:
        _, host = normalize_target(payload.url)
    except PublicAuditTargetError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    cached = guard.cached(host)
    if cached is not None:
        return _response(cached, True)
    client = request.client.host if request.client else "unknown"
    if not guard.allow(client):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You have reached the hourly audit limit. Please try again later or sign up.",
            headers={"Retry-After": "3600"},
        )
    if guard.slots.locked():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The audit service is busy. Please try again in a minute.",
            headers={"Retry-After": "60"},
        )
    async with guard.slots:
        try:
            report = await run_in_threadpool(
                run_public_audit, request.app.state.homepage_crawler, payload.url
            )
        except PublicAuditTargetError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
        except PublicAuditUnavailable as error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    guard.store(host, report)
    return _response(report, False)
