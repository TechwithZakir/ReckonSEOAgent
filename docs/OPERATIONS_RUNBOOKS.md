# Operations runbooks (not yet drilled)

These procedures describe what must be true in production. None has been executed: the
repository has no infrastructure definition, so each needs a real environment and an owner
before it counts as done.

## Browser and crawler egress isolation

Goal: crawler, verifier and any browser worker can only reach the public internet, never
internal services, cloud metadata or the database.

1. Run crawl, verification and browser workers in their own network namespace or VPC subnet,
   separate from the API and database.
2. Default-deny egress. Allow DNS to a controlled resolver and TCP 80/443 to the public
   internet only. Block RFC 1918, link-local (169.254.0.0/16, including 169.254.169.254),
   loopback, CGNAT and IPv6 ULA/link-local ranges.
3. Give workers no credentials beyond a queue and a narrow database role. No cloud instance
   role; require IMDSv2 hop limit 1 or disable metadata.
4. Keep the application-level pinned-DNS and redirect checks (`crawl_security`); the network
   rule is a second layer, not a replacement.
5. Drill: from the worker, request `http://169.254.169.254/`, the database host, an internal
   hostname and a public page. Only the public page may succeed. Record the result here.

## Backup and restore

1. PostgreSQL: continuous WAL archiving plus a nightly base backup, encrypted, in a separate
   account or region. Retain 14 days minimum.
2. Secrets (encryption keys for stored model keys, webhook and OIDC secrets) are backed up
   separately from the database. A database restore without `key_cipher`'s key loses stored
   model keys.
3. Redis holds only transient queue and rate state; it needs no restore.
4. Drill, at least quarterly: restore the latest backup to an isolated instance, run
   `alembic upgrade head`, run `pytest tests -q` against it, and compare row counts for
   `orgs`, `sites`, `seo_action_proposals` and `audit_events`. Record restore time (RTO) and
   data age (RPO) here.
5. Actions in `executing` after a restore are settled by `recover_stale_claims` through a live
   read-back; review them before re-enabling the plugin.
