from reckon_core.persistence import Base


def test_physical_database_schema_uses_short_table_and_column_names() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "identities",
        "auth_accounts",
        "auth_verify",
        "auth_reset",
        "auth_sessions",
        "auth_limits",
        "auth_events",
        "platform_admin",
        "orgs",
        "org_members",
        "org_changes",
        "org_invites",
        "org_create_reqs",
        "audit_events",
        "model_usage",
        "org_model_settings",
        "sites",
        "site_create_reqs",
        "site_crawl_runs",
    }
    assert set(Base.metadata.tables["identities"].columns.keys()) == {
        "issuer",
        "subject",
        "usr_id",
    }
    assert set(Base.metadata.tables["org_members"].columns.keys()) == {
        "org_id",
        "usr_id",
        "role",
        "active",
        "version",
    }
    assert set(Base.metadata.tables["org_create_reqs"].columns.keys()) == {
        "usr_id",
        "idem_key",
        "req_hash",
        "org_id",
    }
    assert set(Base.metadata.tables["audit_events"].columns.keys()) == {
        "id",
        "org_id",
        "actor_usr_id",
        "action",
        "res_type",
        "res_id",
        "req_id",
        "details",
        "created_at",
    }
    assert set(Base.metadata.tables["model_usage"].columns.keys()) == {
        "id", "org_id", "actor_usr_id", "task_id", "req_id", "idem_key", "req_hash",
        "provider", "model", "max_input", "max_output", "status", "input_tokens",
        "output_tokens", "started_at", "settled_at",
    }
    assert set(Base.metadata.tables["org_model_settings"].columns.keys()) == {
        "org_id", "provider", "model", "endpoint_url", "key_cipher", "updated_at",
    }
    assert set(Base.metadata.tables["sites"].columns.keys()) == {
        "id",
        "org_id",
        "host",
        "scheme",
        "verified",
        "ver_tok",
        "created_at",
        "verified_at",
    }
    assert set(Base.metadata.tables["site_create_reqs"].columns.keys()) == {
        "org_id",
        "idem_key",
        "req_hash",
        "site_id",
    }
    assert set(Base.metadata.tables["site_crawl_runs"].columns.keys()) == {
        "id",
        "org_id",
        "site_id",
        "actor_usr_id",
        "req_id",
        "idem_key",
        "req_hash",
        "status",
        "started_at",
        "completed_at",
        "final_url",
        "http_status",
        "content_type",
        "bytes_read",
        "title",
        "audit_version",
        "audit_findings",
        "meta_robots_noindex",
        "x_robots_noindex",
        "canonical_url",
        "canonical_count",
        "robots_status_code",
        "sitemap_urls",
        "sitemap_evidence",
        "sitemap_declaration_count",
        "sitemap_rejected_count",
        "sitemap_discovery_truncated",
        "meta_desc",
        "h1_count",
        "redirect_count",
        "error_code",
    }
