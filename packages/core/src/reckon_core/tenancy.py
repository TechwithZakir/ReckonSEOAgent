from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID


class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity mapped by a trusted authentication adapter."""

    user_id: UUID
    issuer: str
    subject: str


@dataclass(frozen=True, slots=True)
class TenantContext:
    principal: AuthenticatedPrincipal
    organization_id: UUID
    role: OrganizationRole


class ActiveMembershipRepository(Protocol):
    def role_for_active_membership(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> OrganizationRole | None:
        """Return the active member's role, or None if they have no active membership."""


class TenantAccessDenied(PermissionError):
    def __init__(self) -> None:
        super().__init__("Active organization membership is required.")


class TenantAccessService:
    def __init__(self, memberships: ActiveMembershipRepository) -> None:
        self._memberships = memberships

    def resolve(
        self,
        principal: AuthenticatedPrincipal,
        organization_id: UUID,
    ) -> TenantContext:
        role = self._memberships.role_for_active_membership(
            principal.user_id,
            organization_id,
        )
        if role is None:
            raise TenantAccessDenied

        return TenantContext(
            principal=principal,
            organization_id=organization_id,
            role=role,
        )
