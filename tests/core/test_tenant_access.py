from uuid import UUID, uuid4

import pytest

from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantAccessDenied,
    TenantAccessService,
)


class MembershipRepository:
    def __init__(
        self,
        memberships: dict[tuple[UUID, UUID], OrganizationRole],
    ) -> None:
        self._memberships = memberships

    def role_for_active_membership(
        self,
        user_id: UUID,
        organization_id: UUID,
    ) -> OrganizationRole | None:
        return self._memberships.get((user_id, organization_id))


def test_tenant_context_uses_active_membership_for_authenticated_user() -> None:
    user_id = uuid4()
    organization_id = uuid4()
    principal = AuthenticatedPrincipal(
        user_id=user_id,
        issuer="https://identity.example.test",
        subject="provider-user-123",
    )
    service = TenantAccessService(
        MembershipRepository({(user_id, organization_id): OrganizationRole.EDITOR})
    )

    context = service.resolve(principal, organization_id)

    assert context.principal == principal
    assert context.organization_id == organization_id
    assert context.role is OrganizationRole.EDITOR


def test_tenant_context_denies_user_without_active_membership() -> None:
    user_id = uuid4()
    authorized_organization_id = uuid4()
    requested_organization_id = uuid4()
    principal = AuthenticatedPrincipal(
        user_id=user_id,
        issuer="https://identity.example.test",
        subject="provider-user-123",
    )
    service = TenantAccessService(
        MembershipRepository(
            {(user_id, authorized_organization_id): OrganizationRole.OWNER}
        )
    )

    with pytest.raises(TenantAccessDenied):
        service.resolve(principal, requested_organization_id)
