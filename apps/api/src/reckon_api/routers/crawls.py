from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from reckon_api.dependencies import (
    get_authenticated_principal,
    get_database_session,
)
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.crawler import (
    CrawlDisallowed,
    CrawlPolicyError,
    CrawlUnavailable,
    SitemapDocumentType,
    SitemapFetchStatus,
)
from reckon_core.persistence import CrawlRun
from reckon_core.repositories import (
    CrawlBudgetExceeded,
    IdempotencyConflict,
    SqlAlchemyCrawlRepository,
    WebsiteNotFound,
    WebsiteNotVerified,
)
from reckon_core.seo_audit import (
    FindingConfidence,
    FindingEffort,
    FindingImpact,
    HomepageFindingCode,
    audit_homepage,
)
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    TenantAccessDenied,
)

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/websites",
    tags=["crawls"],
)


class CrawlFindingResponse(BaseModel):
    code: HomepageFindingCode
    impact: FindingImpact
    confidence: FindingConfidence
    effort: FindingEffort
    source_url: str
    summary: str
    evidence: str
    recommendation: str
    verification: str


class SitemapEvidenceResponse(BaseModel):
    url: str
    status: SitemapFetchStatus
    http_status_code: int | None
    document_type: SitemapDocumentType | None
    url_count: int | None
    homepage_listed: bool | None = None
    canonical_url_listed: bool | None = None
    child_sitemap_count: int | None
    child_sitemap_urls: list[str] = Field(default_factory=list)
    rejected_count: int | None
    truncated: bool


class CrawlResponse(BaseModel):
    crawl_id: UUID
    website_id: UUID
    status: Literal["running", "completed", "disallowed", "failed"]
    started_at: datetime
    completed_at: datetime | None
    final_url: str | None
    http_status: int | None
    content_type: str | None
    bytes_read: int | None
    title: str | None
    audit_version: str | None
    findings: list[CrawlFindingResponse] | None
    meta_description: str | None
    h1_count: int | None
    meta_robots_noindex: bool | None
    x_robots_noindex: bool | None
    canonical_url: str | None
    canonical_link_count: int | None
    robots_status_code: int | None
    sitemap_urls: list[str] | None
    sitemap_evidence: list[SitemapEvidenceResponse] | None
    sitemap_declaration_count: int | None
    sitemap_rejected_count: int | None
    sitemap_discovery_truncated: bool | None
    redirect_count: int | None
    error_code: str | None


def _crawl_response(run: CrawlRun) -> CrawlResponse:
    if run.status not in {"running", "completed", "disallowed", "failed"}:
        raise RuntimeError("The crawl run has an invalid status.")
    started_at = run.started_at
    completed_at = run.completed_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if completed_at is not None and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    return CrawlResponse(
        crawl_id=run.id,
        website_id=run.website_id,
        status=run.status,
        started_at=started_at.astimezone(timezone.utc),
        completed_at=(
            completed_at.astimezone(timezone.utc)
            if completed_at is not None
            else None
        ),
        final_url=run.final_url,
        http_status=run.http_status,
        content_type=run.content_type,
        bytes_read=run.bytes_read,
        title=run.title,
        audit_version=run.audit_version,
        findings=run.audit_findings,
        meta_description=run.meta_description,
        h1_count=run.h1_count,
        meta_robots_noindex=run.meta_robots_noindex,
        x_robots_noindex=run.x_robots_noindex,
        canonical_url=run.canonical_url,
        canonical_link_count=run.canonical_link_count,
        robots_status_code=run.robots_status_code,
        sitemap_urls=run.sitemap_urls,
        sitemap_evidence=run.sitemap_evidence,
        sitemap_declaration_count=run.sitemap_declaration_count,
        sitemap_rejected_count=run.sitemap_rejected_count,
        sitemap_discovery_truncated=run.sitemap_discovery_truncated,
        redirect_count=run.redirect_count,
        error_code=run.error_code,
    )


@router.get(
    "/{website_id}/crawls",
    response_model=list[CrawlResponse],
)
def list_website_crawls(
    organization_id: UUID,
    website_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[CrawlResponse]:
    context = resolve_organization_access(principal, organization_id, session)
    repository = SqlAlchemyCrawlRepository(session)
    try:
        runs = repository.list_for_website(
            context.organization_id,
            website_id,
            limit=limit,
            offset=offset,
        )
    except WebsiteNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found.",
        ) from error
    return [_crawl_response(run) for run in runs]


@router.post(
    "/{website_id}/crawl",
    response_model=CrawlResponse,
)
def crawl_website(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]{8,128}$",
        ),
    ],
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> CrawlResponse:
    context = resolve_organization_access(principal, organization_id, session)
    repository = SqlAlchemyCrawlRepository(session)
    settings = http_request.app.state.settings
    try:
        website, run, replay = repository.reserve(
            organization_id=context.organization_id,
            website_id=website_id,
            actor_user_id=principal.user_id,
            request_id=http_request.state.request_id,
            idempotency_key=idempotency_key,
            daily_limit=settings.crawl_daily_limit,
        )
    except TenantAccessDenied as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        ) from error
    except WebsiteNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found.",
        ) from error
    except WebsiteNotVerified as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Website ownership must be verified before crawling.",
        ) from error
    except IdempotencyConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for a different crawl.",
        ) from error
    except CrawlBudgetExceeded as error:
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The organization has reached its daily crawl limit.",
        ) from error

    session.commit()
    if replay:
        if run.status in {"completed", "disallowed"}:
            return _crawl_response(run)
        if run.status == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This crawl request is already in progress.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This crawl request failed; use a new idempotency key to retry.",
        )

    crawler = http_request.app.state.homepage_crawler
    try:
        result = crawler.crawl(website.scheme, website.host)
    except CrawlDisallowed:
        run = repository.finish(
            run,
            principal.user_id,
            http_request.state.request_id,
            status="disallowed",
            error_code="robots_disallowed",
        )
        session.commit()
        return _crawl_response(run)
    except CrawlPolicyError as error:
        repository.finish(
            run,
            principal.user_id,
            http_request.state.request_id,
            status="failed",
            error_code="crawl_policy_blocked",
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The crawl was blocked by the crawl policy.",
        ) from error
    except CrawlUnavailable as error:
        repository.finish(
            run,
            principal.user_id,
            http_request.state.request_id,
            status="failed",
            error_code="crawl_unavailable",
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The website could not be crawled at this time.",
        ) from error

    run = repository.finish(
        run,
        principal.user_id,
        http_request.state.request_id,
        status="completed",
        result=result,
        audit=audit_homepage(result),
    )
    session.commit()
    return _crawl_response(run)
