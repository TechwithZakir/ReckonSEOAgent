"""Scoped, revocable credentials for the Claude plugin.

A plugin token replaces a member's short-lived session token in the plugin. It can only call
the MCP tools it was issued for, only in the organization it was issued for, and only until
it expires or is revoked. The issuing member's current role still applies on every call, so
removing or demoting the member immediately limits the token as well.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.persistence import AuditEvent, PluginToken
from reckon_core.tenancy import AuthenticatedPrincipal, TenantContext

TOKEN_PREFIX = "rkpt_"
MAX_LIFETIME = timedelta(days=90)
MAX_ACTIVE_PER_ORGANIZATION = 10
ALLOWED_SCOPES = frozenset(
    {
        "reckon.crawl.list",
        "reckon.crawl.schedule.list",
        "reckon.audit.list",
        "reckon.crawl.start",
        "reckon.website.evidence.get",
        "reckon.engine.audit.get",
        "reckon.seo_action.propose",
        "reckon.seo_action.approved.list",
        "reckon.seo_action.claim",
        "reckon.seo_action.report",
    }
)
# Read-only analysis plus the lifecycle tools the plugin needs; no crawl start by default.
DEFAULT_SCOPES = (
    "reckon.crawl.list",
    "reckon.audit.list",
    "reckon.website.evidence.get",
    "reckon.engine.audit.get",
    "reckon.seo_action.propose",
    "reckon.seo_action.approved.list",
    "reckon.seo_action.claim",
    "reckon.seo_action.report",
)
_PATH = re.compile(
    r"^/api/v1/mcp/organizations/(?P<org>[0-9a-fA-F-]{36})/tools/(?P<tool>[A-Za-z0-9._]+)/invoke$"
)


class PluginTokenError(ValueError):
    pass


def is_plugin_token(token: str) -> bool:
    return token.startswith(TOKEN_PREFIX)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PluginTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def issue(
        self,
        context: TenantContext,
        label: str,
        scopes: list[str] | None,
        lifetime_days: int,
        request_id: UUID,
    ) -> tuple[str, PluginToken]:
        """Create a token. The plaintext is returned once and never stored."""
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        label = label.strip()
        chosen = sorted(set(DEFAULT_SCOPES if scopes is None else scopes))
        if not label or len(label) > 80:
            raise PluginTokenError("The token label must be 1-80 characters.")
        if not chosen or any(scope not in ALLOWED_SCOPES for scope in chosen):
            raise PluginTokenError("The token scopes are not supported.")
        if not 1 <= lifetime_days <= MAX_LIFETIME.days:
            raise PluginTokenError(f"The token lifetime must be 1-{MAX_LIFETIME.days} days.")
        now = datetime.now(timezone.utc)
        active = self._session.scalar(
            select(func.count())
            .select_from(PluginToken)
            .where(
                PluginToken.organization_id == context.organization_id,
                PluginToken.revoked_at.is_(None),
                PluginToken.expires_at > now,
            )
        )
        if (active or 0) >= MAX_ACTIVE_PER_ORGANIZATION:
            raise PluginTokenError("The organization has too many active plugin tokens.")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        row = PluginToken(
            token_hash=_digest(token),
            id=uuid4(),
            organization_id=context.organization_id,
            user_id=context.principal.user_id,
            label=label,
            scopes=chosen,
            expires_at=now + timedelta(days=lifetime_days),
        )
        self._session.add(row)
        self._audit(context, "plugin_token.issued", row.id, request_id, {"scopes": ",".join(chosen)})
        self._session.flush()
        return token, row

    def list(self, context: TenantContext) -> list[PluginToken]:
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        return list(
            self._session.scalars(
                select(PluginToken)
                .where(PluginToken.organization_id == context.organization_id)
                .order_by(PluginToken.created_at.desc())
                .limit(100)
            )
        )

    def revoke(self, context: TenantContext, token_id: UUID, request_id: UUID) -> PluginToken:
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        row = self._session.scalar(
            select(PluginToken)
            .where(
                PluginToken.organization_id == context.organization_id,
                PluginToken.id == token_id,
            )
            .with_for_update()
        )
        if row is None:
            raise LookupError("Plugin token not found.")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            self._audit(context, "plugin_token.revoked", row.id, request_id, {})
        self._session.flush()
        return row

    def authenticate(self, token: str, path: str) -> AuthenticatedPrincipal | None:
        """Accept the token only for one of its tools in its own organization."""
        match = _PATH.fullmatch(path)
        if match is None:
            return None
        row = self._session.scalar(
            select(PluginToken).where(PluginToken.token_hash == _digest(token))
        )
        now = datetime.now(timezone.utc)
        if row is None or row.revoked_at is not None:
            return None
        expiry = row.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            return None
        try:
            requested_org = UUID(match["org"])
        except ValueError:
            return None
        if requested_org != row.organization_id or match["tool"] not in row.scopes:
            return None
        row.last_used_at = now
        return AuthenticatedPrincipal(row.user_id, "reckon-plugin", str(row.id))

    def _audit(
        self,
        context: TenantContext,
        action: str,
        token_id: UUID,
        request_id: UUID,
        details: dict[str, str],
    ) -> None:
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action=action,
                resource_type="plugin_token",
                resource_id=token_id,
                request_id=request_id,
                details=details,
            )
        )
