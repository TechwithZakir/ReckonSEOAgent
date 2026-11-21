import base64
import binascii
import os
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from reckon_core.persistence import AuditEvent, Organization, OrganizationMembership, OrganizationModelSettings
from reckon_core.tenancy import OrganizationRole, TenantAccessDenied, TenantContext
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.websites import InvalidWebsiteUrl, normalize_website_url

ModelProvider = Literal["openai", "anthropic"]
DEFAULT_MODEL_ENDPOINTS: dict[ModelProvider, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}


def normalize_model_endpoint(value: str) -> str:
    if not value or len(value) > 2048 or any(char.isspace() for char in value) or "\\" in value:
        raise ValueError("Invalid model endpoint.")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "https" or not parsed.netloc
            or parsed.query or parsed.fragment or "?" in value or "#" in value
            or parsed.username is not None or parsed.password is not None
            or (parsed.path and not re.fullmatch(r"/[A-Za-z0-9._~/-]*", parsed.path))
            or "//" in parsed.path
            or any(segment in {".", ".."} for segment in parsed.path.split("/"))
        ):
            raise ValueError("Invalid model endpoint.")
        origin = normalize_website_url(f"https://{parsed.netloc}")
    except (InvalidWebsiteUrl, ValueError):
        raise ValueError("Invalid model endpoint. Use a public HTTPS base URL without credentials or query.") from None
    return f"{origin.origin}{parsed.path.rstrip('/')}"


class CredentialEncryptionUnavailable(RuntimeError):
    pass


class ModelCredentialRequired(ValueError):
    pass


class CredentialCipher:
    def __init__(self, configured_key: SecretStr | None) -> None:
        if configured_key is None or not configured_key.get_secret_value():
            raise CredentialEncryptionUnavailable("Credential encryption is not configured.")
        try:
            key = base64.b64decode(
                configured_key.get_secret_value(), altchars=b"-_", validate=True
            )
        except (ValueError, binascii.Error):
            raise CredentialEncryptionUnavailable("Credential encryption is misconfigured.") from None
        if len(key) != 32:
            raise CredentialEncryptionUnavailable("Credential encryption is misconfigured.")
        self._cipher = AESGCM(key)

    @staticmethod
    def _associated_data(organization_id: UUID, provider: str) -> bytes:
        return f"reckon-model-key-v1:{organization_id}:{provider}".encode("ascii")

    def encrypt(self, secret: SecretStr, organization_id: UUID, provider: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(
            nonce, secret.get_secret_value().encode("utf-8"),
            self._associated_data(organization_id, provider),
        )

    def decrypt(self, ciphertext: bytes, organization_id: UUID, provider: str) -> SecretStr:
        try:
            plaintext = self._cipher.decrypt(
                ciphertext[:12], ciphertext[12:], self._associated_data(organization_id, provider)
            )
            return SecretStr(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, UnicodeDecodeError):
            raise CredentialEncryptionUnavailable("Stored credential could not be decrypted.") from None


class SqlAlchemyModelSettingsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._is_postgresql = session.get_bind().dialect.name == "postgresql"

    def _set_tenant(self, organization_id: UUID) -> None:
        if self._is_postgresql:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )

    def _lock_manager(self, context: TenantContext) -> None:
        self._set_tenant(context.organization_id)
        organization = self._session.scalar(
            select(Organization.id)
            .where(Organization.id == context.organization_id)
            .with_for_update()
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
            organization is None
            or membership is None
            or membership.is_active is not True
            or membership.role != context.role
        ):
            raise TenantAccessDenied
        require_permission(membership.role, OrganizationPermission.AI_SETTINGS_MANAGE)

    def get(self, context: TenantContext) -> OrganizationModelSettings | None:
        self._set_tenant(context.organization_id)
        return self._session.scalar(
            select(OrganizationModelSettings).where(
                OrganizationModelSettings.organization_id == context.organization_id
            )
        )

    def save(
        self,
        context: TenantContext,
        request_id: UUID,
        provider: ModelProvider,
        model: str,
        api_key: SecretStr | None,
        cipher: CredentialCipher,
        endpoint_url: str | None = None,
    ) -> OrganizationModelSettings:
        self._lock_manager(context)
        existing = self.get(context)
        endpoint = (
            normalize_model_endpoint(endpoint_url) if endpoint_url is not None
            else (existing.endpoint_url or DEFAULT_MODEL_ENDPOINTS[provider])
            if existing is not None and existing.provider == provider
            else DEFAULT_MODEL_ENDPOINTS[provider]
        )
        if api_key is None and (existing is None or existing.provider != provider):
            raise ModelCredentialRequired("An API key is required for the selected provider.")
        if api_key is None:
            assert existing is not None
            cipher.decrypt(existing.encrypted_key, context.organization_id, provider)
            encrypted = existing.encrypted_key
        else:
            encrypted = cipher.encrypt(api_key, context.organization_id, provider)
        if existing is None:
            existing = OrganizationModelSettings(
                organization_id=context.organization_id,
                provider=provider,
                model=model,
                encrypted_key=encrypted,
                endpoint_url=endpoint,
            )
            self._session.add(existing)
        else:
            existing.provider = provider
            existing.model = model
            existing.endpoint_url = endpoint
            existing.encrypted_key = encrypted
            existing.updated_at = datetime.now(timezone.utc)
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="model_settings.saved",
                resource_type="organization",
                resource_id=context.organization_id,
                request_id=request_id,
                details={"provider": provider, "model": model},
            )
        )
        self._session.flush()
        return existing

    def delete(self, context: TenantContext, request_id: UUID) -> None:
        self._lock_manager(context)
        existing = self.get(context)
        if existing is not None:
            self._session.delete(existing)
            self._session.add(
                AuditEvent(
                    organization_id=context.organization_id,
                    actor_user_id=context.principal.user_id,
                    action="model_settings.deleted",
                    resource_type="organization",
                    resource_id=context.organization_id,
                    request_id=request_id,
                    details={},
                )
            )
            self._session.flush()
