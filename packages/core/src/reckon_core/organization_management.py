import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from reckon_core.native_auth import normalize_email
from reckon_core.persistence import (
    AuditEvent, NativeAccount, Organization, OrganizationChange,
    OrganizationInvitation, OrganizationMembership,
)
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import (
    AuthenticatedPrincipal, OrganizationRole, TenantAccessDenied, TenantContext,
)


class OrganizationChangeConflict(ValueError):
    pass


class InvitationUnavailable(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class OrganizationManagement:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._postgres = session.get_bind().dialect.name == "postgresql"

    def _scope(self, org_id: UUID | None, user_id: UUID | None = None) -> None:
        if self._postgres:
            self._session.execute(
                text("SELECT set_config('app.org_id', :org_id, true)"),
                {"org_id": str(org_id) if org_id else ""},
            )
            if user_id is not None:
                self._session.execute(
                    text("SELECT set_config('app.usr_id', :user_id, true)"),
                    {"user_id": str(user_id)},
                )

    def _lock_manager(self, context: TenantContext) -> OrganizationRole:
        self._scope(context.organization_id)
        org = self._session.scalar(
            select(Organization.id).where(Organization.id == context.organization_id).with_for_update()
        )
        member = self._session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == context.organization_id,
                OrganizationMembership.user_id == context.principal.user_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        if org is None or member is None or not member.is_active or member.role not in {
            OrganizationRole.OWNER, OrganizationRole.ADMIN,
        }:
            raise TenantAccessDenied
        return member.role

    def _target(
        self, org_id: UUID, action: str, user_id: UUID | None, email: str | None
    ) -> tuple[OrganizationMembership | None, str]:
        target_id = user_id
        if action == "invite":
            target_id = self._session.scalar(select(NativeAccount.user_id).where(NativeAccount.email == email))
        member = None
        if target_id is not None:
            member = self._session.get(OrganizationMembership, {
                "organization_id": org_id, "user_id": target_id,
            })
        version = _digest({
            "user": str(target_id) if target_id else None,
            "role": member.role.value if member else None,
            "active": member.is_active if member else None,
            "version": str(member.version) if member else None,
        })
        return member, version

    @staticmethod
    def _authorize(role: OrganizationRole, new_role: OrganizationRole, member: OrganizationMembership | None) -> None:
        if role == OrganizationRole.ADMIN and (
            new_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
            or (member is not None and member.role in {OrganizationRole.OWNER, OrganizationRole.ADMIN})
        ):
            raise TenantAccessDenied

    def propose(
        self, context: TenantContext, action: Literal["invite", "role_change"],
        new_role: OrganizationRole, reason: str, key: str, user_id: UUID | None = None,
        email: str | None = None,
    ) -> OrganizationChange:
        manager_role = self._lock_manager(context)
        if action == "invite":
            if email is None or user_id is not None:
                raise ValueError("An invitation requires an email address.")
            email = normalize_email(email)
        elif action == "role_change":
            if user_id is None or email is not None:
                raise ValueError("A role change requires a member.")
        else:
            raise ValueError("Unsupported organization change.")
        body = {
            "action": action, "role": new_role.value, "reason": reason,
            "user": str(user_id) if user_id else None, "email": email,
        }
        request_hash = _digest(body)
        existing = self._session.scalar(select(OrganizationChange).where(
            OrganizationChange.organization_id == context.organization_id,
            OrganizationChange.actor_user_id == context.principal.user_id,
            OrganizationChange.idempotency_key == key,
        ))
        if existing is not None:
            if not hmac.compare_digest(existing.request_hash, request_hash):
                raise IdempotencyConflict
            return existing
        member, version = self._target(context.organization_id, action, user_id, email)
        self._authorize(manager_role, new_role, member)
        if action == "role_change" and (member is None or not member.is_active):
            raise OrganizationChangeConflict("The active member was not found.")
        if action == "invite" and member is not None:
            raise OrganizationChangeConflict("This account already has an organization membership.")
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=15)
        change_id = uuid4()
        approval_hash = _digest({
            **body, "id": str(change_id), "org": str(context.organization_id),
            "actor": str(context.principal.user_id), "target_version": version,
            "expires_at": expires.isoformat(), "evidence": "organization membership snapshot",
        })
        change = OrganizationChange(
            id=change_id, organization_id=context.organization_id,
            actor_user_id=context.principal.user_id, idempotency_key=key,
            request_hash=request_hash, approval_hash=approval_hash, action=action,
            target_user_id=user_id, email=email, role=new_role, target_version=version,
            reason=reason, created_at=now, expires_at=expires,
        )
        self._session.add(change)
        self._session.flush()
        return change

    def approve(
        self, context: TenantContext, change_id: UUID, approval_hash: str, request_id: UUID
    ) -> tuple[OrganizationChange, OrganizationInvitation | None, bool]:
        manager_role = self._lock_manager(context)
        change = self._session.scalar(select(OrganizationChange).where(
            OrganizationChange.organization_id == context.organization_id,
            OrganizationChange.id == change_id,
            OrganizationChange.actor_user_id == context.principal.user_id,
        ).with_for_update())
        if change is None or not hmac.compare_digest(change.approval_hash, approval_hash):
            raise OrganizationChangeConflict("The approval does not match the proposal.")
        expiry = change.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        else:
            expiry = expiry.astimezone(timezone.utc)
        expected_hash = _digest({
            "action": change.action, "role": change.role.value, "reason": change.reason,
            "user": str(change.target_user_id) if change.target_user_id else None,
            "email": change.email, "id": str(change.id), "org": str(change.organization_id),
            "actor": str(change.actor_user_id), "target_version": change.target_version,
            "expires_at": expiry.isoformat(), "evidence": "organization membership snapshot",
        })
        if not hmac.compare_digest(change.approval_hash, expected_hash):
            raise OrganizationChangeConflict("The proposal has changed.")
        if change.approved_at is not None:
            invitation = self._session.scalar(select(OrganizationInvitation).where(
                OrganizationInvitation.organization_id == context.organization_id,
                OrganizationInvitation.change_id == change.id,
            ))
            return change, invitation, False
        now = datetime.now(timezone.utc)
        if expiry <= now:
            raise OrganizationChangeConflict("The proposal has expired.")
        member, version = self._target(context.organization_id, change.action, change.target_user_id, change.email)
        if not hmac.compare_digest(version, change.target_version):
            raise OrganizationChangeConflict("The target changed; create a new proposal.")
        self._authorize(manager_role, change.role, member)
        invitation = None
        if change.action == "role_change":
            if member is None or not member.is_active:
                raise OrganizationChangeConflict("The active member was not found.")
            if member.role == OrganizationRole.OWNER and change.role != OrganizationRole.OWNER:
                owners = self._session.scalar(select(func.count()).select_from(OrganizationMembership).where(
                    OrganizationMembership.organization_id == context.organization_id,
                    OrganizationMembership.role == OrganizationRole.OWNER,
                    OrganizationMembership.is_active.is_(True),
                ))
                if owners is None or owners <= 1:
                    raise OrganizationChangeConflict("The last owner cannot be demoted.")
            member.role = change.role
            target_id = member.user_id
        else:
            if member is not None or change.email is None:
                raise OrganizationChangeConflict("This account already has an organization membership.")
            pending = self._session.scalar(select(OrganizationInvitation.id).where(
                OrganizationInvitation.organization_id == context.organization_id,
                OrganizationInvitation.email == change.email,
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.expires_at > now,
            ))
            if pending is not None:
                raise OrganizationChangeConflict("An active invitation already exists for this address.")
            invitation = OrganizationInvitation(
                id=uuid4(), organization_id=context.organization_id, change_id=change.id,
                email=change.email, role=change.role, inviter_user_id=context.principal.user_id,
                expires_at=now + timedelta(days=7), delivery_state="unconfirmed",
            )
            self._session.add(invitation)
            target_id = invitation.id
        change.approved_at = now
        self._session.add(AuditEvent(
            organization_id=context.organization_id, actor_user_id=context.principal.user_id,
            action=f"organization.{change.action}", resource_type=change.action,
            resource_id=target_id, request_id=request_id,
            details={"role": change.role.value, "reason": change.reason, "approval_hash": change.approval_hash},
        ))
        self._session.flush()
        return change, invitation, True

    def incoming(self, principal: AuthenticatedPrincipal) -> list[tuple[OrganizationInvitation, str]]:
        account = self._session.get(NativeAccount, principal.user_id)
        if account is None or not account.email_verified:
            return []
        self._scope(None, principal.user_id)
        invitations = self._session.scalars(select(OrganizationInvitation).where(
            OrganizationInvitation.email == account.email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(timezone.utc),
        ).order_by(OrganizationInvitation.expires_at).limit(50)).all()
        result = []
        for invite in invitations:
            self._scope(invite.organization_id)
            name = self._session.scalar(select(Organization.name).where(Organization.id == invite.organization_id))
            if name is not None:
                result.append((invite, name))
        return result

    def record_notification(self, organization_id: UUID, invitation_id: UUID, state: str) -> None:
        if state not in {"smtp_accepted", "unconfirmed"}:
            raise ValueError("Invalid notification state.")
        self._scope(organization_id)
        invitation = self._session.scalar(select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.id == invitation_id,
        ).with_for_update())
        if invitation is None:
            raise InvitationUnavailable
        invitation.delivery_state = state
        self._session.flush()

    def accept(self, principal: AuthenticatedPrincipal, invitation_id: UUID, request_id: UUID) -> TenantContext:
        account = self._session.get(NativeAccount, principal.user_id)
        if account is None or not account.email_verified:
            raise InvitationUnavailable
        self._scope(None, principal.user_id)
        invite = self._session.scalar(select(OrganizationInvitation).where(
            OrganizationInvitation.id == invitation_id, OrganizationInvitation.email == account.email,
        ))
        if invite is None:
            raise InvitationUnavailable
        org_id = invite.organization_id
        self._scope(org_id)
        org = self._session.scalar(select(Organization.id).where(Organization.id == org_id).with_for_update())
        invite = self._session.scalar(select(OrganizationInvitation).where(
            OrganizationInvitation.id == invitation_id, OrganizationInvitation.organization_id == org_id,
            OrganizationInvitation.email == account.email,
        ).with_for_update().execution_options(populate_existing=True))
        if org is None or invite is None:
            raise InvitationUnavailable
        member = self._session.get(OrganizationMembership, {"organization_id": org_id, "user_id": principal.user_id})
        if invite.accepted_at is not None:
            if invite.accepted_by == principal.user_id and member is not None and member.is_active:
                return TenantContext(principal, org_id, member.role)
            raise InvitationUnavailable
        expiry = invite.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc) or member is not None:
            raise InvitationUnavailable
        member = OrganizationMembership(
            organization_id=org_id, user_id=principal.user_id, role=invite.role, is_active=True,
        )
        self._session.add(member)
        invite.accepted_by = principal.user_id
        invite.accepted_at = datetime.now(timezone.utc)
        self._session.add(AuditEvent(
            organization_id=org_id, actor_user_id=principal.user_id,
            action="organization.invitation_accepted", resource_type="invitation",
            resource_id=invite.id, request_id=request_id, details={"role": invite.role.value},
        ))
        self._session.flush()
        return TenantContext(principal, org_id, member.role)
