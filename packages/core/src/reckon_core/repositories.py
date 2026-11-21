import hashlib
import hmac
import secrets
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reckon_core.persistence import (
    AuditEvent,
    CrawlRun,
    CrawlSchedule,
    ExternalIdentity,
    NativeAccount,
    Organization,
    OrganizationCreationRequest,
    OrganizationMembership,
    User,
    Website,
    WebsiteCreationRequest,
)
from reckon_core.crawler import CrawlResult
from reckon_core.seo_audit import HomepageAudit
from reckon_core.tenancy import (
    OrganizationRole,
    TenantAccessDenied,
    TenantContext,
)

_STALE_CRAWL_AFTER = timedelta(minutes=5)


def utc_day(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required.")
    day_start = now.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return day_start, day_start + timedelta(days=1)


class IdempotencyConflict(ValueError):
    pass


class WebsiteAlreadyExists(ValueError):
    pass


class WebsiteNotFound(LookupError):
    pass


class WebsiteNotVerified(ValueError):
    pass


class CrawlBudgetExceeded(ValueError):
    pass


class CrawlRetentionLimitExceeded(ValueError):
    pass


class CrawlScheduleNotFound(LookupError):
    pass


class CrawlRequestInProgress(ValueError):
    pass


class SqlAlchemyIdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def user_id_for_identity(self, issuer: str, subject: str) -> UUID | None:
        return self._session.scalar(
            select(ExternalIdentity.user_id).where(
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == subject,
            )
        )


class SqlAlchemyIdentityProvisioningRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def provision(self, issuer: str, subject: str) -> tuple[UUID, bool]:
        if (
            not issuer
            or issuer != issuer.strip()
            or len(issuer) > 512
            or not subject
            or not subject.strip()
            or len(subject) > 512
        ):
            raise ValueError("Verified identity claims are invalid.")

        existing_user_id = self._user_id_for_identity(issuer, subject)
        if existing_user_id is not None:
            return existing_user_id, False

        user = User()
        try:
            with self._session.begin_nested():
                self._session.add(user)
                self._session.flush()
                self._session.add(
                    ExternalIdentity(
                        issuer=issuer,
                        subject=subject,
                        user_id=user.id,
                    )
                )
                self._session.flush()
        except IntegrityError:
            existing_user_id = self._user_id_for_identity(issuer, subject)
            if existing_user_id is None:
                raise
            return existing_user_id, False

        return user.id, True

    def _user_id_for_identity(self, issuer: str, subject: str) -> UUID | None:
        return self._session.scalar(
            select(ExternalIdentity.user_id).where(
                ExternalIdentity.issuer == issuer,
                ExternalIdentity.subject == subject,
            )
        )


class SqlAlchemyMembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

        self._is_postgresql = session.get_bind().dialect.name == "postgresql"

    def role_for_active_membership(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> OrganizationRole | None:
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )

        membership = self._session.get(
            OrganizationMembership,
            {
                "organization_id": organization_id,
                "user_id": user_id,
            },
        )
        if membership is None or not membership.is_active:
            return None
        return membership.role


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._is_postgresql = session.get_bind().dialect.name == "postgresql"

    def list_members(
        self, context: TenantContext, limit: int, after: UUID | None
    ) -> tuple[list[tuple[UUID, str | None, OrganizationRole]], UUID | None]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("The member page size must be between 1 and 50.")
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(context.organization_id)},
            )
        membership = self._session.execute(
            select(OrganizationMembership.is_active, OrganizationMembership.role)
            .where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.user_id == context.principal.user_id,
            )
            .with_for_update()
        ).one_or_none()
        if (
            membership is None or membership.is_active is not True
            or membership.role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        ):
            raise TenantAccessDenied
        query = (
            select(OrganizationMembership.user_id, NativeAccount.email, OrganizationMembership.role)
            .outerjoin(NativeAccount, NativeAccount.user_id == OrganizationMembership.user_id)
            .where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.is_active.is_(True),
            )
        )
        if after is not None:
            query = query.where(OrganizationMembership.user_id > after)
        rows = self._session.execute(
            query.order_by(OrganizationMembership.user_id).limit(limit + 1)
        ).all()
        page = rows[:limit]
        cursor = page[-1].user_id if len(rows) > limit else None
        return [(row.user_id, row.email, row.role) for row in page], cursor

    def list_for_user(
        self, user_id: UUID, limit: int, after: UUID | None
    ) -> tuple[list[tuple[UUID, str, OrganizationRole]], UUID | None]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("The organization page size must be between 1 and 50.")
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', '', true)")
            )
            self._session.execute(
                text("SELECT set_config('app.usr_id', :user_id, true)"),
                {"user_id": str(user_id)},
            )
        query = select(OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.is_active.is_(True),
        )
        if after is not None:
            query = query.where(OrganizationMembership.organization_id > after)
        ids = self._session.scalars(
            query.order_by(OrganizationMembership.organization_id).limit(limit + 1)
        ).all()
        page_ids = ids[:limit]
        next_cursor = page_ids[-1] if len(ids) > limit else None
        organizations: list[tuple[UUID, str, OrganizationRole]] = []
        for organization_id in page_ids:
            if self._is_postgresql:
                self._session.execute(
                    text("SELECT set_config('app.org_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
            result = self._session.execute(
                select(Organization.id, Organization.name, OrganizationMembership.role)
                .join(
                    OrganizationMembership,
                    OrganizationMembership.organization_id == Organization.id,
                )
                .where(
                    Organization.id == organization_id,
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.is_active.is_(True),
                )
            ).one_or_none()
            if result is not None:
                organizations.append((result.id, result.name, result.role))
        return organizations, next_cursor

    def create_for_owner(
        self,
        owner_user_id: UUID,
        name: str,
        idempotency_key: str,
        request_id: UUID,
    ) -> tuple[UUID, OrganizationRole]:
        request_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.usr_id', :user_id, true)"),
                {"user_id": str(owner_user_id)},
            )
        user_id = self._session.scalar(
            select(User.id)
            .where(User.id == owner_user_id)
            .with_for_update()
        )
        if user_id is None:
            raise TenantAccessDenied

        existing_request = self._session.get(
            OrganizationCreationRequest,
            {
                "user_id": owner_user_id,
                "idempotency_key": idempotency_key,
            },
        )
        if existing_request is not None:
            if not hmac.compare_digest(existing_request.request_hash, request_hash):
                raise IdempotencyConflict
            if self._is_postgresql:
                self._session.execute(
                    text(
                        "SELECT set_config('app.org_id', "
                        ":organization_id, true)"
                    ),
                    {"organization_id": str(existing_request.organization_id)},
                )
            membership = self._session.get(
                OrganizationMembership,
                {
                    "organization_id": existing_request.organization_id,
                    "user_id": owner_user_id,
                },
            )
            if membership is None or not membership.is_active:
                raise TenantAccessDenied
            return existing_request.organization_id, membership.role

        organization_id = uuid4()
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )

        self._session.add(
            Organization(
                id=organization_id,
                name=name,
            )
        )
        self._session.flush()
        self._session.add(
            OrganizationMembership(
                organization_id=organization_id,
                user_id=owner_user_id,
                role=OrganizationRole.OWNER,
                is_active=True,
            )
        )
        self._session.add(
            OrganizationCreationRequest(
                user_id=owner_user_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                organization_id=organization_id,
            )
        )
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=owner_user_id,
                action="organization.created",
                resource_type="organization",
                resource_id=organization_id,
                request_id=request_id,
                details={"name": name},
            )
        )
        self._session.flush()
        return organization_id, OrganizationRole.OWNER


class SqlAlchemyWebsiteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._is_postgresql = session.get_bind().dialect.name == "postgresql"

    def create(
        self,
        organization_id: UUID,
        actor_user_id: UUID,
        scheme: str,
        host: str,
        idempotency_key: str,
        request_id: UUID,
    ) -> Website:
        self._set_tenant(organization_id)
        found_organization = self._session.scalar(
            select(Organization.id)
            .where(Organization.id == organization_id)
            .with_for_update()
        )
        if found_organization is None:
            raise TenantAccessDenied

        request_hash = hashlib.sha256(
            f"{scheme}://{host}".encode("utf-8")
        ).hexdigest()
        existing_request = self._session.get(
            WebsiteCreationRequest,
            {
                "organization_id": organization_id,
                "idempotency_key": idempotency_key,
            },
        )
        if existing_request is not None:
            if not hmac.compare_digest(existing_request.request_hash, request_hash):
                raise IdempotencyConflict
            website = self._session.get(Website, existing_request.website_id)
            if website is None:
                raise WebsiteNotFound
            return website

        existing_website = self._session.scalar(
            select(Website.id).where(
                Website.organization_id == organization_id,
                Website.host == host,
            )
        )
        if existing_website is not None:
            raise WebsiteAlreadyExists

        website = Website(
            organization_id=organization_id,
            host=host,
            scheme=scheme,
            is_verified=False,
            verification_token=secrets.token_urlsafe(32),
        )
        self._session.add(website)
        self._session.flush()
        self._session.add(
            WebsiteCreationRequest(
                organization_id=organization_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                website_id=website.id,
            )
        )
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action="website.created",
                resource_type="website",
                resource_id=website.id,
                request_id=request_id,
                details={"host": host},
            )
        )
        self._session.flush()
        return website

    def list_for_organization(self, organization_id: UUID) -> list[Website]:
        self._set_tenant(organization_id)
        return list(
            self._session.scalars(
                select(Website)
                .where(Website.organization_id == organization_id)
                .order_by(Website.created_at, Website.id)
            )
        )

    def get_for_verification(
        self,
        organization_id: UUID,
        website_id: UUID,
    ) -> Website:
        self._set_tenant(organization_id)
        website = self._session.scalar(
            select(Website)
            .where(
                Website.organization_id == organization_id,
                Website.id == website_id,
            )
            .with_for_update()
        )
        if website is None:
            raise WebsiteNotFound
        return website

    def mark_verified(
        self,
        website: Website,
        actor_user_id: UUID,
        request_id: UUID,
    ) -> Website:
        self._set_tenant(website.organization_id)
        if website.is_verified:
            return website

        website.is_verified = True
        website.verified_at = datetime.now(timezone.utc)
        self._session.add(
            AuditEvent(
                organization_id=website.organization_id,
                actor_user_id=actor_user_id,
                action="website.verified",
                resource_type="website",
                resource_id=website.id,
                request_id=request_id,
                details={"host": website.host, "method": "dns_txt"},
            )
        )
        self._session.flush()
        return website

    def _set_tenant(self, organization_id: UUID) -> None:
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )


class SqlAlchemyCrawlRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._is_postgresql = session.get_bind().dialect.name == "postgresql"

    def count_for_period(
        self, organization_id: UUID, period_start: datetime, period_end: datetime
    ) -> int:
        self._set_tenant(organization_id)
        count = self._session.scalar(
            select(func.count(CrawlRun.id)).where(
                CrawlRun.organization_id == organization_id,
                CrawlRun.started_at >= period_start,
                CrawlRun.started_at < period_end,
            )
        )
        if count is None:
            raise RuntimeError("The crawl usage count could not be calculated.")
        return count

    def reserve(
        self,
        organization_id: UUID,
        website_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
        idempotency_key: str,
        daily_limit: int,
    ) -> tuple[Website, CrawlRun, bool]:
        self._set_tenant(organization_id)
        found_organization = self._session.scalar(
            select(Organization.id)
            .where(Organization.id == organization_id)
            .with_for_update()
        )
        if found_organization is None:
            raise TenantAccessDenied

        website = self._session.scalar(
            select(Website).where(
                Website.organization_id == organization_id,
                Website.id == website_id,
            )
        )
        if website is None:
            raise WebsiteNotFound
        if not website.is_verified:
            raise WebsiteNotVerified

        now = datetime.now(timezone.utc)
        stale_before = now - _STALE_CRAWL_AFTER
        stale_runs = self._session.scalars(
            select(CrawlRun)
            .where(
                CrawlRun.organization_id == organization_id,
                CrawlRun.status == "running",
                CrawlRun.started_at < stale_before,
            )
            .with_for_update()
        ).all()
        for stale_run in stale_runs:
            stale_run.status = "failed"
            stale_run.completed_at = now
            stale_run.error_code = "worker_interrupted"
            self._session.add(
                AuditEvent(
                    organization_id=organization_id,
                    actor_user_id=actor_user_id,
                    action="crawl.recovered",
                    resource_type="crawl_run",
                    resource_id=stale_run.id,
                    request_id=request_id,
                    details={
                        "site_id": str(stale_run.website_id),
                        "status": "failed",
                        "error_code": "worker_interrupted",
                    },
                )
            )

        request_hash = hashlib.sha256(str(website_id).encode("ascii")).hexdigest()
        existing_run = self._session.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.organization_id == organization_id,
                CrawlRun.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing_run is not None:
            if not hmac.compare_digest(existing_run.request_hash, request_hash):
                raise IdempotencyConflict
            return website, existing_run, True

        day_start, day_end = utc_day(now)
        used = self.count_for_period(organization_id, day_start, day_end)
        if used >= daily_limit:
            raise CrawlBudgetExceeded

        run = CrawlRun(
            id=uuid4(),
            organization_id=organization_id,
            website_id=website.id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status="running",
            started_at=now,
        )
        self._session.add(run)
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action="crawl.started",
                resource_type="crawl_run",
                resource_id=run.id,
                request_id=request_id,
                details={
                    "host": website.host,
                    "budget_limit": str(daily_limit),
                    "budget_used": str(used + 1),
                },
            )
        )
        self._session.flush()
        return website, run, False

    def list_for_website(
        self,
        organization_id: UUID,
        website_id: UUID,
        limit: int,
        offset: int,
    ) -> list[CrawlRun]:
        self._set_tenant(organization_id)
        website_exists = self._session.scalar(
            select(Website.id).where(
                Website.organization_id == organization_id,
                Website.id == website_id,
            )
        )
        if website_exists is None:
            raise WebsiteNotFound

        return list(
            self._session.scalars(
                select(CrawlRun)
                .where(
                    CrawlRun.organization_id == organization_id,
                    CrawlRun.website_id == website_id,
                )
                .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    def create_schedule(
        self,
        organization_id: UUID,
        website_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
        frequency: str,
        active: bool = True,
    ) -> CrawlSchedule:
        if frequency not in {"daily", "weekly"}:
            raise ValueError("The crawl schedule frequency must be daily or weekly.")
        if type(active) is not bool:
            raise ValueError("The crawl schedule active state must be boolean.")
        self._set_tenant(organization_id)
        website = self._session.scalar(
            select(Website).where(
                Website.organization_id == organization_id,
                Website.id == website_id,
            )
        )
        if website is None:
            raise WebsiteNotFound
        if not website.is_verified:
            raise WebsiteNotVerified
        existing = self._session.scalar(
            select(CrawlSchedule).where(
                CrawlSchedule.organization_id == organization_id,
                CrawlSchedule.website_id == website_id,
            )
        )
        if existing is not None:
            existing.frequency = frequency
            existing.active = active
            existing.next_run_at = datetime.now(timezone.utc) + (
                timedelta(days=1)
                if frequency == "daily"
                else timedelta(days=7)
            )
            self._session.flush()
            return existing
        now = datetime.now(timezone.utc)
        schedule = CrawlSchedule(
            id=uuid4(),
            organization_id=organization_id,
            website_id=website_id,
            actor_user_id=actor_user_id,
            frequency=frequency,
            active=active,
            next_run_at=now + (
                timedelta(days=1)
                if frequency == "daily"
                else timedelta(days=7)
            ),
        )
        self._session.add(schedule)
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action="crawl_schedule.created",
                resource_type="crawl_schedule",
                resource_id=schedule.id,
                request_id=request_id,
                details={
                    "site_id": str(website_id),
                    "frequency": frequency,
                },
            )
        )
        self._session.flush()
        return schedule

    def list_schedules(
        self,
        organization_id: UUID,
        website_id: UUID,
    ) -> list[CrawlSchedule]:
        self._set_tenant(organization_id)
        return list(
            self._session.scalars(
                select(CrawlSchedule)
                .where(
                    CrawlSchedule.organization_id == organization_id,
                    CrawlSchedule.website_id == website_id,
                )
                .order_by(CrawlSchedule.next_run_at)
            )
        )

    def update_schedule(
        self,
        organization_id: UUID,
        website_id: UUID,
        schedule_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
        active: bool,
        frequency: str,
    ) -> CrawlSchedule:
        if frequency not in {"daily", "weekly"}:
            raise ValueError("The crawl schedule frequency must be daily or weekly.")
        if type(active) is not bool:
            raise ValueError("The crawl schedule active state must be boolean.")
        self._set_tenant(organization_id)
        schedule = self._session.scalar(
            select(CrawlSchedule)
            .where(
                CrawlSchedule.organization_id == organization_id,
                CrawlSchedule.website_id == website_id,
                CrawlSchedule.id == schedule_id,
            )
            .with_for_update()
        )
        if schedule is None:
            raise CrawlScheduleNotFound
        schedule.frequency = frequency
        schedule.active = active
        schedule.next_run_at = datetime.now(timezone.utc) + (
            timedelta(days=1)
            if frequency == "daily"
            else timedelta(days=7)
        )
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action="crawl_schedule.updated",
                resource_type="crawl_schedule",
                resource_id=schedule.id,
                request_id=request_id,
                details={
                    "site_id": str(schedule.website_id),
                    "frequency": frequency,
                    "active": str(active).lower(),
                },
            )
        )
        self._session.flush()
        return schedule

    def delete_schedule(
        self,
        organization_id: UUID,
        website_id: UUID,
        schedule_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
    ) -> CrawlSchedule:
        self._set_tenant(organization_id)
        schedule = self._session.scalar(
            select(CrawlSchedule)
            .where(
                CrawlSchedule.organization_id == organization_id,
                CrawlSchedule.website_id == website_id,
                CrawlSchedule.id == schedule_id,
            )
            .with_for_update()
        )
        if schedule is None:
            raise CrawlScheduleNotFound
        self._session.delete(schedule)
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action="crawl_schedule.deleted",
                resource_type="crawl_schedule",
                resource_id=schedule.id,
                request_id=request_id,
                details={"site_id": str(schedule.website_id)},
            )
        )
        self._session.flush()
        return schedule

    def purge_before(
        self,
        organization_id: UUID,
        website_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
        cutoff: datetime,
        reason: str,
        max_rows: int = 1000,
    ) -> int:
        if type(max_rows) is not int or not 1 <= max_rows <= 1000:
            raise ValueError("The crawl purge batch limit must be between 1 and 1000.")
        if (
            cutoff.tzinfo is None
            or cutoff.utcoffset() is None
            or not reason.strip()
            or len(reason.strip()) > 200
        ):
            raise ValueError("A valid cutoff and purge reason are required.")
        reason = reason.strip()
        cutoff = cutoff.astimezone(timezone.utc)
        self._set_tenant(organization_id)
        website_exists = self._session.scalar(
            select(Website.id).where(
                Website.organization_id == organization_id,
                Website.id == website_id,
            )
        )
        if website_exists is None:
            raise WebsiteNotFound

        runs = list(
            self._session.scalars(
                select(CrawlRun)
                .where(
                    CrawlRun.organization_id == organization_id,
                    CrawlRun.website_id == website_id,
                    CrawlRun.started_at < cutoff,
                    CrawlRun.status != "running",
                )
                .order_by(CrawlRun.started_at, CrawlRun.id)
                .limit(max_rows + 1)
                .with_for_update()
            )
        )
        if len(runs) > max_rows:
            raise CrawlRetentionLimitExceeded

        ids = [run.id for run in runs]
        for run in runs:
            self._session.delete(run)
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action="crawl.purged",
                resource_type="website",
                resource_id=website_id,
                request_id=request_id,
                details={
                    "cutoff": cutoff.isoformat(),
                    "deleted_count": str(len(ids)),
                    "reason": reason,
                },
            )
        )
        self._session.flush()
        return len(ids)

    def finish(
        self,
        run: CrawlRun,
        actor_user_id: UUID,
        request_id: UUID,
        status: str,
        result: CrawlResult | None = None,
        audit: HomepageAudit | None = None,
        error_code: str | None = None,
    ) -> CrawlRun:
        if status not in {"completed", "disallowed", "failed"}:
            raise ValueError("A crawl run cannot be finished with this status.")
        if audit is not None and result is None:
            raise ValueError("A crawl audit requires page evidence.")
        self._set_tenant(run.organization_id)
        if run.status != "running":
            raise CrawlRequestInProgress

        run.status = status
        run.completed_at = datetime.now(timezone.utc)
        run.error_code = error_code
        details = {
            "site_id": str(run.website_id),
            "status": status,
        }
        if result is not None:
            run.final_url = result.final_url
            run.http_status = result.status_code
            run.content_type = result.content_type[:255]
            run.bytes_read = result.bytes_read
            run.title = result.title
            run.meta_description = result.meta_description
            run.h1_count = result.h1_count
            run.meta_robots_noindex = result.meta_robots_noindex
            run.x_robots_noindex = result.x_robots_noindex
            run.canonical_url = result.canonical_url
            run.canonical_link_count = result.canonical_link_count
            run.robots_status_code = result.robots_status_code
            run.sitemap_urls = (
                list(result.sitemap_urls)
                if result.sitemap_urls is not None
                else None
            )
            run.sitemap_evidence = (
                [asdict(item) for item in result.sitemap_evidence]
                if result.sitemap_evidence is not None
                else None
            )
            run.sitemap_declaration_count = result.sitemap_declaration_count
            run.sitemap_rejected_count = result.sitemap_rejected_count
            run.sitemap_discovery_truncated = result.sitemap_discovery_truncated
            run.redirect_count = result.redirect_count
            run.internal_urls = list(result.internal_urls)
            run.page_evidence = [
                asdict(item) for item in result.page_evidence
            ]
            if audit is not None:
                run.audit_version = audit.version
                run.audit_findings = [
                    asdict(finding) for finding in audit.findings
                ]
            details.update(
                {
                    "http_status": str(result.status_code),
                    "bytes_read": str(result.bytes_read),
                    "redirect_count": str(result.redirect_count),
                }
            )

        self._session.add(
            AuditEvent(
                organization_id=run.organization_id,
                actor_user_id=actor_user_id,
                action=f"crawl.{status}",
                resource_type="crawl_run",
                resource_id=run.id,
                request_id=request_id,
                details=details,
            )
        )
        self._session.flush()
        return run

    def _set_tenant(self, organization_id: UUID) -> None:
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )
