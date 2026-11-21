import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

from reckon_api.config import Settings
from reckon_core.model_gateway import (
    ModelExecutionPolicy,
    ModelGateway,
    ModelGatewayRequest,
    ModelMessage,
    ModelProviderResult,
)
from reckon_core.model_usage import ModelReservationRequest, ModelUsageReport
from reckon_core.model_settings import CredentialCipher, SqlAlchemyModelSettingsRepository
from reckon_core.model_usage_repository import (
    ModelBudgetExceeded,
    SqlAlchemyModelUsageRepository,
)
from reckon_core.persistence import (
    AuditEvent,
    ModelUsageReservation,
    NativeAccount,
    Organization,
    OrganizationMembership,
    OrganizationInvitation,
    OrganizationCreationRequest,
    OrganizationModelSettings,
    User,
    Website,
)
from reckon_core.organization_management import OrganizationChangeConflict, OrganizationManagement
from reckon_core.repositories import (
    CrawlBudgetExceeded,
    SqlAlchemyCrawlRepository,
    SqlAlchemyOrganizationRepository,
    utc_day,
)
from reckon_core.tenancy import AuthenticatedPrincipal, OrganizationRole, TenantContext
from reckon_core.tenancy import TenantAccessDenied


def test_postgres_create_organization_is_atomic_and_idempotent() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                role = connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                ).one()
                assert role.rolsuper is False and role.rolbypassrls is False
                with Session(bind=connection) as session:
                    user = User()
                    session.add(user)
                    session.flush()
                    repository = SqlAlchemyOrganizationRepository(session)
                    request_id = uuid4()
                    org_id, role = repository.create_for_owner(
                        user.id, "Organization fixture", "fixture-create-key", request_id,
                    )
                    assert role == OrganizationRole.OWNER
                    assert repository.create_for_owner(
                        user.id, "Organization fixture", "fixture-create-key", uuid4(),
                    ) == (org_id, OrganizationRole.OWNER)
                    assert session.get(Organization, org_id) is not None
                    member = session.get(OrganizationMembership, {"organization_id": org_id, "user_id": user.id})
                    assert member is not None and member.role == OrganizationRole.OWNER
                    assert session.get(OrganizationCreationRequest, {
                        "user_id": user.id, "idempotency_key": "fixture-create-key",
                    }) is not None
                    events = session.scalars(select(AuditEvent).where(AuditEvent.organization_id == org_id)).all()
                    assert len(events) == 1 and events[0].request_id == request_id
            finally:
                transaction.rollback()
            connection.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            assert connection.execute(
                select(Organization.id).where(Organization.id == org_id)
            ).scalar_one_or_none() is None
    finally:
        engine.dispose()


