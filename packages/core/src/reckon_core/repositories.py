import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reckon_core.persistence import (
    AuditEvent,
    ExternalIdentity,
    Organization,
    OrganizationCreationRequest,
    OrganizationMembership,
    User,
    Website,
    WebsiteCreationRequest,
)
from reckon_core.tenancy import (
    OrganizationRole,
    TenantAccessDenied,
)


class IdempotencyConflict(ValueError):
    pass


class WebsiteAlreadyExists(ValueError):
    pass


class WebsiteNotFound(LookupError):
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
