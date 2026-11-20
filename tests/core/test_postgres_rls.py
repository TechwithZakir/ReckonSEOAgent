from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from reckon_api.config import Settings


def test_postgres_rls_isolates_organization_rows() -> None:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("RECKON_DATABASE_URL is not configured.")

    engine = create_engine(settings.database_url.get_secret_value())
    first_id, second_id = str(uuid4()), str(uuid4())

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                role = connection.execute(
                    text(
                        """
                        SELECT r.rolsuper, r.rolbypassrls
                        FROM pg_roles AS r
                        WHERE r.rolname = current_user
                        """
                    )
                ).one()
                assert role.rolsuper is False
                assert role.rolbypassrls is False

                guarded_tables = {
                    row.relname: (row.relrowsecurity, row.relforcerowsecurity)
                    for row in connection.execute(
                        text(
                            """
                            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                            FROM pg_class AS c
                            JOIN pg_namespace AS n ON n.oid = c.relnamespace
                            WHERE n.nspname = current_schema()
                              AND c.relname IN (
                                  'sites', 'site_create_reqs', 'site_crawl_runs'
                              )
                            """
                        )
                    )
                }
                assert guarded_tables == {
                    "sites": (True, True),
                    "site_create_reqs": (True, True),
                    "site_crawl_runs": (True, True),
                }

                for organization_id, name in (
                    (first_id, "rls-check-a"),
                    (second_id, "rls-check-b"),
                ):
                    user_id = str(uuid4())
                    connection.execute(
                        text(
                            """
                            INSERT INTO users (id, created_at)
                            VALUES (CAST(:user_id AS uuid), now())
                            """
                        ),
                        {"user_id": user_id},
                    )
                    connection.execute(
                        text("SELECT set_config('app.org_id', :org_id, true)"),
                        {"org_id": organization_id},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO orgs (id, name, created_at)
                            VALUES (CAST(:org_id AS uuid), :name, now())
                            """
                        ),
                        {"org_id": organization_id, "name": name},
                    )
                    site_id = str(uuid4())
                    connection.execute(
                        text(
                            """
                            INSERT INTO sites (
                                id, org_id, host, scheme, verified, ver_tok,
                                created_at, verified_at
                            )
                            VALUES (
                                CAST(:site_id AS uuid), CAST(:org_id AS uuid),
                                :host, 'https', false, 'rls-test-token', now(), NULL
                            )
                            """
                        ),
                        {
                            "site_id": site_id,
                            "org_id": organization_id,
                            "host": f"{name}.example.org",
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO site_create_reqs (org_id, idem_key, req_hash, site_id)
                            VALUES (
                                CAST(:org_id AS uuid), :idem_key, repeat('a', 64),
                                CAST(:site_id AS uuid)
                            )
                            """
                        ),
                        {
                            "org_id": organization_id,
                            "idem_key": f"rls-{name}",
                            "site_id": site_id,
                        },
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO site_crawl_runs (
                                id, org_id, site_id, actor_usr_id, req_id, idem_key,
                                req_hash, status, started_at
                            )
                            VALUES (
                                CAST(:run_id AS uuid), CAST(:org_id AS uuid),
                                CAST(:site_id AS uuid), CAST(:user_id AS uuid),
                                CAST(:request_id AS uuid), :idem_key, repeat('b', 64),
                                'running', now()
                            )
                            """
                        ),
                        {
                            "run_id": str(uuid4()),
                            "org_id": organization_id,
                            "site_id": site_id,
                            "user_id": user_id,
                            "request_id": str(uuid4()),
                            "idem_key": f"crawl-{name}",
                        },
                    )

                connection.execute(
                    text("SELECT set_config('app.org_id', :org_id, true)"),
                    {"org_id": first_id},
                )
                visible = connection.execute(
                    text("SELECT id::text, name FROM orgs ORDER BY name")
                ).all()
                assert [(row.id, row.name) for row in visible] == [
                    (first_id, "rls-check-a")
                ]
                assert connection.execute(
                    text("SELECT host FROM sites")
                ).scalars().all() == ["rls-check-a.example.org"]
                assert connection.execute(
                    text("SELECT idem_key FROM site_create_reqs")
                ).scalars().all() == ["rls-rls-check-a"]
                assert connection.execute(
                    text("SELECT idem_key FROM site_crawl_runs")
                ).scalars().all() == ["crawl-rls-check-a"]

                connection.execute(
                    text("SELECT set_config('app.org_id', '', true)")
                )
                assert connection.execute(
                    text("SELECT count(*) FROM orgs")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM sites")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM site_create_reqs")
                ).scalar_one() == 0
                assert connection.execute(
                    text("SELECT count(*) FROM site_crawl_runs")
                ).scalar_one() == 0
            finally:
                transaction.rollback()

            assert connection.execute(
                text("SELECT count(*) FROM orgs")
            ).scalar_one() == 0
    finally:
        engine.dispose()
