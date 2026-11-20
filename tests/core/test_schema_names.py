from reckon_core.persistence import Base


def test_physical_database_schema_uses_short_table_and_column_names() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "identities",
        "orgs",
        "org_members",
        "org_create_reqs",
        "audit_events",
        "sites",
        "site_create_reqs",
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