def test_postgres_invitation_discovery_and_membership_versions_are_isolated() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                role = connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                ).one()
                assert role.rolsuper is False and role.rolbypassrls is False
                with Session(bind=connection) as session:
                    owner, recipient, other = User(), User(), User()
                    session.add_all((owner, recipient, other))
                    session.flush()
                    email = f"{uuid4()}@example.com"
                    session.add_all((
                        NativeAccount(user_id=recipient.id, email=email, password_hash="fixture", email_verified=True),
                        NativeAccount(
                            user_id=other.id, email=f"{uuid4()}@example.com",
                            password_hash="fixture", email_verified=True,
                        ),
                    ))
                    org_id = uuid4()
                    session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
                    session.add(Organization(id=org_id, name="Invitation RLS fixture"))
                    session.flush()
                    member = OrganizationMembership(
                        organization_id=org_id, user_id=owner.id, role=OrganizationRole.OWNER, is_active=True,
                    )
                    session.add(member)
                    session.flush()
                    old_version = member.version
                    session.execute(
                        text("UPDATE org_members SET role = role WHERE org_id = :org AND usr_id = :user"),
                        {"org": org_id, "user": owner.id},
                    )
                    session.refresh(member)
                    assert member.version != old_version
                    principal = AuthenticatedPrincipal(owner.id, "fixture", "fixture")
                    context = TenantContext(principal, org_id, OrganizationRole.OWNER)
                    service = OrganizationManagement(session)
                    proposal = service.propose(context, "invite", OrganizationRole.VIEWER, "Invite fixture", "fixture-key", email=email)
                    _, invitation, created = service.approve(context, proposal.id, proposal.approval_hash, uuid4())
                    assert created and invitation is not None
                    session.execute(text("SELECT set_config('app.org_id', '', true)"))
                    session.execute(text("SELECT set_config('app.usr_id', :user, true)"), {"user": str(other.id)})
                    assert session.scalars(select(OrganizationInvitation)).all() == []
                    session.execute(text("SELECT set_config('app.usr_id', :user, true)"), {"user": str(recipient.id)})
                    assert [row.id for row in session.scalars(select(OrganizationInvitation)).all()] == [invitation.id]
                    recipient_principal = AuthenticatedPrincipal(recipient.id, "fixture", "fixture")
                    assert len(service.incoming(recipient_principal)) == 1
                    accepted = service.accept(recipient_principal, invitation.id, uuid4())
                    assert accepted.organization_id == org_id and accepted.role == OrganizationRole.VIEWER
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_postgres_concurrent_approvals_and_acceptance_are_idempotent() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    org_id, owner_id, recipient_id = uuid4(), uuid4(), uuid4()
    email = f"{uuid4()}@example.com"
    try:
        with factory.begin() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            session.add_all((User(id=owner_id), User(id=recipient_id), Organization(id=org_id, name="Invitation concurrency")))
            session.flush()
            session.add_all((
                OrganizationMembership(organization_id=org_id, user_id=owner_id, role=OrganizationRole.OWNER, is_active=True),
                NativeAccount(user_id=recipient_id, email=email, password_hash="fixture", email_verified=True),
            ))
            session.flush()
            owner = AuthenticatedPrincipal(owner_id, "fixture", "fixture")
            context = TenantContext(owner, org_id, OrganizationRole.OWNER)
            proposal = OrganizationManagement(session).propose(
                context, "invite", OrganizationRole.VIEWER, "Invite fixture", "fixture-concurrent-key", email=email,
            )
            change_id, approval_hash = proposal.id, proposal.approval_hash
        barrier = Barrier(2)

        def approve(_: int) -> tuple[UUID, bool]:
            with factory.begin() as session:
                barrier.wait(timeout=10)
                _, invite, created = OrganizationManagement(session).approve(context, change_id, approval_hash, uuid4())
                assert invite is not None
                return invite.id, created

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(approve, range(2)))
        assert results[0][0] == results[1][0]
        assert sorted(created for _, created in results) == [False, True]
        invite_id = results[0][0]
        barrier = Barrier(2)

        def accept(_: int) -> UUID:
            with factory.begin() as session:
                barrier.wait(timeout=10)
                principal = AuthenticatedPrincipal(recipient_id, "fixture", "fixture")
                return OrganizationManagement(session).accept(principal, invite_id, uuid4()).organization_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert list(executor.map(accept, range(2))) == [org_id, org_id]
        with factory() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            actions = session.scalars(select(AuditEvent.action).where(AuditEvent.organization_id == org_id)).all()
            assert actions.count("organization.invite") == 1
            assert actions.count("organization.invitation_accepted") == 1
    finally:
        with factory.begin() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            session.execute(delete(Organization).where(Organization.id == org_id))
            session.execute(delete(User).where(User.id.in_((owner_id, recipient_id))))
        engine.dispose()


