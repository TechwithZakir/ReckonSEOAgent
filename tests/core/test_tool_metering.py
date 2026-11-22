from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from reckon_core.persistence import Base, Organization, OrganizationMembership, User
from reckon_core.tenancy import (
    AuthenticatedPrincipal,
    OrganizationRole,
    TenantContext,
)
from reckon_core.tool_metering import ToolCallBudgetExceeded, ToolCallMeter


def _context(session, name: str) -> TenantContext:
    user = User()
    organization = Organization(name=name)
    session.add_all((user, organization))
    session.flush()
    session.add(
        OrganizationMembership(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
            is_active=True,
        )
    )
    session.flush()
    return TenantContext(
        AuthenticatedPrincipal(user.id, "issuer", name), organization.id, OrganizationRole.OWNER
    )


def test_daily_tool_call_cap_is_enforced_per_organization() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        first = _context(session, "org-a")
        second = _context(session, "org-b")
        meter = ToolCallMeter(session)

        assert meter.record(first, "reckon.crawl.list", uuid4(), 2) == 1
        assert meter.record(first, "reckon.seo_action.claim", uuid4(), 2) == 2
        with pytest.raises(ToolCallBudgetExceeded):
            meter.record(first, "reckon.crawl.list", uuid4(), 2)

        # Another organization has its own independent budget.
        assert meter.record(second, "reckon.crawl.list", uuid4(), 2) == 1
    engine.dispose()
