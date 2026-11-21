import asyncio
import hmac
from datetime import timezone
from typing import Annotated, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reckon_api.dependencies import get_authenticated_principal, get_database_session
from reckon_api.tenant_access import resolve_organization_access
from reckon_core.model_settings import (
    CredentialCipher,
    CredentialEncryptionUnavailable,
    DEFAULT_MODEL_ENDPOINTS,
    ModelCredentialRequired,
    ModelProvider,
    SqlAlchemyModelSettingsRepository,
    normalize_model_endpoint,
)
from reckon_core.model_usage import Identifier
from reckon_core.model_gateway import (
    ModelExecutionPolicy, ModelGateway, ModelGatewayRejected, ModelGatewayReplay,
    ModelGatewayRequest, ModelLimitExceeded, ModelMessage, ModelOutcomeUnknown,
)
from reckon_core.model_providers import ProviderAdapter
from reckon_core.model_usage import ModelUsageReport
from reckon_core.model_usage_repository import (
    ModelBudgetExceeded,
    ModelReservationNotFound,
    ModelUsageConflict,
    SqlAlchemyModelUsageRepository,
)
from reckon_core.persistence import OrganizationModelSettings
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import (
    AuthenticatedPrincipal, OrganizationRole, TenantAccessDenied, TenantContext,
)
from reckon_core.permissions import OrganizationPermission, require_permission

router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/ai-settings", tags=["AI settings"]
)
usage_router = APIRouter(
    prefix="/api/v1/organizations/{organization_id}/ai-usage", tags=["AI usage"]
)


class SaveModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: ModelProvider
    model: Identifier
    api_key: SecretStr | None = None
    endpoint_url: str | None = None

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        return normalize_model_endpoint(value) if value is not None else None

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            secret = value.get_secret_value()
            if not 1 <= len(secret) <= 4096 or any(char.isspace() for char in secret):
                raise ValueError("Invalid API key.")
        return value


class ModelSettingsResponse(BaseModel):
    configured: bool
    provider: ModelProvider | None
    model: str | None
    endpoint_url: str | None
    encryption_available: bool


class ModelTestResponse(BaseModel):
    verified: bool
    provider: ModelProvider
    model: str
    input_tokens: int
    output_tokens: int


class AIUsageResponse(BaseModel):
    reservation_id: UUID
    task_id: UUID
    request_id: UUID
    status: Literal["reserved", "settled"]
    provider: str
    model: str
    max_input_tokens: int
    max_output_tokens: int
    input_tokens: int | None
    output_tokens: int | None
    started_at: str
    settled_at: str | None


class ReconcileAIUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    verification_reference: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=8, max_length=256),
    ]


AIUsageResponse.model_rebuild()


class _TestAuthorizer:
    def __init__(self, policy: ModelExecutionPolicy) -> None:
        self._policy = policy

    def authorize(
        self, context: TenantContext, task_id: UUID, request: ModelGatewayRequest,
    ) -> ModelExecutionPolicy:
        try:
            require_permission(context.role, OrganizationPermission.AI_SETTINGS_MANAGE)
        except TenantAccessDenied:
            raise TenantAccessDenied
        return self._policy


def _require_manager(
    principal: AuthenticatedPrincipal, organization_id: UUID, session: Session
) -> TenantContext:
    context = resolve_organization_access(principal, organization_id, session)
    try:
        require_permission(context.role, OrganizationPermission.AI_SETTINGS_MANAGE)
    except TenantAccessDenied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization administrator access is required.",
        )
    return context


def _cipher(request: Request) -> CredentialCipher:
    try:
        return CredentialCipher(request.app.state.settings.credential_encryption_key)
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Credential encryption is unavailable. Contact the platform operator.",
        ) from error