def test_postgres_concurrent_demotions_preserve_an_owner() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    org_id, first, second = uuid4(), uuid4(), uuid4()
    try:
        with factory.begin() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            session.add_all((User(id=first), User(id=second), Organization(id=org_id, name="Owner concurrency")))
            session.flush()
            session.add_all((
                OrganizationMembership(organization_id=org_id, user_id=first, role=OrganizationRole.OWNER, is_active=True),
                OrganizationMembership(organization_id=org_id, user_id=second, role=OrganizationRole.OWNER, is_active=True),
            ))
            session.flush()
            context = TenantContext(AuthenticatedPrincipal(first, "fixture", "fixture"), org_id, OrganizationRole.OWNER)
            service = OrganizationManagement(session)
            proposals = [
                service.propose(context, "role_change", OrganizationRole.VIEWER, "Demote fixture", f"fixture-key-{i}", user_id=target)
                for i, target in enumerate((first, second))
            ]
            approvals = [(item.id, item.approval_hash) for item in proposals]
        barrier = Barrier(2)

        def approve(item: tuple[UUID, str]) -> str:
            try:
                with factory.begin() as session:
                    barrier.wait(timeout=10)
                    OrganizationManagement(session).approve(context, item[0], item[1], uuid4())
                return "approved"
            except (OrganizationChangeConflict, TenantAccessDenied):
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(approve, approvals)) == ["approved", "denied"]
        with factory() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            roles = session.scalars(select(OrganizationMembership.role).where(OrganizationMembership.organization_id == org_id)).all()
            assert roles.count(OrganizationRole.OWNER) == 1
    finally:
        with factory.begin() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            session.execute(delete(Organization).where(Organization.id == org_id))
            session.execute(delete(User).where(User.id.in_((first, second))))
        engine.dispose()


def test_postgres_manager_lock_refreshes_stale_authorization() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    org_id, manager_id = uuid4(), uuid4()
    try:
        with factory.begin() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            session.add_all((User(id=manager_id), Organization(id=org_id, name="Manager refresh fixture")))
            session.flush()
            session.add(OrganizationMembership(
                organization_id=org_id, user_id=manager_id, role=OrganizationRole.ADMIN, is_active=True,
            ))
        with factory() as stale_session:
            stale_session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            cached = stale_session.get(OrganizationMembership, {"organization_id": org_id, "user_id": manager_id})
            assert cached is not None and cached.role == OrganizationRole.ADMIN
            with factory.begin() as other_session:
                other_session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
                member = other_session.get(OrganizationMembership, {"organization_id": org_id, "user_id": manager_id})
                assert member is not None
                member.role = OrganizationRole.VIEWER
            context = TenantContext(AuthenticatedPrincipal(manager_id, "fixture", "fixture"), org_id, OrganizationRole.ADMIN)
            with pytest.raises(TenantAccessDenied):
                OrganizationManagement(stale_session).propose(
                    context, "invite", OrganizationRole.VIEWER, "Invite fixture", "fixture-key", email="test@example.com",
                )
    finally:
        with factory.begin() as session:
            session.execute(text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)})
            session.execute(delete(Organization).where(Organization.id == org_id))
            session.execute(delete(User).where(User.id == manager_id))
        engine.dispose()


