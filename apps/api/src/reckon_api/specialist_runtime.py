"""Shared, tenant-bound model gateway construction and error mapping for specialist agents."""

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
from reckon_core.persistence import OrganizationModelSettings
from reckon_core.repositories import IdempotencyConflict
from reckon_core.specialist_agents import SpecialistPrioritizationAuthorizer
from reckon_core.tenancy import TenantContext


@dataclass(frozen=True)
class SpecialistRuntime:
    gateway: ModelGateway
    factory: sessionmaker[Session]
    provider: str
    model: str


def build_specialist_runtime(
    http_request: Request,
    session: Session,
    context: TenantContext,
    *,
    max_input_tokens: int = 4096,
    max_output_tokens: int = 512,
    use_agent_budget: bool = False,
) -> SpecialistRuntime:
    """Bind the organization's saved AI settings to a bounded gateway (or raise HTTPException)."""
    organization_id = context.organization_id
    settings = SqlAlchemyModelSettingsRepository(session).get(context)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Save AI settings before running a specialist agent.",
        )
    app_settings = http_request.app.state.settings
    if http_request.url.scheme != "https" and app_settings.environment != "test":
        local_request = (
            app_settings.environment == "local"
            and http_request.client is not None
            and http_request.client.host in {"127.0.0.1", "::1"}
        )
        if not local_request:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HTTPS is required to run an AI specialist.",
            )
    provider, model = settings.provider, settings.model
    endpoint = settings.endpoint_url or DEFAULT_MODEL_ENDPOINTS[provider]
    ciphertext = settings.encrypted_key
    try:
        api_key = CredentialCipher(app_settings.credential_encryption_key).decrypt(
            ciphertext, organization_id, provider
        )
    except CredentialEncryptionUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored credential could not be decrypted. Replace the API key.",
        ) from error
    adapter = ProviderAdapter(
        provider, endpoint, api_key, ciphertext,
        http_request.app.state.model_test_resolver,
        http_request.app.state.model_test_transport,
    )
    policy = ModelExecutionPolicy(
        provider=provider,
        model=model,
        daily_token_limit=(
            app_settings.ai_agent_daily_token_limit
            if use_agent_budget
            else app_settings.ai_test_daily_token_limit
        ),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
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
        factory, SpecialistPrioritizationAuthorizer(policy), {provider: adapter}, 2, check_binding,
    )
    return SpecialistRuntime(gateway, factory, provider, model)


def model_error_to_http(error: Exception) -> HTTPException | None:
    """Translate gateway failures into non-leaky HTTP errors; None if not a gateway error."""
    if isinstance(error, ModelBudgetExceeded):
        return HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "The organization has reached its AI token budget."
        )
    if isinstance(error, (ModelGatewayReplay, IdempotencyConflict)):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            "This specialist run was already attempted; start a new run deliberately.",
        )
    if isinstance(error, ModelGatewayRejected):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    if isinstance(error, ModelLimitExceeded):
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The provider exceeded the authorized token limit."
        )
    if isinstance(error, TimeoutError):
        return HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "The specialist run exceeded its aggregate deadline."
        )
    return None
