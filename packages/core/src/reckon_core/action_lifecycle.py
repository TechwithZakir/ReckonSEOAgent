import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from reckon_core.persistence import AuditEvent, SeoActionProposal, Website
from reckon_core.permissions import OrganizationPermission, require_permission
from reckon_core.repositories import IdempotencyConflict
from reckon_core.tenancy import TenantAccessDenied, TenantContext


ActionRisk = Literal["low", "medium", "high"]
ActionStatus = Literal[
    "proposed",
    "approved",
    "rejected",
    "executing",
    "executed",
    "verified",
    "failed",
    "rolled_back",
]


class ActionLifecycleConflict(ValueError):
    pass


class ActionExecutionUnavailable(RuntimeError):
    pass


class ActionExecutor(Protocol):
    def execute(self, proposal: SeoActionProposal) -> dict[str, str]:
        """Execute only an approved proposal and return executed state."""

    def verify(self, proposal: SeoActionProposal) -> dict[str, str]:
        """Independently verify live state and return verification evidence."""

    def rollback(self, proposal: SeoActionProposal) -> dict[str, str]:
        """Restore before-state when technically possible."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class SeoActionLifecycle:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._postgres = session.get_bind().dialect.name == "postgresql"

    def _scope(self, organization_id: UUID) -> None:
        if self._postgres:
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )

    def _require_manager(self, context: TenantContext) -> None:
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)

    def _require_verified_website(self, proposal: SeoActionProposal) -> None:
        website = self._session.scalar(
            select(Website).where(
                Website.organization_id == proposal.organization_id,
                Website.id == proposal.website_id,
            )
        )
        if (
            website is None
            or not website.is_verified
            or (urlsplit(proposal.target_url).hostname or "").lower() != website.host.lower()
        ):
            raise ActionLifecycleConflict("The action website is not verified for execution.")

    def propose(
        self,
        context: TenantContext,
        website_id: UUID,
        action_type: str,
        target_url: str,
        target_version: str,
        before_state: dict[str, str],
        proposed_state: dict[str, str],
        risk: ActionRisk,
        reason: str,
        idempotency_key: str,
        request_id: UUID,
        channel: Literal["api", "mcp"] = "api",
    ) -> SeoActionProposal:
        self._scope(context.organization_id)
        try:
            self._require_manager(context)
        except TenantAccessDenied:
            raise
        if risk not in {"low", "medium", "high"}:
            raise ValueError("Invalid action risk.")
        if action_type not in {
            "meta_title",
            "meta_description",
            "canonical",
            "heading",
            "schema",
            "redirect",
            "internal_link",
            "other",
        }:
            raise ValueError("Unsupported action type.")
        if (
            not target_url
            or len(target_url) > 2048
            or not target_version
            or len(target_version) > 64
            or not reason.strip()
            or len(reason.strip()) > 200
        ):
            raise ValueError("Invalid action target or reason.")

        website = self._session.scalar(
            select(Website).where(
                Website.organization_id == context.organization_id,
                Website.id == website_id,
            )
        )
        if website is None:
            raise LookupError("Website not found.")
        if (urlsplit(target_url).hostname or "").lower() != website.host.lower():
            raise ValueError("The action target must belong to the selected website.")
        payload = {
            "action_type": action_type,
            "target_url": target_url,
            "target_version": target_version,
            "before_state": before_state,
            "proposed_state": proposed_state,
            "risk": risk,
            "reason": reason.strip(),
        }
        proposal_hash = _digest(payload)
        existing = self._session.scalar(
            select(SeoActionProposal).where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if not hmac.compare_digest(existing.proposal_hash, proposal_hash):
                raise IdempotencyConflict
            return existing

        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=30)
        proposal_id = uuid4()
        approval_hash = _digest({
            **payload,
            "proposal_id": str(proposal_id),
            "organization_id": str(context.organization_id),
            "website_id": str(website_id),
            "actor_user_id": str(context.principal.user_id),
            "expires_at": expires.isoformat(),
        })
        proposal = SeoActionProposal(
            id=proposal_id,
            organization_id=context.organization_id,
            website_id=website_id,
            actor_user_id=context.principal.user_id,
            idempotency_key=idempotency_key,
            proposal_hash=proposal_hash,
            approval_hash=approval_hash,
            action_type=action_type,
            target_url=target_url,
            target_version=target_version,
            risk=risk,
            status="proposed",
            reason=reason.strip(),
            before_state=before_state,
            proposed_state=proposed_state,
            expires_at=expires,
        )
        self._session.add(proposal)
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="seo_action.proposed",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={
                    "action_type": action_type,
                    "target_url": target_url,
                    "target_version": target_version,
                    "risk": risk,
                    "channel": channel,
                },
            )
        )
        self._session.flush()
        return proposal

    def approve(
        self,
        context: TenantContext,
        proposal_id: UUID,
        approval_hash: str,
        request_id: UUID,
    ) -> SeoActionProposal:
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        proposal = self._session.scalar(
            select(SeoActionProposal)
            .where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.id == proposal_id,
            )
            .with_for_update()
        )
        if proposal is None or not hmac.compare_digest(proposal.approval_hash, approval_hash):
            raise ActionLifecycleConflict("The approval does not match the proposal.")
        if proposal.status != "proposed":
            if proposal.status == "approved":
                return proposal
            raise ActionLifecycleConflict("The proposal is not approvable.")
        if proposal.risk != "low" and proposal.actor_user_id == context.principal.user_id:
            raise ActionLifecycleConflict(
                "A different authorized member must approve this medium or high risk action."
            )
        now = datetime.now(timezone.utc)
        expiry = proposal.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            raise ActionLifecycleConflict("The proposal has expired.")
        payload = {
            "action_type": proposal.action_type,
            "target_url": proposal.target_url,
            "target_version": proposal.target_version,
            "before_state": proposal.before_state,
            "proposed_state": proposal.proposed_state,
            "risk": proposal.risk,
            "reason": proposal.reason,
        }
        expected = _digest({
            **payload,
            "proposal_id": str(proposal.id),
            "organization_id": str(proposal.organization_id),
            "website_id": str(proposal.website_id),
            "actor_user_id": str(proposal.actor_user_id),
            "expires_at": expiry.isoformat(),
        })
        if not hmac.compare_digest(proposal.approval_hash, expected):
            raise ActionLifecycleConflict("The proposal changed.")
        proposal.status = "approved"
        proposal.approved_at = now
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="seo_action.approved",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={"target_version": proposal.target_version, "risk": proposal.risk},
            )
        )
        self._session.flush()
        return proposal

    def reject(
        self,
        context: TenantContext,
        proposal_id: UUID,
        request_id: UUID,
    ) -> SeoActionProposal:
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        proposal = self._session.scalar(
            select(SeoActionProposal)
            .where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.id == proposal_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise LookupError("SEO action proposal not found.")
        if proposal.status not in {"proposed", "approved"}:
            raise ActionLifecycleConflict("The proposal cannot be rejected.")
        proposal.status = "rejected"
        proposal.error_code = "human_rejected"
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="seo_action.rejected",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={"target_version": proposal.target_version},
            )
        )
        self._session.flush()
        return proposal

    def _locked(self, context: TenantContext, proposal_id: UUID) -> SeoActionProposal:
        proposal = self._session.scalar(
            select(SeoActionProposal)
            .where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.id == proposal_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise LookupError("SEO action proposal not found.")
        return proposal

    def claim_external(
        self,
        context: TenantContext,
        proposal_id: UUID,
        request_id: UUID,
    ) -> SeoActionProposal:
        """Hand an approved proposal to one external executor (e.g. the Claude plugin)."""
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        proposal = self._locked(context, proposal_id)
        if proposal.status != "approved":
            raise ActionLifecycleConflict("Only approved proposals can be claimed.")
        expiry = proposal.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise ActionLifecycleConflict("The proposal has expired.")
        self._require_verified_website(proposal)
        proposal.status = "executing"
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="seo_action.claimed",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={"target_version": proposal.target_version, "channel": "mcp"},
            )
        )
        self._session.flush()
        return proposal

    def report_external(
        self,
        context: TenantContext,
        proposal_id: UUID,
        outcome: Literal["executed", "failed"],
        reported_state: dict[str, str],
        verifier: ActionExecutor | None,
        request_id: UUID,
    ) -> SeoActionProposal:
        """Record an external executor's report; only Reckon's own read-back can verify it."""
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        proposal = self._locked(context, proposal_id)
        executed = {**reported_state, "execution": "external-reported"}
        if proposal.status in {"executed", "verified", "failed"}:
            if outcome == "executed" and proposal.executed_state == executed:
                return proposal
            if outcome == "failed" and proposal.status == "failed" and proposal.executed_state is None:
                return proposal
            raise ActionLifecycleConflict("A different result was already recorded.")
        if proposal.status != "executing":
            raise ActionLifecycleConflict("Only claimed proposals can report a result.")
        if outcome == "failed":
            proposal.status = "failed"
            proposal.error_code = "external_execution_failed"
        else:
            proposal.executed_state = executed
            proposal.status = "executed"
            proposal.executed_at = datetime.now(timezone.utc)
            if verifier is not None:
                try:
                    proposal.verification_state = verifier.verify(proposal)
                    proposal.status = "verified"
                    proposal.verified_at = datetime.now(timezone.utc)
                except Exception as error:
                    proposal.status = "failed"
                    proposal.error_code = type(error).__name__
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action=f"seo_action.{proposal.status}",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={
                    "target_version": proposal.target_version,
                    "status": proposal.status,
                    "channel": "mcp",
                },
            )
        )
        self._session.flush()
        return proposal

    def recover_stale_claims(
        self,
        context: TenantContext,
        verifier: ActionExecutor | None,
        request_id: UUID,
        max_age: timedelta = timedelta(minutes=15),
    ) -> list[SeoActionProposal]:
        """Resolve claims whose executor never reported.

        A claim older than ``max_age`` is checked against the live page through Reckon's own
        read-back. A matching live value is recorded as verified; anything else fails closed
        with ``external_claim_timeout`` so the action can be re-proposed or rolled back.
        """
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        cutoff = datetime.now(timezone.utc) - max_age
        candidates = self._session.scalars(
            select(SeoActionProposal)
            .where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.status == "executing",
            )
            .with_for_update()
        ).all()
        recovered: list[SeoActionProposal] = []
        for proposal in candidates:
            claimed_at = self._session.scalar(
                select(func.max(AuditEvent.created_at)).where(
                    AuditEvent.organization_id == context.organization_id,
                    AuditEvent.resource_id == proposal.id,
                    AuditEvent.action == "seo_action.claimed",
                )
            )
            if claimed_at is None:
                continue
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=timezone.utc)
            if claimed_at > cutoff:
                continue
            value = proposal.proposed_state.get("value")
            if verifier is not None and value is not None:
                proposal.executed_state = {"value": value, "execution": "recovered-by-readback"}
                try:
                    proposal.verification_state = verifier.verify(proposal)
                    proposal.status = "verified"
                    proposal.executed_at = proposal.verified_at = datetime.now(timezone.utc)
                except Exception:
                    proposal.executed_state = None
                    proposal.verification_state = None
                    proposal.status = "failed"
                    proposal.error_code = "external_claim_timeout"
            else:
                proposal.status = "failed"
                proposal.error_code = "external_claim_timeout"
            self._session.add(
                AuditEvent(
                    organization_id=context.organization_id,
                    actor_user_id=context.principal.user_id,
                    action=f"seo_action.{proposal.status}",
                    resource_type="seo_action",
                    resource_id=proposal.id,
                    request_id=request_id,
                    details={
                        "target_version": proposal.target_version,
                        "status": proposal.status,
                        "channel": "recovery",
                    },
                )
            )
            recovered.append(proposal)
        self._session.flush()
        return recovered

    def execute(
        self,
        context: TenantContext,
        proposal_id: UUID,
        executor: ActionExecutor,
        request_id: UUID,
    ) -> SeoActionProposal:
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        proposal = self._session.scalar(
            select(SeoActionProposal)
            .where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.id == proposal_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise LookupError("SEO action proposal not found.")
        if proposal.status != "approved":
            raise ActionLifecycleConflict("Only approved proposals can execute.")
        self._require_verified_website(proposal)
        proposal.status = "executing"
        self._session.flush()
        try:
            executed = executor.execute(proposal)
            proposal.executed_state = executed
            proposal.status = "executed"
            proposal.executed_at = datetime.now(timezone.utc)
        except Exception as error:
            proposal.status = "failed"
            proposal.error_code = type(error).__name__
            self._session.add(
                AuditEvent(
                    organization_id=context.organization_id,
                    actor_user_id=context.principal.user_id,
                    action="seo_action.failed",
                    resource_type="seo_action",
                    resource_id=proposal.id,
                    request_id=request_id,
                    details={"target_version": proposal.target_version, "error": type(error).__name__},
                )
            )
            self._session.flush()
            raise

        try:
            verified = executor.verify(proposal)
            proposal.verification_state = verified
            proposal.status = "verified"
            proposal.verified_at = datetime.now(timezone.utc)
        except Exception as error:
            proposal.status = "failed"
            proposal.error_code = type(error).__name__
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action=f"seo_action.{proposal.status}",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={"target_version": proposal.target_version, "status": proposal.status},
            )
        )
        self._session.flush()
        return proposal

    def rollback(
        self,
        context: TenantContext,
        proposal_id: UUID,
        executor: ActionExecutor,
        request_id: UUID,
    ) -> SeoActionProposal:
        self._scope(context.organization_id)
        require_permission(context.role, OrganizationPermission.MEMBER_MANAGE)
        proposal = self._session.scalar(
            select(SeoActionProposal)
            .where(
                SeoActionProposal.organization_id == context.organization_id,
                SeoActionProposal.id == proposal_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise LookupError("SEO action proposal not found.")
        if proposal.status not in {"executed", "verified", "failed"}:
            raise ActionLifecycleConflict("Only executed or failed actions can be rolled back.")
        if proposal.rollback_state is not None:
            proposal.status = "rolled_back"
            return proposal
        self._require_verified_website(proposal)
        try:
            rollback_state = executor.rollback(proposal)
            proposal.rollback_state = rollback_state
            proposal.status = "rolled_back"
        except Exception as error:
            proposal.status = "failed"
            proposal.error_code = type(error).__name__
            self._session.flush()
            raise
        self._session.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.principal.user_id,
                action="seo_action.rolled_back",
                resource_type="seo_action",
                resource_id=proposal.id,
                request_id=request_id,
                details={"target_version": proposal.target_version},
            )
        )
        self._session.flush()
        return proposal
