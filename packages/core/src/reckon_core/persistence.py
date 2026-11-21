from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
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


class NativeAccount(Base):
    __tablename__ = "auth_accounts"

    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column("pw_hash", String(512), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret_cipher: Mapped[bytes | None] = mapped_column(
        "mfa_secret_cipher",
        LargeBinary,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class NativeVerification(Base):
    __tablename__ = "auth_verify"
    __table_args__ = (Index("ix_auth_verify_expiry", "expires_at"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativePasswordReset(Base):
    __tablename__ = "auth_reset"
    __table_args__ = (
        Index("ix_auth_reset_expiry", "expires_at"),
        Index("ix_auth_reset_user", "usr_id"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativeMfaChallenge(Base):
    __tablename__ = "auth_mfa_challenges"
    __table_args__ = (Index("ix_auth_mfa_challenges_expiry", "expires_at"),)

    challenge_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativeMfaRecoveryCode(Base):
    __tablename__ = "auth_mfa_recovery"
    __table_args__ = (
        Index("ix_auth_mfa_recovery_user", "usr_id"),
    )

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativeSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_expiry", "expires_at"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NativeAuthRateLimit(Base):
    __tablename__ = "auth_limits"
    __table_args__ = (Index("ix_auth_limits_expiry", "expires_at"),)

    bucket_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NativeAuthEvent(Base):
    __tablename__ = "auth_events"
    __table_args__ = (Index("ix_auth_events_user_created", "usr_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column("req_id", Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class PlatformAdministrator(Base):
    __tablename__ = "platform_admin"
    __table_args__ = (CheckConstraint("slot = 1", name="ck_platform_admin_slot"),)

    slot: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    user_id: Mapped[UUID] = mapped_column(
        "usr_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
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
    __table_args__ = (
        Index(
            "ix_org_members_user_active_org", "usr_id", "org_id",
            postgresql_where=text("active = true"),
        ),
    )

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
    version: Mapped[UUID] = mapped_column(Uuid, nullable=False, default=uuid4, onupdate=uuid4)


class OrganizationChange(Base):
    __tablename__ = "org_changes"
    __table_args__ = (
        UniqueConstraint("org_id", "actor_usr_id", "idem_key", name="uq_org_change_request"),
        UniqueConstraint("org_id", "id", name="uq_org_change_tenant_id"),
        CheckConstraint("action IN ('invite', 'role_change')", name="ck_org_change_action"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column("org_id", Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column("actor_usr_id", Uuid, ForeignKey("users.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column("idem_key", String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    target_user_id: Mapped[UUID | None] = mapped_column("target_usr_id", Uuid, ForeignKey("users.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(OrganizationRole, name="org_role", values_callable=lambda roles: [role.value for role in roles]), nullable=False
    )
    target_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationInvitation(Base):
    __tablename__ = "org_invites"
    __table_args__ = (
        UniqueConstraint("change_id", name="uq_org_invite_change"),
        ForeignKeyConstraint(
            ["org_id", "change_id"], ["org_changes.org_id", "org_changes.id"], ondelete="CASCADE"
        ),
        Index("ix_org_invite_email", "email", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column("org_id", Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    change_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(OrganizationRole, name="org_role", values_callable=lambda roles: [role.value for role in roles]), nullable=False
    )
    inviter_user_id: Mapped[UUID] = mapped_column("inviter_usr_id", Uuid, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[UUID | None] = mapped_column("accepted_usr_id", Uuid, ForeignKey("users.id"), nullable=True)
    delivery_state: Mapped[str] = mapped_column(String(20), nullable=False, default="unconfirmed")


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


class OrganizationModelSettings(Base):
    __tablename__ = "org_model_settings"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('openai', 'anthropic')", name="ck_org_model_settings_provider"
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        "org_id", Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[Literal["openai", "anthropic"]] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    encrypted_key: Mapped[bytes] = mapped_column("key_cipher", LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ModelUsageReservation(Base):
    __tablename__ = "model_usage"
    __table_args__ = (
        UniqueConstraint("org_id", "idem_key", name="uq_model_usage_org_idem"),
        CheckConstraint(
            "status IN ('reserved', 'settled')", name="ck_model_usage_status"
        ),
        CheckConstraint(
            "max_input > 0 AND max_output > 0", name="ck_model_usage_max"
        ),
        CheckConstraint(
            "(status = 'reserved' AND input_tokens IS NULL AND output_tokens IS NULL "
            "AND settled_at IS NULL) OR "
            "(status = 'settled' AND input_tokens IS NOT NULL AND input_tokens >= 0 "
            "AND output_tokens IS NOT NULL AND output_tokens >= 0 AND settled_at IS NOT NULL)",
            name="ck_model_usage_settlement",
        ),
        Index("ix_model_usage_org_started", "org_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        "org_id", Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        "actor_usr_id", Uuid, ForeignKey("users.id"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    request_id: Mapped[UUID] = mapped_column("req_id", Uuid, nullable=False)
    idempotency_key: Mapped[str] = mapped_column("idem_key", String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column("req_hash", String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    max_input_tokens: Mapped[int] = mapped_column("max_input", BigInteger, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column("max_output", BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class CrawlRun(Base):
    __tablename__ = "site_crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'disallowed', 'failed')",
            name="ck_site_crawl_runs_status",
        ),
        CheckConstraint(
            "bytes_read IS NULL OR bytes_read >= 0",
            name="ck_site_crawl_runs_bytes_read",
        ),
        CheckConstraint(
            "h1_count IS NULL OR h1_count >= 0",
            name="ck_site_crawl_runs_h1_count",
        ),
        CheckConstraint(
            "canonical_count IS NULL OR canonical_count >= 0",
            name="ck_site_crawl_runs_canonical_count",
        ),
        CheckConstraint(
            "sitemap_declaration_count IS NULL OR sitemap_declaration_count >= 0",
            name="ck_site_crawl_runs_sitemap_declarations",
        ),
        CheckConstraint(
            "sitemap_rejected_count IS NULL OR sitemap_rejected_count >= 0",
            name="ck_site_crawl_runs_sitemap_rejected",
        ),
        CheckConstraint(
            "redirect_count IS NULL OR redirect_count >= 0",
            name="ck_site_crawl_runs_redirects",
        ),
        ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
        Index("ix_site_crawl_runs_org_started", "org_id", "started_at"),
        UniqueConstraint("org_id", "idem_key", name="uq_site_crawl_runs_org_idem"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        "org_id",
        Uuid,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    website_id: Mapped[UUID] = mapped_column("site_id", Uuid, nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(
        "actor_usr_id",
        Uuid,
        ForeignKey("users.id"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column("req_id", Uuid, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        "idem_key",
        String(128),
        nullable=False,
    )
    request_hash: Mapped[str] = mapped_column("req_hash", String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    http_status: Mapped[int | None] = mapped_column(
        "http_status",
        Integer,
        nullable=True,
    )
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bytes_read: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    audit_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audit_findings: Mapped[list[dict[str, str]] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    meta_robots_noindex: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    x_robots_noindex: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    canonical_link_count: Mapped[int | None] = mapped_column(
        "canonical_count",
        Integer,
        nullable=True,
    )
    robots_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sitemap_urls: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    sitemap_evidence: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    sitemap_declaration_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    sitemap_rejected_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    sitemap_discovery_truncated: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    meta_description: Mapped[str | None] = mapped_column(
        "meta_desc",
        String(1000),
        nullable=True,
    )
    h1_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    internal_urls: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    page_evidence: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    redirect_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CrawlSchedule(Base):
    __tablename__ = "crawl_schedules"
    __table_args__ = (
        UniqueConstraint("org_id", "site_id", name="uq_crawl_schedule_org_site"),
        ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
        Index("ix_crawl_schedules_next_active", "active", "next_run_at"),
        CheckConstraint("frequency IN ('daily', 'weekly')", name="ck_crawl_schedule_frequency"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column("org_id", Uuid, nullable=False)
    website_id: Mapped[UUID] = mapped_column("site_id", Uuid, nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(
        "actor_usr_id",
        Uuid,
        ForeignKey("users.id"),
        nullable=False,
    )
    frequency: Mapped[Literal["daily", "weekly"]] = mapped_column(
        String(10),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class SeoActionProposal(Base):
    __tablename__ = "seo_action_proposals"
    __table_args__ = (
        UniqueConstraint("org_id", "idem_key", name="uq_seo_action_org_idem"),
        UniqueConstraint("org_id", "id", name="uq_seo_action_tenant_id"),
        CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_seo_action_risk"),
        CheckConstraint(
            "status IN ('proposed','approved','rejected','executing','executed','verified','failed','rolled_back')",
            name="ck_seo_action_status",
        ),
        ForeignKeyConstraint(
            ["site_id", "org_id"],
            ["sites.id", "sites.org_id"],
            ondelete="CASCADE",
        ),
        Index("ix_seo_action_org_created", "org_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column("org_id", Uuid, nullable=False)
    website_id: Mapped[UUID] = mapped_column("site_id", Uuid, nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(
        "actor_usr_id", Uuid, ForeignKey("users.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column("idem_key", String(128), nullable=False)
    proposal_hash: Mapped[str] = mapped_column("proposal_hash", String(64), nullable=False)
    approval_hash: Mapped[str] = mapped_column("approval_hash", String(64), nullable=False)
    action_type: Mapped[str] = mapped_column("action_type", String(32), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    before_state: Mapped[dict[str, str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    proposed_state: Mapped[dict[str, str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    executed_state: Mapped[dict[str, str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    verification_state: Mapped[dict[str, str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    rollback_state: Mapped[dict[str, str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
