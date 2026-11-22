import asyncio
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from celery.exceptions import CeleryError
from kombu.exceptions import OperationalError as BrokerOperationalError
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

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
from reckon_core.model_gateway import (
    ModelExecutionPolicy,
    ModelGateway,
    ModelGatewayRejected,
    ModelGatewayReplay,
    ModelLimitExceeded,
)
from reckon_core.model_providers import ProviderAdapter
from reckon_core.model_settings import (
    CredentialCipher,
    CredentialEncryptionUnavailable,
    DEFAULT_MODEL_ENDPOINTS,
    SqlAlchemyModelSettingsRepository,
)
from reckon_core.model_usage_repository import ModelBudgetExceeded
from reckon_core.persistence import CrawlRun, CrawlSchedule
from reckon_core.persistence import OrganizationModelSettings
from reckon_core.repositories import (
    CrawlBudgetExceeded,
    CrawlRetentionLimitExceeded,
    CrawlScheduleNotFound,
    IdempotencyConflict,
    SqlAlchemyCrawlRepository,
    WebsiteNotFound,
    WebsiteNotVerified,
)
from reckon_core.specialist_agents import (
    AgentRunResult,
    GovernedPrioritizationAgent,
    SpecialistPrioritizationAuthorizer,
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
    TenantContext,
)
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.seo_engines import EngineName, audit_engine

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


class PageEvidenceResponse(BaseModel):
    url: str
    status: Literal[
        "fetched",
        "robots_disallowed",
        "fetch_unavailable",
        "fetch_rejected",
        "unsupported_content_type",
    ]
    http_status_code: int | None = None
    content_type: str | None = None
    bytes_read: int | None = None
    title: str | None = None
    meta_description: str | None = None
    h1_count: int | None = None
    h2_count: int | None = None
    internal_link_count: int | None = None
    image_count: int | None = None
    missing_alt_text_count: int | None = None


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
    internal_urls: list[str] = Field(default_factory=list)
    page_evidence: list[PageEvidenceResponse] = Field(default_factory=list)
    error_code: str | None


class EngineFindingResponse(BaseModel):
    code: str
    title: str
    impact: Literal["high", "medium", "low"]
    confidence: Literal["high", "medium"]
    effort: Literal["low", "medium", "high"]
    source_url: str
    evidence: str
    recommendation: str
    verification: str


class EngineAuditResponse(BaseModel):
    engine: EngineName
    version: str
    coverage: Literal["complete", "partial", "unavailable"]
    findings: list[EngineFindingResponse]


class PrioritizationResponse(BaseModel):
    status: Literal["completed", "unknown", "invalid_output"]
    ordered_codes: list[HomepageFindingCode] | None = None
    reservation_id: UUID | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class PurgeCrawlHistoryRequest(BaseModel):
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=200),
    ]


class PurgeCrawlHistoryResponse(BaseModel):
    deleted_count: int
    cutoff: datetime
    retention_days: int


class CrawlScheduleRequest(BaseModel):
    frequency: Literal["daily", "weekly"]
    active: bool = True


class CrawlScheduleResponse(BaseModel):
    schedule_id: UUID
    website_id: UUID
    frequency: Literal["daily", "weekly"]
    active: bool
    next_run_at: datetime
    last_run_id: UUID | None
    created_at: datetime


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
        internal_urls=list(run.internal_urls or []),
        page_evidence=[
            PageEvidenceResponse.model_validate(item)
            for item in (run.page_evidence or [])
        ],
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


