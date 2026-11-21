from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from reckon_core.model_usage import ModelReservationRequest, ModelUsageReport
from reckon_core.model_usage_repository import (
    ModelBudgetExceeded,
    ModelReservationNotFound,
    ModelUsageConflict,
    SqlAlchemyModelUsageRepository,
)
from reckon_core.persistence import (
    AuditEvent,
    Base,
    ModelUsageReservation,
    Organization,
    OrganizationMembership,
    User,
)
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantContext,
)


@pytest.fixture
def ledger() -> Iterator[tuple[sessionmaker[Session], TenantContext, TenantContext]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        user = User()
        organizations = [Organization(name="First"), Organization(name="Second")]
        session.add_all([user, *organizations])
        session.flush()
        for organization in organizations:
            session.add(
                OrganizationMembership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role=OrganizationRole.OWNER,
                    is_active=True,
                )
            )
        principal = AuthenticatedPrincipal(user.id, "issuer", "subject")
        contexts = [
            TenantContext(principal, organization.id, OrganizationRole.OWNER)
            for organization in organizations
        ]
        session.commit()
    try:
        yield factory, contexts[0], contexts[1]
    finally:
        engine.dispose()


def request(key: str = "model-request-001") -> ModelReservationRequest:
    return ModelReservationRequest(
        task_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=key,
        provider="provider",
        model="model-v1",
        request_digest="a" * 64,
        max_input_tokens=60,
        max_output_tokens=40,
    )


def test_reservations_are_idempotent_bound_and_transactional(
    ledger: tuple[sessionmaker[Session], TenantContext, TenantContext],
) -> None:
    factory, context, _ = ledger
    initial = request()
    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        first, replay = repository.reserve(context, initial, 100)
        assert replay is False
        session.commit()
        same, replay = repository.reserve(
            context, initial.model_copy(update={"request_id": uuid4()}), 100
        )
        assert replay is True
        assert same.id == first.id
        with pytest.raises(IdempotencyConflict):
            repository.reserve(
                context, initial.model_copy(update={"request_digest": "b" * 64}), 100
            )
        with pytest.raises(ModelBudgetExceeded):
            repository.reserve(context, request("model-request-002"), 100)
        session.rollback()
        assert session.scalar(select(func.count(ModelUsageReservation.id))) == 1
        assert session.scalar(select(func.count(AuditEvent.id))) == 1

    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        repository.reserve(context, request("rolled-back-001"), 200)
        session.rollback()
        assert session.scalar(select(func.count(ModelUsageReservation.id))) == 1


def test_unresolved_reservations_carry_forward_and_settlement_is_idempotent(
    ledger: tuple[sessionmaker[Session], TenantContext, TenantContext],
) -> None:
    factory, context, _ = ledger
    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        reservation, _ = repository.reserve(context, request(), 100)
        reservation.started_at = datetime.now(timezone.utc) - timedelta(days=2)
        session.commit()
        with pytest.raises(ModelBudgetExceeded):
            repository.reserve(context, request("model-request-002"), 100)
        report = ModelUsageReport(input_tokens=20, output_tokens=10)
        settled = repository.settle(context, reservation.id, uuid4(), report)
        assert (settled.input_tokens, settled.output_tokens) == (20, 10)
        session.commit()
        repository.settle(context, reservation.id, uuid4(), report)
        with pytest.raises(ModelUsageConflict):
            repository.settle(
                context, reservation.id, uuid4(), ModelUsageReport(input_tokens=21, output_tokens=10)
            )
        _, replay = repository.reserve(context, request("model-request-002"), 100)
        assert replay is False
        session.commit()
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.action == "model_usage.settled")
        ) == 1


def test_provider_overage_is_recorded_and_blocks_future_reservations(
    ledger: tuple[sessionmaker[Session], TenantContext, TenantContext],
) -> None:
    factory, context, _ = ledger
    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        reservation, _ = repository.reserve(context, request(), 100)
        session.commit()
        repository.settle(
            context, reservation.id, uuid4(), ModelUsageReport(input_tokens=120, output_tokens=20)
        )
        session.commit()
        with pytest.raises(ModelBudgetExceeded):
            repository.reserve(context, request("model-request-002"), 100)
        assert reservation.input_tokens == 120


