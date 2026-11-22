import hashlib
import hmac
import json
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from reckon_core.model_usage import ModelReservationRequest, ModelUsageReport
from reckon_core.persistence import (
    AuditEvent,
    ModelUsageReservation,
    Organization,
    OrganizationMembership,
)
from reckon_core.repositories import (
    IdempotencyConflict,
    SqlAlchemyMembershipRepository,
    utc_day,
)
from reckon_core.tenancy import TenantAccessDenied, TenantContext
from reckon_core.permissions import OrganizationPermission, require_permission

UnknownReason = Literal[
    "timeout", "adapter_error", "adapter_cancelled", "invalid_result", "caller_cancelled"
]


class ModelBudgetExceeded(ValueError):
    pass


class ModelReservationNotFound(LookupError):
    pass


class ModelUsageConflict(ValueError):
    pass


class SqlAlchemyModelUsageRepository:
    """Internal ledger; the caller owns transaction commit and provider verification."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._is_postgresql = session.get_bind().dialect.name == "postgresql"

    def _lock_organization(self, context: TenantContext) -> None:
        role = SqlAlchemyMembershipRepository(self._session).role_for_active_membership(
            context.principal.user_id, context.organization_id
        )
        if role is None or role != context.role:
            raise TenantAccessDenied
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(context.organization_id)},
            )
        found = self._session.scalar(
            select(Organization.id)
            .where(Organization.id == context.organization_id)
            .with_for_update()
        )
        if found is None:
            raise TenantAccessDenied
        membership = self._session.execute(
            select(OrganizationMembership.is_active, OrganizationMembership.role)
            .where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.user_id == context.principal.user_id,
            )
            .with_for_update()
        ).one_or_none()
        if membership is None or membership.is_active is not True or membership.role != context.role:
            raise TenantAccessDenied

    def reserve(
        self,
        context: TenantContext,
        request: ModelReservationRequest,
        daily_token_limit: int,
        reservation_check: Callable[[Session, TenantContext], None] | None = None,
    ) -> tuple[ModelUsageReservation, bool]:
        """Commit a new reservation before dispatch; a replay never authorizes dispatch."""
        if type(daily_token_limit) is not int or daily_token_limit <= 0:
            raise ValueError("The daily token limit must be a positive integer.")
        self._lock_organization(context)
        if reservation_check is not None:
            reservation_check(self._session, context)
        digest = hashlib.sha256(
            json.dumps(
                [
                    str(context.principal.user_id),
                    str(request.task_id),
                    request.provider,
                    request.model,
                    request.request_digest,
                    request.max_input_tokens,
                    request.max_output_tokens,
                ],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        existing = self._session.scalar(
            select(ModelUsageReservation)
            .where(
                ModelUsageReservation.organization_id == context.organization_id,
                ModelUsageReservation.idempotency_key == request.idempotency_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if not hmac.compare_digest(existing.request_hash, digest):
                raise IdempotencyConflict
            return existing, True

        now = datetime.now(timezone.utc)
        day_start, day_end = utc_day(now)
        charged = self._session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ModelUsageReservation.status == "reserved",
                                ModelUsageReservation.max_input_tokens
                                + ModelUsageReservation.max_output_tokens,
                            ),
                            else_=ModelUsageReservation.input_tokens
                            + ModelUsageReservation.output_tokens,
                        )
                    ),
                    0,
                )
            ).where(
                ModelUsageReservation.organization_id == context.organization_id,
                or_(
                    ModelUsageReservation.status == "reserved",
                    (
                        (ModelUsageReservation.started_at >= day_start)
                        & (ModelUsageReservation.started_at < day_end)
                    ),
                ),
            )
        )
        if charged is None:
            raise RuntimeError("The model token budget could not be calculated.")
        if charged + request.max_input_tokens + request.max_output_tokens > daily_token_limit:
            raise ModelBudgetExceeded

        reservation = ModelUsageReservation(
            id=uuid4(),
            organization_id=context.organization_id,
            actor_user_id=context.principal.user_id,
            task_id=request.task_id,
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            request_hash=digest,
            provider=request.provider,
            model=request.model,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            status="reserved",
            started_at=now,
        )
        self._session.add(reservation)
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="model_usage.reserved",
                resource_type="model_usage",
                resource_id=reservation.id,
                request_id=request.request_id,
                details={
                    "task_id": str(request.task_id),
                    "max_input": str(request.max_input_tokens),
                    "max_output": str(request.max_output_tokens),
                },
            )
        )
        self._session.flush()
        return reservation, False

    def settle(
        self,
        context: TenantContext,
        reservation_id: UUID,
        request_id: UUID,
        report: ModelUsageReport,
    ) -> ModelUsageReservation:
        """Record a report verified by the caller; unknown outcomes stay reserved."""
        self._lock_organization(context)
        reservation = self._session.scalar(
            select(ModelUsageReservation)
            .where(
                ModelUsageReservation.organization_id == context.organization_id,
                ModelUsageReservation.id == reservation_id,
                ModelUsageReservation.actor_user_id == context.principal.user_id,
            )
            .with_for_update()
        )
        if reservation is None:
            raise ModelReservationNotFound
        if reservation.status == "settled":
            if (
                reservation.input_tokens != report.input_tokens
                or reservation.output_tokens != report.output_tokens
            ):
                raise ModelUsageConflict
            return reservation
        if reservation.status != "reserved":
            raise RuntimeError("The model usage reservation has an invalid status.")
        reservation.status = "settled"
        reservation.input_tokens = report.input_tokens
        reservation.output_tokens = report.output_tokens
        reservation.settled_at = datetime.now(timezone.utc)
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="model_usage.settled",
                resource_type="model_usage",
                resource_id=reservation.id,
                request_id=request_id,
                details={
                    "task_id": str(reservation.task_id),
                    "input_tokens": str(report.input_tokens),
                    "output_tokens": str(report.output_tokens),
                },
            )
        )
        self._session.flush()
        return reservation

    def record_unknown(
        self,
        context: TenantContext,
        reservation_id: UUID,
        request_id: UUID,
        reason: UnknownReason,
        elapsed_ms: int,
    ) -> None:
        if reason not in {
            "timeout", "adapter_error", "adapter_cancelled", "invalid_result", "caller_cancelled"
        } or type(elapsed_ms) is not int or elapsed_ms < 0:
            raise ValueError("Invalid unknown outcome details.")
        self._lock_organization(context)
        reservation = self._session.scalar(
            select(ModelUsageReservation)
            .where(
                ModelUsageReservation.organization_id == context.organization_id,
                ModelUsageReservation.id == reservation_id,
                ModelUsageReservation.actor_user_id == context.principal.user_id,
            )
            .with_for_update()
        )
        if reservation is None:
            raise ModelReservationNotFound
        if reservation.status != "reserved":
            raise ModelUsageConflict
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="model_usage.outcome_unknown",
                resource_type="model_usage",
                resource_id=reservation.id,
                request_id=request_id,
                details={
                    "task_id": str(reservation.task_id),
                    "reason": reason,
                    "elapsed_ms": str(elapsed_ms),
                },
            )
        )
        self._session.flush()

    def list_for_organization(
        self,
        context: TenantContext,
        limit: int = 100,
    ) -> list[ModelUsageReservation]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("The usage page size must be between 1 and 100.")
        require_permission(context.role, OrganizationPermission.AI_USAGE_VIEW)
        self._lock_organization(context)
        return list(
            self._session.scalars(
                select(ModelUsageReservation)
                .where(ModelUsageReservation.organization_id == context.organization_id)
                .order_by(
                    ModelUsageReservation.started_at.desc(),
                    ModelUsageReservation.id.desc(),
                )
                .limit(limit)
            )
        )

    def reconcile_unknown(
        self,
        context: TenantContext,
        reservation_id: UUID,
        request_id: UUID,
        report: ModelUsageReport,
        verification_reference: str,
    ) -> ModelUsageReservation:
        require_permission(context.role, OrganizationPermission.AI_USAGE_RECONCILE)
        if (
            not verification_reference
            or len(verification_reference) > 256
            or verification_reference.strip() != verification_reference
        ):
            raise ValueError("A verification reference is required.")
        self._lock_organization(context)
        reservation = self._session.scalar(
            select(ModelUsageReservation)
            .where(
                ModelUsageReservation.organization_id == context.organization_id,
                ModelUsageReservation.id == reservation_id,
            )
            .with_for_update()
        )
        if reservation is None:
            raise ModelReservationNotFound
        if reservation.status != "reserved":
            raise ModelUsageConflict
        unknown = self._session.scalar(
            select(AuditEvent.id).where(
                AuditEvent.organization_id == context.organization_id,
                AuditEvent.action == "model_usage.outcome_unknown",
                AuditEvent.resource_type == "model_usage",
                AuditEvent.resource_id == reservation_id,
            )
        )
        if unknown is None:
            raise ModelUsageConflict
        reservation.status = "settled"
        reservation.input_tokens = report.input_tokens
        reservation.output_tokens = report.output_tokens
        reservation.settled_at = datetime.now(timezone.utc)
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="model_usage.reconciled",
                resource_type="model_usage",
                resource_id=reservation.id,
                request_id=request_id,
                details={
                    "task_id": str(reservation.task_id),
                    "input_tokens": str(report.input_tokens),
                    "output_tokens": str(report.output_tokens),
                    "verification_reference": verification_reference,
                },
            )
        )
        self._session.flush()
        return reservation
