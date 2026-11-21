from enum import Enum

from reckon_core.tenancy import OrganizationRole, TenantAccessDenied


class OrganizationPermission(str, Enum):
    ORGANIZATION_VIEW = "organization.view"
    MEMBER_VIEW = "member.view"
    MEMBER_MANAGE = "member.manage"
    WEBSITE_CREATE = "website.create"
    WEBSITE_VERIFY = "website.verify"
    CRAWL_RUN = "crawl.run"
    CRAWL_VIEW = "crawl.view"
    CRAWL_PURGE = "crawl.purge"
    CRAWL_SCHEDULE_MANAGE = "crawl.schedule.manage"
    AI_SETTINGS_MANAGE = "ai_settings.manage"
    AI_USAGE_VIEW = "ai_usage.view"
    AI_USAGE_RECONCILE = "ai_usage.reconcile"
    AGENT_RUN = "agent.run"
    PROFILE_UPDATE = "profile.update"


_ROLE_PERMISSIONS: dict[OrganizationRole, frozenset[OrganizationPermission]] = {
    OrganizationRole.OWNER: frozenset(permission for permission in OrganizationPermission),
    OrganizationRole.ADMIN: frozenset({
        OrganizationPermission.ORGANIZATION_VIEW,
        OrganizationPermission.MEMBER_VIEW,
        OrganizationPermission.MEMBER_MANAGE,
        OrganizationPermission.WEBSITE_CREATE,
        OrganizationPermission.WEBSITE_VERIFY,
        OrganizationPermission.CRAWL_RUN,
        OrganizationPermission.CRAWL_VIEW,
        OrganizationPermission.CRAWL_PURGE,
        OrganizationPermission.CRAWL_SCHEDULE_MANAGE,
        OrganizationPermission.AI_SETTINGS_MANAGE,
        OrganizationPermission.AI_USAGE_VIEW,
        OrganizationPermission.AI_USAGE_RECONCILE,
        OrganizationPermission.AGENT_RUN,
        OrganizationPermission.PROFILE_UPDATE,
    }),
    OrganizationRole.EDITOR: frozenset({
        OrganizationPermission.ORGANIZATION_VIEW,
        OrganizationPermission.CRAWL_RUN,
        OrganizationPermission.CRAWL_VIEW,
        OrganizationPermission.AGENT_RUN,
    }),
    OrganizationRole.VIEWER: frozenset({
        OrganizationPermission.ORGANIZATION_VIEW,
        OrganizationPermission.CRAWL_VIEW,
    }),
}


def has_permission(role: OrganizationRole, permission: OrganizationPermission) -> bool:
    return permission in _ROLE_PERMISSIONS.get(role, frozenset())


def require_permission(role: OrganizationRole, permission: OrganizationPermission) -> None:
    if not has_permission(role, permission):
        raise TenantAccessDenied