def test_same_day_settlement_releases_only_unused_reservation(
    ledger: tuple[sessionmaker[Session], TenantContext, TenantContext],
) -> None:
    factory, context, _ = ledger
    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        first, _ = repository.reserve(context, request(), 100)
        session.commit()
        repository.settle(context, first.id, uuid4(), ModelUsageReport(input_tokens=20, output_tokens=10))
        session.commit()
        next_request = request("model-request-002").model_copy(
            update={"max_input_tokens": 40, "max_output_tokens": 30}
        )
        repository.reserve(context, next_request, 100)
        session.commit()
        with pytest.raises(ModelBudgetExceeded):
            repository.reserve(context, request("model-request-003"), 100)


def test_ledger_requires_membership_and_does_not_cross_tenants(
    ledger: tuple[sessionmaker[Session], TenantContext, TenantContext],
) -> None:
    factory, first, second = ledger
    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        first_request = request()
        first_run, _ = repository.reserve(first, first_request, 100)
        session.commit()
        second_run, _ = repository.reserve(second, request(), 100)
        assert first_run.id != second_run.id
        session.commit()
        with pytest.raises(ModelReservationNotFound):
            repository.settle(second, first_run.id, uuid4(), ModelUsageReport(input_tokens=1, output_tokens=1))
        with pytest.raises(ModelReservationNotFound):
            repository.record_unknown(second, first_run.id, uuid4(), "timeout", 10)
        another_user = User()
        session.add(another_user)
        session.flush()
        session.add(
            OrganizationMembership(
                organization_id=first.organization_id,
                user_id=another_user.id,
                role=OrganizationRole.EDITOR,
                is_active=True,
            )
        )
        session.commit()
        another_member = TenantContext(
            AuthenticatedPrincipal(another_user.id, "issuer", "another-member"),
            first.organization_id,
            OrganizationRole.EDITOR,
        )
        with pytest.raises(ModelReservationNotFound):
            repository.settle(another_member, first_run.id, uuid4(), ModelUsageReport(input_tokens=1, output_tokens=1))
        with pytest.raises(ModelReservationNotFound):
            repository.record_unknown(another_member, first_run.id, uuid4(), "timeout", 10)
        with pytest.raises(IdempotencyConflict):
            repository.reserve(another_member, first_request, 100)
        stranger = TenantContext(
            AuthenticatedPrincipal(uuid4(), "issuer", "other"),
            first.organization_id,
            OrganizationRole.OWNER,
        )
        with pytest.raises(TenantAccessDenied):
            repository.reserve(stranger, request("unauthorized-001"), 100)
        membership = session.get(
            OrganizationMembership,
            {"organization_id": first.organization_id, "user_id": first.principal.user_id},
        )
        assert membership is not None
        membership.is_active = False
        session.commit()
        with pytest.raises(TenantAccessDenied):
            repository.reserve(first, request("inactive-user-001"), 100)


def test_usage_inputs_reject_invalid_limits_and_reports() -> None:
    with pytest.raises(ValidationError):
        ModelUsageReport(input_tokens=-1, output_tokens=0)
    with pytest.raises(ValidationError):
        ModelUsageReport(input_tokens=True, output_tokens=0)
    with pytest.raises(ValidationError):
        ModelReservationRequest(
            task_id=uuid4(),
            request_id=uuid4(),
            idempotency_key="short",
            provider="provider",
            model="model",
            request_digest="bad",
            max_input_tokens=0,
            max_output_tokens=1,
        )


def test_unknown_usage_requires_prior_evidence_and_explicit_reconciliation(
    ledger: tuple[sessionmaker[Session], TenantContext, TenantContext],
) -> None:
    factory, context, _ = ledger
    with factory() as session:
        repository = SqlAlchemyModelUsageRepository(session)
        reservation, _ = repository.reserve(context, request("unknown-request-001"), 100)
        session.commit()

        with pytest.raises(ModelUsageConflict):
            repository.reconcile_unknown(
                context,
                reservation.id,
                uuid4(),
                ModelUsageReport(input_tokens=20, output_tokens=10),
                "provider-verification-result-1",
            )

        repository.record_unknown(
            context,
            reservation.id,
            uuid4(),
            "adapter_error",
            125,
        )
        reconciled = repository.reconcile_unknown(
            context,
            reservation.id,
            uuid4(),
            ModelUsageReport(input_tokens=20, output_tokens=10),
            "provider-verification-result-1",
        )
        session.commit()
        assert reconciled.status == "settled"
        assert (reconciled.input_tokens, reconciled.output_tokens) == (20, 10)

        rows = repository.list_for_organization(context)
        assert len(rows) == 1
        assert rows[0].status == "settled"
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "model_usage.reconciled"
            )
        ) == 1
