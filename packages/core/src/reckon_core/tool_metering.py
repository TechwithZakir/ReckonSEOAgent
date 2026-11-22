"""Deterministic per-organization daily metering of governed tool calls (MCP and actions)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from reckon_core.persistence import AuditEvent, Organization
from reckon_core.repositories import utc_day
from reckon_core.tenancy import TenantContext

TOOL_CALL_ACTION = "mcp.tool_call"


class ToolCallBudgetExceeded(Exception):
    pass


class ToolCallMeter:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        context: TenantContext,
        tool_name: str,
        request_id: UUID,
        daily_limit: int,
    ) -> int:
        """Reserve one tool call for today; raises when the organization's daily cap is reached.

        Returns the number of calls used today including this one. The organization row is
        locked so concurrent calls cannot overshoot the cap.
        """
        organization_id = context.organization_id
        if self._session.get_bind().dialect.name == "postgresql":
            self._session.execute(
                text("SELECT set_config('app.org_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )
        self._session.scalar(
            select(Organization.id).where(Organization.id == organization_id).with_for_update()
        )
        now = datetime.now(timezone.utc)
        day_start, day_end = utc_day(now)
        used = self._session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == TOOL_CALL_ACTION,
                AuditEvent.created_at >= day_start,
                AuditEvent.created_at < day_end,
            )
        ) or 0
        if used >= daily_limit:
            raise ToolCallBudgetExceeded
        self._session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=context.principal.user_id,
                action=TOOL_CALL_ACTION,
                resource_type="mcp_tool",
                resource_id=organization_id,
                request_id=request_id,
                details={"tool": tool_name[:64], "used": str(used + 1), "limit": str(daily_limit)},
            )
        )
        self._session.flush()
        return used + 1