@router.get(
    "/{website_id}/crawls/{crawl_id}/engines/{engine}",
    response_model=EngineAuditResponse,
)
def get_engine_audit(
    organization_id: UUID,
    website_id: UUID,
    crawl_id: UUID,
    engine: EngineName,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> EngineAuditResponse:
    context = resolve_organization_access(principal, organization_id, session)
    run = session.scalar(
        select(CrawlRun).where(
            CrawlRun.organization_id == context.organization_id,
            CrawlRun.website_id == website_id,
            CrawlRun.id == crawl_id,
            CrawlRun.status == "completed",
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Completed crawl evidence was not found.",
        )
    audit = audit_engine(run, engine)
    return EngineAuditResponse(
        engine=audit.engine,
        version=audit.version,
        coverage=audit.coverage,
        findings=[
            EngineFindingResponse(
                code=finding.code,
                title=finding.title,
                impact=finding.impact,
                confidence=finding.confidence,
                effort=finding.effort,
                source_url=finding.source_url,
                evidence=finding.evidence,
                recommendation=finding.recommendation,
                verification=finding.verification,
            )
            for finding in audit.findings
        ],
    )


def _schedule_response(schedule: CrawlSchedule) -> CrawlScheduleResponse:
    next_run_at = schedule.next_run_at
    created_at = schedule.created_at
    if next_run_at.tzinfo is None:
        next_run_at = next_run_at.replace(tzinfo=timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return CrawlScheduleResponse(
        schedule_id=schedule.id,
        website_id=schedule.website_id,
        frequency=schedule.frequency,
        active=schedule.active,
        next_run_at=next_run_at.astimezone(timezone.utc),
        last_run_id=schedule.last_run_id,
        created_at=created_at.astimezone(timezone.utc),
    )


@router.get("/{website_id}/crawl-schedules", response_model=list[CrawlScheduleResponse])
def list_crawl_schedules(
    organization_id: UUID,
    website_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[CrawlScheduleResponse]:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.CRAWL_VIEW)
    except TenantAccessDenied:
        raise HTTPException(status_code=403, detail="Organization crawl access is required.") from None
    rows = SqlAlchemyCrawlRepository(session).list_schedules(
        organization_id=context.organization_id,
        website_id=website_id,
    )
    return [_schedule_response(row) for row in rows]


@router.post("/{website_id}/crawl-schedules", response_model=CrawlScheduleResponse)
def create_crawl_schedule(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    payload: CrawlScheduleRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> CrawlScheduleResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.CRAWL_SCHEDULE_MANAGE)
    except TenantAccessDenied:
        raise HTTPException(status_code=403, detail="Organization schedule management access is required.") from None
    try:
        schedule = SqlAlchemyCrawlRepository(session).create_schedule(
            organization_id=context.organization_id,
            website_id=website_id,
            actor_user_id=principal.user_id,
            request_id=http_request.state.request_id,
            frequency=payload.frequency,
            active=payload.active,
        )
        session.commit()
    except WebsiteNotFound as error:
        raise HTTPException(status_code=404, detail="Website not found.") from error
    except WebsiteNotVerified as error:
        raise HTTPException(status_code=409, detail="Website ownership must be verified before scheduling.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _schedule_response(schedule)


@router.patch("/{website_id}/crawl-schedules/{schedule_id}", response_model=CrawlScheduleResponse)
def update_crawl_schedule(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    schedule_id: UUID,
    payload: CrawlScheduleRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> CrawlScheduleResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.CRAWL_SCHEDULE_MANAGE)
    except TenantAccessDenied:
        raise HTTPException(status_code=403, detail="Organization schedule management access is required.") from None
    try:
        schedule = SqlAlchemyCrawlRepository(session).update_schedule(
            organization_id=context.organization_id,
            website_id=website_id,
            schedule_id=schedule_id,
            actor_user_id=principal.user_id,
            request_id=http_request.state.request_id,
            active=payload.active,
            frequency=payload.frequency,
        )
        session.commit()
    except CrawlScheduleNotFound as error:
        raise HTTPException(status_code=404, detail="Crawl schedule not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _schedule_response(schedule)


@router.delete("/{website_id}/crawl-schedules/{schedule_id}", status_code=204)
def delete_crawl_schedule(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    schedule_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> Response:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.CRAWL_SCHEDULE_MANAGE)
    except TenantAccessDenied:
        raise HTTPException(status_code=403, detail="Organization schedule management access is required.") from None
    try:
        schedule = SqlAlchemyCrawlRepository(session).delete_schedule(
            organization_id=context.organization_id,
            website_id=website_id,
            schedule_id=schedule_id,
            actor_user_id=principal.user_id,
            request_id=http_request.state.request_id,
        )
        session.commit()
    except CrawlScheduleNotFound as error:
        raise HTTPException(status_code=404, detail="Crawl schedule not found.") from error
    return Response(status_code=204)


@router.post(
    "/{website_id}/crawls/purge",
    response_model=PurgeCrawlHistoryResponse,
)
def purge_website_crawl_history(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    payload: PurgeCrawlHistoryRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> PurgeCrawlHistoryResponse:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.CRAWL_PURGE)
    except TenantAccessDenied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners and admins can purge crawl history.",
        )
    retention_days = http_request.app.state.settings.crawl_history_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    try:
        deleted = SqlAlchemyCrawlRepository(session).purge_before(
            organization_id=context.organization_id,
            website_id=website_id,
            actor_user_id=principal.user_id,
            request_id=http_request.state.request_id,
            cutoff=cutoff,
            reason=payload.reason,
        )
        session.commit()
    except WebsiteNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found.",
        ) from error
    except CrawlRetentionLimitExceeded as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The purge batch exceeds the safe 1000-run limit.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return PurgeCrawlHistoryResponse(
        deleted_count=deleted,
        cutoff=cutoff,
        retention_days=retention_days,
    )


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

    queue = getattr(http_request.app.state, "crawl_queue", None)
    if queue is not None:
        try:
            queue.enqueue(
                organization_id=context.organization_id,
                website_id=website_id,
                run_id=run.id,
                actor_user_id=principal.user_id,
                request_id=http_request.state.request_id,
            )
        except (CeleryError, BrokerOperationalError, ValueError):
            repository.finish(
                run,
                principal.user_id,
                http_request.state.request_id,
                status="failed",
                error_code="crawl_queue_unavailable",
            )
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The crawl worker queue is temporarily unavailable.",
            )
        session.commit()
        return _crawl_response(run)

    crawler = http_request.app.state.homepage_crawler
    try:
        if hasattr(crawler, "crawl_pages"):
            result = crawler.crawl_pages(website.scheme, website.host)
        else:
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


@router.post(
    "/{website_id}/crawls/{crawl_id}/prioritize",
    response_model=PrioritizationResponse,
)
async def prioritize_crawl(
    http_request: Request,
    organization_id: UUID,
    website_id: UUID,
    crawl_id: UUID,
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
) -> PrioritizationResponse:
    context = resolve_organization_access(principal, organization_id, session)
    settings = SqlAlchemyModelSettingsRepository(session).get(context)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Save AI settings before running a specialist agent.",
        )
    if http_request.url.scheme != "https" and http_request.app.state.settings.environment != "test":
        local_request = (
            http_request.app.state.settings.environment == "local"
            and http_request.client is not None
            and http_request.client.host in {"127.0.0.1", "::1"}
        )
        if not local_request:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HTTPS is required to run an AI specialist.",
            )

    provider = settings.provider
    model = settings.model
    endpoint = settings.endpoint_url or DEFAULT_MODEL_ENDPOINTS[provider]
    ciphertext = settings.encrypted_key
    try:
        api_key = CredentialCipher(
            http_request.app.state.settings.credential_encryption_key
        ).decrypt(ciphertext, organization_id, provider)
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored credential could not be decrypted. Replace the API key.",
        ) from error

    adapter = ProviderAdapter(
        provider,
        endpoint,
        api_key,
        ciphertext,
        http_request.app.state.model_test_resolver,
        http_request.app.state.model_test_transport,
    )
    policy = ModelExecutionPolicy(
        provider=provider,
        model=model,
        daily_token_limit=http_request.app.state.settings.ai_test_daily_token_limit,
        max_input_tokens=4096,
        max_output_tokens=512,
        timeout_seconds=15.0,
    )

    def check_binding(locked_session: Session, tenant: TenantContext) -> None:
        current = locked_session.scalar(
            select(OrganizationModelSettings).where(
                OrganizationModelSettings.organization_id == tenant.organization_id
            )
        )
        if (
            current is None
            or current.provider != provider
            or current.model != model
            or (current.endpoint_url or DEFAULT_MODEL_ENDPOINTS[current.provider]) != endpoint
            or not hmac.compare_digest(current.encrypted_key, ciphertext)
        ):
            raise ModelGatewayRejected("AI settings changed; start a new specialist run.")

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    gateway = ModelGateway(
        factory,
        SpecialistPrioritizationAuthorizer(policy),
        {provider: adapter},
        2,
        check_binding,
    )
    task_id = uuid5(
        organization_id,
        f"specialist:technical-audit-prioritizer:{website_id}:{crawl_id}",
    )
    agent = GovernedPrioritizationAgent(
        factory,
        Path(__file__).resolve().parents[5] / "skills",
        gateway,
        provider,
        model,
    )

    try:
        async with asyncio.timeout(16.0):
            result: AgentRunResult = await agent.execute(
                context,
                website_id,
                crawl_id,
                task_id,
                http_request.state.request_id,
                idempotency_key,
            )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization or crawl not found.") from error
    except ModelBudgetExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The organization has reached its AI token budget.",
        ) from error
    except (ModelGatewayReplay, IdempotencyConflict) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This specialist run was already attempted; start a new run deliberately.",
        ) from error
    except ModelGatewayRejected as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ModelLimitExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The provider exceeded the authorized token limit.",
        ) from error
    except TimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The specialist run exceeded its aggregate deadline.",
        ) from error

    if result.status == "unknown":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The provider response could not be verified; charges may be unknown.",
        )
    if result.status == "invalid_output":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The specialist response did not match its typed contract.",
        )
    return PrioritizationResponse(
        status=result.status,
        ordered_codes=list(result.ordered_codes) if result.ordered_codes is not None else None,
        reservation_id=result.reservation_id,
        input_tokens=result.usage.input_tokens if result.usage is not None else None,
        output_tokens=result.usage.output_tokens if result.usage is not None else None,
    )
