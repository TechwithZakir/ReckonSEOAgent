from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from reckon_core.tenancy import OrganizationRole


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ExternalIdentity(Base):
    __tablename__ = "identities"

    issuer: Mapped[str] = mapped_column(String(512), primary_key=True)
    subject: Mapped[str] = mapped_column(String(512), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id",
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Organization(Base):
    __tablename__ = "orgs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class OrganizationMembership(Base):
    __tablename__ = "org_members"

    organization_id: Mapped[UUID] = mapped_column(
        "org_id",
        Uuid,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        "usr_id",
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(
            OrganizationRole,
            name="org_role",
            values_callable=lambda role_enum: [role.value for role in role_enum],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        "active",
        Boolean,
        nullable=False,
        default=True,
    )


class OrganizationCreationRequest(Base):
    __tablename__ = "org_create_reqs"

    user_id: Mapped[UUID] = mapped_column(
        "usr_id",
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        "idem_key",
        String(128),
        primary_key=True,
    )
    request_hash: Mapped[str] = mapped_column("req_hash", String(64), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(
        "org_id",
        Uuid,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        "org_id",
        Uuid,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        "actor_usr_id",
        Uuid,
        ForeignKey("users.id"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column("res_type", String(100), nullable=False)
    resource_id: Mapped[UUID] = mapped_column("res_id", Uuid, nullable=False)
    request_id: Mapped[UUID] = mapped_column("req_id", Uuid, nullable=False)
    details: Mapped[dict[str, str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class Website(Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("org_id", "host", name="uq_sites_org_host"),
        UniqueConstraint("id", "org_id", name="uq_sites_id_org"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        "org_id",
        Uuid,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    host: Mapped[str] = mapped_column(String(253), nullable=False)
    scheme: Mapped[str] = mapped_column(String(5), nullable=False)
    is_verified: Mapped[bool] = mapped_column(
        "verified",
        Boolean,
        nullable=False,
        default=False,
    )
    verification_token: Mapped[str] = mapped_column(
        "ver_tok",
        String(64),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        "verified_at",
        DateTime(timezone=True),
        nullable=True,
    )


class WebsiteCreationRequest(Base):
    __tablename__ = "site_create_reqs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        "org_id",
        Uuid,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        "idem_key",
        String(128),
        primary_key=True,
    )
    request_hash: Mapped[str] = mapped_column("req_hash", String(64), nullable=False)
    website_id: Mapped[UUID] = mapped_column(
        "site_id",
        Uuid,
        nullable=False,
        unique=True,
    )
