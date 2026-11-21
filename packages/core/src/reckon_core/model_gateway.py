import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session, sessionmaker

from reckon_core.model_usage import (
    IdempotencyKey,
    Identifier,
    ModelReservationRequest,
    ModelUsageReport,
    PositiveTokenCount,
)
from reckon_core.model_usage_repository import SqlAlchemyModelUsageRepository, UnknownReason
from reckon_core.repositories import SqlAlchemyMembershipRepository
from reckon_core.tenancy import TenantAccessDenied, TenantContext

MessageText = Annotated[str, StringConstraints(min_length=1, max_length=32_000)]


class ModelMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    role: Literal["user", "assistant"]
    content: MessageText = Field(repr=False)


class ModelGatewayRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    provider: Identifier
    model: Identifier
    system_prompt: MessageText = Field(repr=False)
    messages: tuple[ModelMessage, ...] = Field(min_length=1, max_length=32, repr=False)


class ModelExecutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Identifier
    model: Identifier
    daily_token_limit: PositiveTokenCount
    max_input_tokens: PositiveTokenCount
    max_output_tokens: PositiveTokenCount
    timeout_seconds: float = Field(strict=True, gt=0, le=60, allow_inf_nan=False)


class ModelProviderResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    text: Annotated[str, StringConstraints(max_length=100_000)] = Field(repr=False)
    usage: ModelUsageReport


class ModelAuthorizer(Protocol):
    def authorize(
        self, context: TenantContext, task_id: UUID, request: ModelGatewayRequest
    ) -> ModelExecutionPolicy:
        """Return trusted task-specific policy or raise; do not perform external I/O."""


class ModelAdapter(Protocol):
    binding_version: str

    def input_token_upper_bound(self, request: ModelGatewayRequest) -> int:
        """Return a conservative local bound including provider framing; do not perform I/O."""

    async def complete(
        self,
        request: ModelGatewayRequest,
        policy: ModelExecutionPolicy,
        timeout_seconds: float,
    ) -> ModelProviderResult:
        """Enforce policy limits and timeouts and report provider-confirmed token usage."""


class ModelAdapterError(Exception):
    """A provider error whose usage outcome is unknown."""


class ModelGatewayRejected(ValueError):
    pass


class ModelGatewayReplay(ValueError):
    pass


class ModelOutcomeUnknown(RuntimeError):
    def __init__(self, reservation_id: UUID) -> None:
        super().__init__("The model call outcome is unknown; its reservation remains charged.")
        self.reservation_id = reservation_id


class ModelLimitExceeded(RuntimeError):
    pass