def test_postgres_member_roster_is_tenant_scoped_and_manager_only() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                role = connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                ).one()
                assert role.rolsuper is False and role.rolbypassrls is False
                with Session(bind=connection) as session:
                    actor, member, outsider = User(), User(), User()
                    session.add_all((actor, member, outsider))
                    session.flush()
                    first, second = uuid4(), uuid4()
                    for org_id, name in ((first, "roster-first"), (second, "roster-second")):
                        session.execute(
                            text("SELECT set_config('app.org_id', :org_id, true)"),
                            {"org_id": str(org_id)},
                        )
                        session.add(Organization(id=org_id, name=name))
                        session.flush()
                        if org_id == first:
                            session.add_all((
                                OrganizationMembership(
                                    organization_id=first, user_id=actor.id,
                                    role=OrganizationRole.ADMIN, is_active=True,
                                ),
                                OrganizationMembership(
                                    organization_id=first, user_id=member.id,
                                    role=OrganizationRole.VIEWER, is_active=True,
                                ),
                                NativeAccount(user_id=member.id, email=f"{uuid4()}@example.com", password_hash="fixture"),
                            ))
                        else:
                            session.add(OrganizationMembership(
                                organization_id=second, user_id=outsider.id,
                                role=OrganizationRole.OWNER, is_active=True,
                            ))
                        session.flush()
                    context = TenantContext(
                        AuthenticatedPrincipal(actor.id, "fixture", "fixture"), first, OrganizationRole.ADMIN
                    )
                    rows, cursor = SqlAlchemyOrganizationRepository(session).list_members(context, 50, None)
                    assert cursor is None
                    assert {row[0] for row in rows} == {actor.id, member.id}
                    assert outsider.id not in {row[0] for row in rows}
                    actor_membership = session.get(OrganizationMembership, {
                        "organization_id": first, "user_id": actor.id,
                    })
                    assert actor_membership is not None
                    actor_membership.role = OrganizationRole.EDITOR
                    session.flush()
                    with pytest.raises(TenantAccessDenied):
                        SqlAlchemyOrganizationRepository(session).list_members(context, 50, None)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_postgres_rls_isolates_organization_rows() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")

    engine = create_engine(settings.database_url.get_secret_value())
    first_id, second_id = str(uuid4()), str(uuid4())

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                role = connection.execute(
                    text(
                        """
                        SELECT r.rolsuper, r.rolbypassrls
                        FROM pg_roles AS r
                        WHERE r.rolname = current_user
                        """
                    )
                ).one()
                assert role.rolsuper is False
                assert role.rolbypassrls is False

                guarded_tables = {
                    row.relname: (row.relrowsecurity, row.relforcerowsecurity)
                    for row in connection.execute(
                        text(
                            """
                            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                            FROM pg_class AS c
                            JOIN pg_namespace AS n ON n.oid = c.relnamespace
                            WHERE n.nspname = current_schema()
                              AND c.relname IN (
                                  'sites', 'site_create_reqs', 'site_crawl_runs', 'model_usage',
                                  'org_model_settings'
                              )
                            """
                        )
                    )
                }
                assert guarded_tables == {
                    "sites": (True, True),
                    "site_create_reqs": (True, True),
                    "site_crawl_runs": (True, True),
                    "model_usage": (True, True),
                    "org_model_settings": (True, True),
                }

                for organization_id, name in (
                    (first_id, "rls-check-a"),
                    (second_id, "rls-check-b"),
                ):
                    user_id = str(uuid4())
                    connection.execute(
                        text(
                            """
                            INSERT INTO users (id, created_at)
                            VALUES (CAST(:user_id AS uuid), now())
                            """
                        ),
                        {"user_id": user_id},
                    )
                    connection.execute(
                        text("SELECT set_config('app.org_id', :org_id, true)"),
                        {"org_id": organization_id},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO orgs (id, name, created_at)
                            VALUES (CAST(:org_id AS uuid), :name, now())
                            """
                        ),
                        {"org_id": organization_id, "name": name},
                    )
                    site_id = str(uuid4())
                    connection.execute(
                        text(
                            """
                            INSERT INTO sites (
                                id, org_id, host, scheme, verified, ver_tok,
                                created_at, verified_at
                            )
                            VALUES (
                                CAST(:site_id AS uuid), CAST(:org_id AS uuid),
                                :host, 'https', false, 'rls-test-token', now(), NULL
                            )
                            """
                        ),
                        {
                            "site_id": site_id,
                            "org_id": organization_id,
                            "host": f"{name}.example.org",
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO org_model_settings (org_id, provider, model, key_cipher, updated_at)
                            VALUES (CAST(:org_id AS uuid), 'openai', :model, decode('00', 'hex'), now())
                            """
                        ),
                        {"org_id": organization_id, "model": name},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO model_usage (
                                id, org_id, actor_usr_id, task_id, req_id, idem_key,
                                req_hash, provider, model, max_input, max_output,
                                status, started_at
                            )
                            VALUES (
                                CAST(:id AS uuid), CAST(:org_id AS uuid), CAST(:user_id AS uuid),
                                CAST(:task_id AS uuid), CAST(:request_id AS uuid), :idem_key,
                                repeat('a', 64), 'test-provider', 'test-model', 50, 50,
                                'reserved', now()
                            )
                            """
                        ),
                        {
                            "id": str(uuid4()),
                            "org_id": organization_id,
                            "user_id": user_id,
                            "task_id": str(uuid4()),
                            "request_id": str(uuid4()),
                            "idem_key": f"model-{name}",
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO site_create_reqs (org_id, idem_key, req_hash, site_id)
                            VALUES (
                                CAST(:org_id AS uuid), :idem_key, repeat('a', 64),
                                CAST(:site_id AS uuid)
                            )
                            """
                        ),
                        {
                            "org_id": organization_id,
                            "idem_key": f"rls-{name}",
                            "site_id": site_id,
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO site_crawl_runs (
                                id, org_id, site_id, actor_usr_id, req_id, idem_key,
                                req_hash, status, started_at
                            )
                            VALUES (
                                CAST(:run_id AS uuid), CAST(:org_id AS uuid),
                                CAST(:site_id AS uuid), CAST(:user_id AS uuid),
                                CAST(:request_id AS uuid), :idem_key, repeat('b', 64),
                                'running', now()
                            )
                            """
                        ),
                        {
                            "run_id": str(uuid4()),
                            "org_id": organization_id,
                            "site_id": site_id,
                            "user_id": user_id,
                            "request_id": str(uuid4()),
                            "idem_key": f"crawl-{name}",
                        },
                    )

                connection.execute(
                    text("SELECT set_config('app.org_id', :org_id, true)"),
                    {"org_id": first_id},
                )
                visible = connection.execute(
                    text("SELECT id::text, name FROM orgs ORDER BY name")
                ).all()
                assert [(row.id, row.name) for row in visible] == [
                    (first_id, "rls-check-a")
                ]
                assert connection.execute(
                    text("SELECT host FROM sites")
                ).scalars().all() == ["rls-check-a.example.org"]
                assert connection.execute(
                    text("SELECT idem_key FROM site_create_reqs")
                ).scalars().all() == ["rls-rls-check-a"]
                assert connection.execute(
                    text("SELECT idem_key FROM site_crawl_runs")
                ).scalars().all() == ["crawl-rls-check-a"]
                assert connection.execute(
                    text("SELECT idem_key FROM model_usage")
                ).scalars().all() == ["model-rls-check-a"]
                assert connection.execute(
                    text("SELECT model FROM org_model_settings")
                ).scalars().all() == ["rls-check-a"]
                with connection.begin_nested() as savepoint:
                    with pytest.raises(DBAPIError):
                        connection.execute(
                            text(
                                """
                                UPDATE model_usage SET org_id = CAST(:other_org AS uuid)
                                WHERE idem_key = 'model-rls-check-a'
                                """
                            ),
                            {"other_org": second_id},
                        )
                    savepoint.rollback()
                with connection.begin_nested() as savepoint:
                    with pytest.raises(DBAPIError):
                        connection.execute(
                            text(
                                "UPDATE org_model_settings SET org_id = CAST(:other_org AS uuid)"
                            ),
                            {"other_org": second_id},
                        )
                    savepoint.rollback()

                connection.execute(
                    text("SELECT set_config('app.org_id', '', true)")
                )
                assert connection.execute(
                    text("SELECT count(*) FROM orgs")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM sites")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM site_create_reqs")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM site_crawl_runs")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM model_usage")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM org_model_settings")
                ).scalar_one() == 0
            finally:
                transaction.rollback()

            assert connection.execute(
                text("SELECT count(*) FROM orgs")
            ).scalar_one() == 0
    finally:
        engine.dispose()


def test_postgres_membership_discovery_is_user_scoped_and_read_only() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    first, second, inactive = uuid4(), uuid4(), uuid4()
    user, other_user = uuid4(), uuid4()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                factory = sessionmaker(bind=connection, expire_on_commit=False)
                with factory() as session:
                    session.add_all((User(id=user), User(id=other_user)))
                    session.flush()
                    for organization_id in (first, second, inactive):
                        session.execute(
                            text("SELECT set_config('app.org_id', :org_id, true)"),
                            {"org_id": str(organization_id)},
                        )
                        session.add(Organization(id=organization_id, name=f"org-{organization_id}"))
                        session.flush()
                        session.add(OrganizationMembership(
                            organization_id=organization_id, user_id=user,
                            role=OrganizationRole.EDITOR, is_active=organization_id != inactive,
                        ))
                        if organization_id == first:
                            session.add(OrganizationMembership(
                                organization_id=organization_id, user_id=other_user,
                                role=OrganizationRole.OWNER, is_active=True,
                            ))
                        session.flush()
                    repository = SqlAlchemyOrganizationRepository(session)
                    rows, cursor = repository.list_for_user(user, 1, None)
                    assert len(rows) == 1 and cursor is not None
                    next_rows, next_cursor = repository.list_for_user(user, 1, cursor)
                    assert next_cursor is None
                    assert {row[0] for row in rows + next_rows} == {first, second}
                    session.execute(text("SELECT set_config('app.org_id', '', true)"))
                    visible = session.execute(text("SELECT org_id, usr_id FROM org_members")).all()
                    assert {(row.org_id, row.usr_id) for row in visible} == {
                        (first, user), (second, user)
                    }
                    assert session.execute(text("SELECT count(*) FROM orgs")).scalar_one() == 0
                    updated = session.execute(text("UPDATE org_members SET role = 'owner'"))
                    assert updated.rowcount == 0
                    session.execute(
                        text("SELECT set_config('app.org_id', :org_id, true)"),
                        {"org_id": str(first)},
                    )
                    visible_ids = session.execute(text("SELECT usr_id FROM org_members")).scalars().all()
                    assert set(visible_ids) == {user, other_user}
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_postgres_model_settings_repository_uses_tenant_scope() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    organization_id, user_id = uuid4(), uuid4()
    context = TenantContext(
        AuthenticatedPrincipal(user_id, "test-issuer", "test-subject"),
        organization_id,
        OrganizationRole.OWNER,
    )
    cipher = CredentialCipher(SecretStr(base64.urlsafe_b64encode(b"p" * 32).decode()))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                factory = sessionmaker(bind=connection, expire_on_commit=False)
                with factory() as session:
                    session.execute(
                        text("SELECT set_config('app.org_id', :org_id, true)"),
                        {"org_id": str(organization_id)},
                    )
                    session.add_all((User(id=user_id), Organization(id=organization_id, name="settings test")))
                    session.flush()
                    session.add(OrganizationMembership(
                        organization_id=organization_id, user_id=user_id,
                        role=OrganizationRole.OWNER, is_active=True,
                    ))
                    session.flush()
                    repository = SqlAlchemyModelSettingsRepository(session)
                    stored = repository.save(
                        context, uuid4(), "anthropic", "fixture-model", SecretStr("fake-key"), cipher,
                        "https://proxy.example.com/v1",
                    )
                    session.commit()
                    assert cipher.decrypt(stored.encrypted_key, organization_id, "anthropic").get_secret_value() == "fake-key"
                    fetched = repository.get(context)
                    assert fetched is not None and fetched.endpoint_url == "https://proxy.example.com/v1"
                    session.execute(text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": str(uuid4())})
                    assert session.scalars(select(OrganizationModelSettings)).all() == []
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_postgres_concurrent_crawl_reservations_respect_daily_limit() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")

    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    organization_id = uuid4()
    actor_user_id = uuid4()
    website_id = uuid4()

    try:
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            session.add_all(
                (
                    User(id=actor_user_id),
                    Organization(id=organization_id, name="crawl concurrency test"),
                    Website(
                        id=website_id,
                        organization_id=organization_id,
                        host=f"{website_id.hex}.example.org",
                        scheme="https",
                        is_verified=True,
                        verification_token="test-token",
                    ),
                )
            )
            session.commit()

        barrier = Barrier(2)

        def reserve(key: str) -> str:
            with factory() as session:
                try:
                    barrier.wait(timeout=10)
                    SqlAlchemyCrawlRepository(session).reserve(
                        organization_id=organization_id,
                        website_id=website_id,
                        actor_user_id=actor_user_id,
                        request_id=uuid4(),
                        idempotency_key=key,
                        daily_limit=1,
                    )
                    session.commit()
                    return "reserved"
                except CrawlBudgetExceeded:
                    session.rollback()
                    return "over_budget"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(reserve, ("concurrent-crawl-001", "concurrent-crawl-002"))
            )

        assert sorted(outcomes) == ["over_budget", "reserved"]
        with factory() as session:
            repository = SqlAlchemyCrawlRepository(session)
            start, end = utc_day(datetime.now(timezone.utc))
            assert repository.count_for_period(organization_id, start, end) == 1
            assert repository.count_for_period(uuid4(), start, end) == 0
    finally:
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            session.execute(
                delete(Organization).where(Organization.id == organization_id)
            )
            session.execute(delete(User).where(User.id == actor_user_id))
            session.commit()
        engine.dispose()


def test_postgres_concurrent_model_reservations_respect_budget() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    organization_id, user_id = uuid4(), uuid4()
    context = TenantContext(
        AuthenticatedPrincipal(user_id, "test-issuer", "test-subject"),
        organization_id,
        OrganizationRole.OWNER,
    )
    try:
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            session.add_all(
                (User(id=user_id), Organization(id=organization_id, name="model usage concurrency test"))
            )
            session.flush()
            session.add(
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=user_id,
                    role=OrganizationRole.OWNER,
                    is_active=True,
                )
            )
            session.commit()

        barrier = Barrier(2)

        def reserve(key: str) -> str:
            with factory() as session:
                try:
                    barrier.wait(timeout=10)
                    SqlAlchemyModelUsageRepository(session).reserve(
                        context,
                        ModelReservationRequest(
                            task_id=uuid4(),
                            request_id=uuid4(),
                            idempotency_key=key,
                            provider="test-provider",
                            model="test-model",
                            request_digest="a" * 64,
                            max_input_tokens=60,
                            max_output_tokens=40,
                        ),
                        daily_token_limit=100,
                    )
                    session.commit()
                    return "reserved"
                except ModelBudgetExceeded:
                    session.rollback()
                    return "over_budget"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(reserve, ("concurrent-model-001", "concurrent-model-002"))
            )
        assert sorted(outcomes) == ["over_budget", "reserved"]
    finally:
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            session.execute(delete(Organization).where(Organization.id == organization_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
        engine.dispose()


def test_postgres_gateway_persists_usage_before_returning() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")
    engine = create_engine(settings.database_url.get_secret_value())
    factory = sessionmaker(engine, expire_on_commit=False)
    organization_id, user_id = uuid4(), uuid4()
    context = TenantContext(
        AuthenticatedPrincipal(user_id, "test-issuer", "test-subject"),
        organization_id,
        OrganizationRole.EDITOR,
    )

    class TestAuthorizer:
        def authorize(
            self, context: TenantContext, task_id: UUID, request: ModelGatewayRequest
        ) -> ModelExecutionPolicy:
            return ModelExecutionPolicy(
                provider="fixture", model="fixture-model", daily_token_limit=100,
                max_input_tokens=60, max_output_tokens=40, timeout_seconds=1.0,
            )

    class TestAdapter:
        binding_version = "fixture-v1"

        def input_token_upper_bound(self, request: ModelGatewayRequest) -> int:
            return 10

        async def complete(
            self,
            request: ModelGatewayRequest,
            policy: ModelExecutionPolicy,
            timeout_seconds: float,
        ) -> ModelProviderResult:
            with factory() as session:
                session.execute(
                    text("SELECT set_config('app.org_id', :org_id, true)"),
                    {"org_id": str(organization_id)},
                )
                reservation = session.scalar(select(ModelUsageReservation))
                assert reservation is not None and reservation.status == "reserved"
            return ModelProviderResult(
                text="Fixture response",
                usage=ModelUsageReport(input_tokens=12, output_tokens=8),
            )

    try:
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            session.add_all((User(id=user_id), Organization(id=organization_id, name="gateway test")))
            session.flush()
            session.add(
                OrganizationMembership(
                    organization_id=organization_id,
                    user_id=user_id,
                    role=OrganizationRole.EDITOR,
                    is_active=True,
                )
            )
            session.commit()

        gateway = ModelGateway(factory, TestAuthorizer(), {"fixture": TestAdapter()}, 1)
        result = asyncio.run(
            gateway.execute(
                context, uuid4(), uuid4(), "postgres-gateway-001",
                ModelGatewayRequest(
                    provider="fixture",
                    model="fixture-model",
                    system_prompt="Authorized test",
                    messages=(ModelMessage(role="user", content="Fixture input"),),
                ),
            )
        )
        assert result.text == "Fixture response"
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            reservation = session.scalar(select(ModelUsageReservation))
            assert reservation is not None
            assert (reservation.status, reservation.input_tokens, reservation.output_tokens) == (
                "settled", 12, 8
            )
    finally:
        with factory() as session:
            session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(organization_id)},
            )
            session.execute(delete(Organization).where(Organization.id == organization_id))
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
        engine.dispose()
