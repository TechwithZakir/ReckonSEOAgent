from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from celery import Celery
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from reckon_api.config import Settings
from reckon_core.crawler import (
    CrawlDisallowed,
    CrawlPolicyError,
    CrawlUnavailable,
    HomepageCrawler,
)
from reckon_core.persistence import CrawlRun, CrawlSchedule, Website
from reckon_core.repositories import (
    CrawlBudgetExceeded,
    SqlAlchemyCrawlRepository,
    SqlAlchemyMembershipRepository,
)
from reckon_core.seo_audit import audit_homepage


def create_celery_app(settings: Settings) -> Celery:
    if not settings.crawl_worker_enabled or not settings.crawl_broker_url:
        raise ValueError("Crawl workers are disabled or have no broker.")
    app = Celery(
        "reckon-crawl-worker",
        broker=settings.crawl_broker_url,
    )
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_max_tasks_per_child=50,
        task_soft_time_limit=20,
        task_time_limit=25,
        task_serializer="json",
        accept_content=["json"],
        result_extended=True,
        beat_schedule={
            "reckon-run-due-crawl-schedules": {
                "task": "reckon.run_due_crawl_schedules",
                "schedule": 60.0,
            },
        },
    )
    return app


class CeleryCrawlQueue:
    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    def enqueue(
        self,
        organization_id: UUID,
        website_id: UUID,
        run_id: UUID,
        actor_user_id: UUID,
        request_id: UUID,
    ) -> None:
        self._celery_app.send_task(
            "reckon.execute_crawl",
            args=[
                str(organization_id),
                str(website_id),
                str(run_id),
                str(actor_user_id),
                str(request_id),
            ],
        )


_settings = Settings()
if _settings.crawl_worker_enabled:
    celery_app = create_celery_app(_settings)
else:
    celery_app = Celery(
        "reckon-crawl-worker",
        broker="memory://",
    )


@celery_app.task(
    name="reckon.run_due_crawl_schedules",
    bind=False,
    max_retries=0,
)
def run_due_crawl_schedules() -> int:
    if not _settings.database_url or not _settings.crawl_worker_enabled:
        return 0
    database = create_engine(_settings.database_url.get_secret_value(), pool_pre_ping=True)
    created = 0
    try:
        factory = sessionmaker(database, expire_on_commit=False)
        with factory() as session:
            now = datetime.now(timezone.utc)
            rows = session.scalars(
                select(CrawlSchedule)
                .where(
                    CrawlSchedule.active.is_(True),
                    CrawlSchedule.next_run_at <= now,
                )
                .order_by(CrawlSchedule.next_run_at)
                .limit(100)
                .with_for_update()
            ).all()
            repository = SqlAlchemyCrawlRepository(session)
            for schedule in rows:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(
                        text("SELECT set_config('app.org_id', :organization_id, true)"),
                        {"organization_id": str(schedule.organization_id)},
                    )
                if SqlAlchemyMembershipRepository(session).role_for_active_membership(
                    schedule.actor_user_id,
                    schedule.organization_id,
                ) is None:
                    schedule.active = False
                    continue
                key = f"scheduled-{schedule.id}-{now.strftime('%Y%m%d%H%M')}"
                request_id = uuid4()
                try:
                    _, run, replay = repository.reserve(
                        organization_id=schedule.organization_id,
                        website_id=schedule.website_id,
                        actor_user_id=schedule.actor_user_id,
                        request_id=request_id,
                        idempotency_key=key,
                        daily_limit=_settings.crawl_daily_limit,
                    )
                except CrawlBudgetExceeded:
                    schedule.next_run_at = now + (
                        timedelta(days=1)
                        if schedule.frequency == "daily"
                        else timedelta(days=7)
                    )
                    continue
                if not replay:
                    schedule.last_run_id = run.id
                    schedule.next_run_at = now + (
                        timedelta(days=1)
                        if schedule.frequency == "daily"
                        else timedelta(days=7)
                    )
                    session.commit()
                    celery_app.send_task(
                        "reckon.execute_crawl",
                        args=[
                            str(schedule.organization_id),
                            str(schedule.website_id),
                            str(run.id),
                            str(schedule.actor_user_id),
                            str(request_id),
                        ],
                    )
                    created += 1
                else:
                    schedule.next_run_at = now + (
                        timedelta(days=1)
                        if schedule.frequency == "daily"
                        else timedelta(days=7)
                    )
                    session.commit()
            session.commit()
        return created
    finally:
        database.dispose()


@celery_app.task(
    name="reckon.execute_crawl",
    bind=False,
    max_retries=0,
)
def execute_crawl(
    organization_id: str,
    website_id: str,
    run_id: str,
    actor_user_id: str,
    request_id: str,
) -> str:
    if (
        not _settings.database_url
        or not _settings.crawl_worker_enabled
    ):
        return "worker_disabled"

    organization = UUID(organization_id)
    website_uuid = UUID(website_id)
    crawl_uuid = UUID(run_id)
    actor = UUID(actor_user_id)
    request_uuid = UUID(request_id)

    engine = _settings.database_url
    from sqlalchemy import create_engine

    database = create_engine(engine.get_secret_value(), pool_pre_ping=True)
    factory = sessionmaker(database, expire_on_commit=False)
    try:
        with factory() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(
                    text("SELECT set_config('app.org_id', :organization_id, true)"),
                    {"organization_id": str(organization)},
                )
            run = session.scalar(
                select(CrawlRun).where(
                    CrawlRun.organization_id == organization,
                    CrawlRun.website_id == website_uuid,
                    CrawlRun.id == crawl_uuid,
                )
            )
            website = session.get(Website, {
                "id": website_uuid,
                "organization_id": organization,
            })
            if (
                run is None
                or website is None
                or not website.is_verified
                or run.status != "running"
            ):
                return "invalid_or_duplicate"
            if SqlAlchemyMembershipRepository(session).role_for_active_membership(
                actor,
                organization,
            ) is None:
                return "membership_revoked"

            crawler = HomepageCrawler()
            try:
                if hasattr(crawler, "crawl_pages"):
                    result = crawler.crawl_pages(website.scheme, website.host)
                else:
                    result = crawler.crawl(website.scheme, website.host)
            except CrawlDisallowed:
                SqlAlchemyCrawlRepository(session).finish(
                    run,
                    actor,
                    request_uuid,
                    status="disallowed",
                    error_code="robots_disallowed",
                )
                session.commit()
                return "disallowed"
            except CrawlPolicyError:
                SqlAlchemyCrawlRepository(session).finish(
                    run,
                    actor,
                    request_uuid,
                    status="failed",
                    error_code="crawl_policy_blocked",
                )
                session.commit()
                return "policy_blocked"
            except CrawlUnavailable:
                SqlAlchemyCrawlRepository(session).finish(
                    run,
                    actor,
                    request_uuid,
                    status="failed",
                    error_code="crawl_unavailable",
                )
                session.commit()
                return "unavailable"

            SqlAlchemyCrawlRepository(session).finish(
                run,
                actor,
                request_uuid,
                status="completed",
                result=result,
                audit=audit_homepage(result),
            )
            session.commit()
            return "completed"
    finally:
        database.dispose()