@router.get("", response_model=ModelSettingsResponse)
def get_model_settings(
    request: Request,
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> ModelSettingsResponse:
    context = _require_manager(principal, organization_id, session)
    settings = SqlAlchemyModelSettingsRepository(session).get(context)
    try:
        CredentialCipher(request.app.state.settings.credential_encryption_key)
        encryption_available = True
    except CredentialEncryptionUnavailable:
        encryption_available = False
    if settings is None:
        return ModelSettingsResponse(
            configured=False, provider=None, model=None, endpoint_url=None, encryption_available=encryption_available
        )
    return ModelSettingsResponse(
        configured=True, provider=settings.provider, model=settings.model,
        endpoint_url=settings.endpoint_url or DEFAULT_MODEL_ENDPOINTS[settings.provider],
        encryption_available=encryption_available,
    )


@router.put("", response_model=ModelSettingsResponse)
def put_model_settings(
    http_request: Request,
    organization_id: UUID,
    payload: SaveModelSettings,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> ModelSettingsResponse:
    context = _require_manager(principal, organization_id, session)
    if http_request.url.scheme != "https":
        local_request = (
            http_request.app.state.settings.environment == "local"
            and http_request.client is not None
            and http_request.client.host in {"127.0.0.1", "::1"}
        )
        if http_request.app.state.settings.environment != "test" and not local_request:
            raise HTTPException(
                status_code=400, detail="HTTPS is required to save AI credentials."
            )
    try:
        settings = SqlAlchemyModelSettingsRepository(session).save(
            context, http_request.state.request_id, payload.provider, payload.model,
            payload.api_key, _cipher(http_request), payload.endpoint_url,
        )
        response = ModelSettingsResponse(
            configured=True, provider=settings.provider, model=settings.model, endpoint_url=settings.endpoint_url,
            encryption_available=True,
        )
        session.commit()
    except ModelCredentialRequired as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(
            status_code=503, detail="Stored credential could not be decrypted. Replace the API key."
        ) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.") from error
    return response


@router.post("/test", response_model=ModelTestResponse)
async def test_model_settings(
    request: Request,
    organization_id: UUID,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    ],
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> ModelTestResponse:
    context = _require_manager(principal, organization_id, session)
    if request.url.scheme != "https" and request.app.state.settings.environment != "test":
        local = (
            request.app.state.settings.environment == "local" and request.client is not None
            and request.client.host in {"127.0.0.1", "::1"}
        )
        if not local:
            raise HTTPException(status_code=400, detail="HTTPS is required to test AI settings.")
    settings = SqlAlchemyModelSettingsRepository(session).get(context)
    if settings is None:
        raise HTTPException(status_code=409, detail="Save AI settings before testing.")
    provider, model = settings.provider, settings.model
    endpoint = settings.endpoint_url or DEFAULT_MODEL_ENDPOINTS[provider]
    ciphertext = settings.encrypted_key
    try:
        key = _cipher(request).decrypt(ciphertext, organization_id, provider)
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(status_code=503, detail="Stored credential could not be decrypted.") from error
    adapter = ProviderAdapter(
        provider, endpoint, key, ciphertext, request.app.state.model_test_resolver,
        request.app.state.model_test_transport,
    )
    policy = ModelExecutionPolicy(
        provider=provider, model=model,
        daily_token_limit=request.app.state.settings.ai_test_daily_token_limit,
        max_input_tokens=512, max_output_tokens=128, timeout_seconds=15.0,
    )

    def check_binding(locked_session: Session, tenant: TenantContext) -> None:
        current = locked_session.scalar(select(OrganizationModelSettings).where(
            OrganizationModelSettings.organization_id == tenant.organization_id
        ).with_for_update())
        if (
            current is None or current.provider != provider or current.model != model
            or (current.endpoint_url or DEFAULT_MODEL_ENDPOINTS[current.provider]) != endpoint
            or not hmac.compare_digest(current.encrypted_key, ciphertext)
        ):
            raise ModelGatewayRejected("AI settings changed; start a new test.")

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    gateway = ModelGateway(factory, _TestAuthorizer(policy), {provider: adapter}, 1, check_binding)
    model_request = ModelGatewayRequest(
        provider=provider, model=model, system_prompt="Reply with OK.",
        messages=(ModelMessage(role="user", content="Test connection."),),
    )
    try:
        try:
            await asyncio.wait_for(request.app.state.model_test_slots.acquire(), timeout=1.0)
        except TimeoutError as error:
            raise HTTPException(status_code=503, detail="AI test capacity is busy. Try again later.") from error
        try:
            result = await gateway.execute(
                context, uuid5(organization_id, f"ai-test:{idempotency_key}"),
                request.state.request_id, idempotency_key, model_request,
            )
        finally:
            request.app.state.model_test_slots.release()
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.") from error
    except ModelBudgetExceeded as error:
        raise HTTPException(status_code=429, detail="The organization's AI test token budget is exhausted.") from error
    except (ModelGatewayReplay, IdempotencyConflict) as error:
        raise HTTPException(status_code=409, detail="This test was already attempted; start a new test deliberately.") from error
    except ModelGatewayRejected as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ModelOutcomeUnknown as error:
        raise HTTPException(
            status_code=502, detail="The provider response could not be verified; charges may be unknown."
        ) from error
    except ModelLimitExceeded as error:
        raise HTTPException(status_code=502, detail="The provider exceeded the authorized token limit.") from error
    return ModelTestResponse(
        verified=True, provider=provider, model=model,
        input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_model_settings(
    request: Request,
    organization_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> Response:
    context = _require_manager(principal, organization_id, session)
    try:
        SqlAlchemyModelSettingsRepository(session).delete(context, request.state.request_id)
        session.commit()
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@usage_router.get("", response_model=None)
def list_ai_usage(
    organization_id: UUID,
    limit: int = Query(default=100, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> list[dict[str, object]]:
    context = _require_manager(principal, organization_id, session)
    try:
        rows = SqlAlchemyModelUsageRepository(session).list_for_organization(context, limit)
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.") from error

    response: list[dict[str, object]] = []
    for row in rows:
        started = row.started_at
        settled = row.settled_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if settled is not None and settled.tzinfo is None:
            settled = settled.replace(tzinfo=timezone.utc)
        response.append(
            {
                "reservation_id": str(row.id),
                "task_id": str(row.task_id),
                "request_id": str(row.request_id),
                "status": row.status,
                "provider": row.provider,
                "model": row.model,
                "max_input_tokens": row.max_input_tokens,
                "max_output_tokens": row.max_output_tokens,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "started_at": started.astimezone(timezone.utc).isoformat(),
                "settled_at": settled.astimezone(timezone.utc).isoformat() if settled is not None else None,
            }
        )
    return response


@usage_router.post("/{reservation_id}/reconcile", response_model=AIUsageResponse)
def reconcile_ai_usage(
    organization_id: UUID,
    reservation_id: UUID,
    payload: ReconcileAIUsage,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: Session = Depends(get_database_session),
) -> AIUsageResponse:
    context = _require_manager(principal, organization_id, session)
    try:
        row = SqlAlchemyModelUsageRepository(session).reconcile_unknown(
            context,
            reservation_id,
            request.state.request_id,
            ModelUsageReport(
                input_tokens=payload.input_tokens,
                output_tokens=payload.output_tokens,
            ),
            payload.verification_reference,
        )
        session.commit()
    except ModelReservationNotFound as error:
        raise HTTPException(status_code=404, detail="AI usage reservation not found.") from error
    except ModelUsageConflict as error:
        raise HTTPException(
            status_code=409,
            detail="The reservation is not an unresolved unknown outcome.",
        ) from error
    except TenantAccessDenied as error:
        raise HTTPException(status_code=403, detail="Organization administrator access is required.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    settled = row.settled_at
    started = row.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if settled is not None and settled.tzinfo is None:
        settled = settled.replace(tzinfo=timezone.utc)
    return AIUsageResponse(
        reservation_id=row.id,
        task_id=row.task_id,
        request_id=row.request_id,
        status=row.status,
        provider=row.provider,
        model=row.model,
        max_input_tokens=row.max_input_tokens,
        max_output_tokens=row.max_output_tokens,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        started_at=started.astimezone(timezone.utc).isoformat(),
        settled_at=settled.astimezone(timezone.utc).isoformat() if settled is not None else None,
    )