class ModelGateway:
    """Internal, per-event-loop boundary using only trusted policy and adapters."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        authorizer: ModelAuthorizer,
        adapters: dict[str, ModelAdapter],
        max_concurrent: int,
        reservation_check: Callable[[Session, TenantContext], None] | None = None,
    ) -> None:
        if type(max_concurrent) is not int or max_concurrent < 1:
            raise ValueError("The concurrency limit must be a positive integer.")
        self._session_factory = session_factory
        self._authorizer = authorizer
        self._adapters = dict(adapters)
        self._reservation_check = reservation_check
        self._slots = asyncio.Semaphore(max_concurrent)
        self._inflight: set[asyncio.Task[ModelProviderResult]] = set()

    def _finished(self, task: asyncio.Task[ModelProviderResult]) -> None:
        self._inflight.discard(task)
        self._slots.release()
        if not task.cancelled():
            task.exception()

    def _record_unknown(
        self,
        context: TenantContext,
        reservation_id: UUID,
        request_id: UUID,
        reason: UnknownReason,
        elapsed_ms: int,
    ) -> None:
        with self._session_factory() as session:
            SqlAlchemyModelUsageRepository(session).record_unknown(
                context, reservation_id, request_id, reason, elapsed_ms
            )
            session.commit()

    async def execute(
        self,
        context: TenantContext,
        task_id: UUID,
        request_id: UUID,
        idempotency_key: IdempotencyKey,
        request: ModelGatewayRequest,
    ) -> ModelProviderResult:
        with self._session_factory() as session:
            role = SqlAlchemyMembershipRepository(session).role_for_active_membership(
                context.principal.user_id, context.organization_id
            )
        if role is None or role != context.role:
            raise TenantAccessDenied
        policy = self._authorizer.authorize(context, task_id, request)
        if request.provider != policy.provider or request.model != policy.model:
            raise ModelGatewayRejected("The requested model is not authorized by policy.")
        adapter = self._adapters.get(policy.provider)
        if adapter is None:
            raise ModelGatewayRejected("The authorized model adapter is unavailable.")
        binding_version = adapter.binding_version
        if not binding_version or len(binding_version) > 128:
            raise ModelGatewayRejected("The model adapter binding version is invalid.")

        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + policy.timeout_seconds
        token_bound = adapter.input_token_upper_bound(request)
        if type(token_bound) is not int or token_bound < 0:
            raise ModelGatewayRejected("The model adapter returned an invalid token bound.")
        if token_bound > policy.max_input_tokens:
            raise ModelGatewayRejected("The request exceeds the authorized input token limit.")
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise ModelGatewayRejected("The model request deadline expired before reservation.")

        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=remaining)
        except TimeoutError as error:
            raise ModelGatewayRejected("Model execution capacity is unavailable.") from error

        task: asyncio.Task[ModelProviderResult] | None = None
        reservation_id: UUID | None = None
        release_slot = True
        try:
            digest = hashlib.sha256(
                json.dumps(
                    [binding_version, request.model_dump(mode="json")],
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            reservation_request = ModelReservationRequest(
                task_id=task_id,
                request_id=request_id,
                idempotency_key=idempotency_key,
                provider=policy.provider,
                model=policy.model,
                request_digest=digest,
                max_input_tokens=policy.max_input_tokens,
                max_output_tokens=policy.max_output_tokens,
            )
            with self._session_factory() as session:
                reservation, replay = SqlAlchemyModelUsageRepository(session).reserve(
                    context, reservation_request, policy.daily_token_limit, self._reservation_check
                )
                reservation_id = reservation.id
                session.commit()
            if replay:
                raise ModelGatewayReplay("A previous request already owns this idempotency key.")
            remaining = deadline - loop.time()
            if remaining <= 0:
                with self._session_factory() as session:
                    SqlAlchemyModelUsageRepository(session).settle(
                        context,
                        reservation_id,
                        request_id,
                        ModelUsageReport(input_tokens=0, output_tokens=0),
                    )
                    session.commit()
                raise ModelGatewayRejected("The model request deadline expired before dispatch.")

            task = asyncio.create_task(adapter.complete(request, policy, remaining))
            self._inflight.add(task)
            task.add_done_callback(self._finished)
            release_slot = False
            done, _ = await asyncio.wait({task}, timeout=remaining)
            if not done:
                task.cancel()
                self._record_unknown(
                    context, reservation_id, request_id, "timeout",
                    int((loop.time() - started) * 1000),
                )
                raise ModelOutcomeUnknown(reservation_id)
            if task.cancelled():
                self._record_unknown(
                    context, reservation_id, request_id, "adapter_cancelled",
                    int((loop.time() - started) * 1000),
                )
                raise ModelOutcomeUnknown(reservation_id)
            try:
                result = task.result()
            except (ModelAdapterError, TimeoutError):
                self._record_unknown(
                    context, reservation_id, request_id, "adapter_error",
                    int((loop.time() - started) * 1000),
                )
                raise ModelOutcomeUnknown(reservation_id) from None
            if not isinstance(result, ModelProviderResult):
                self._record_unknown(
                    context, reservation_id, request_id, "invalid_result",
                    int((loop.time() - started) * 1000),
                )
                raise ModelOutcomeUnknown(reservation_id)
            with self._session_factory() as session:
                SqlAlchemyModelUsageRepository(session).settle(
                    context, reservation_id, request_id, result.usage
                )
                session.commit()
            if (
                result.usage.input_tokens > policy.max_input_tokens
                or result.usage.output_tokens > policy.max_output_tokens
            ):
                raise ModelLimitExceeded("The provider reported usage above the authorized limit.")
            return result
        except asyncio.CancelledError:
            if reservation_id is not None and task is not None:
                self._record_unknown(
                    context, reservation_id, request_id, "caller_cancelled",
                    int((loop.time() - started) * 1000),
                )
            raise
        finally:
            if task is not None and not task.done():
                task.cancel()
            if release_slot:
                self._slots.release()
