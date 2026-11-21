import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  createOrganization,
  getOrganizationContext,
  listOrganizations,
} from '../lib/organizations'
import type { OrganizationContext, OrganizationPage } from '../lib/organizations'

const activeOrganizationKey = 'reckon.active-organization'

export function WorkspaceSetup({
  accessToken,
  current,
  onConnected,
}: {
  accessToken: string
  current?: OrganizationContext
  onConnected: (context: OrganizationContext) => void
}) {
  const [name, setName] = useState('')
  const [organizationId, setOrganizationId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [organizations, setOrganizations] = useState<OrganizationPage | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [checkingWorkspace, setCheckingWorkspace] = useState(() =>
    Boolean(window.sessionStorage.getItem(activeOrganizationKey)),
  )
  const idempotencyKey = useRef(crypto.randomUUID())

  useEffect(() => {
    let active = true
    void listOrganizations(accessToken)
      .then((page) => {
        if (active) {
          setOrganizations(page)
          setListError(null)
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setOrganizations(null)
          setListError(cause instanceof Error ? cause.message : 'Could not load organizations.')
        }
      })
    return () => { active = false }
  }, [accessToken, refreshVersion])

  useEffect(() => {
    const savedOrganizationId = window.sessionStorage.getItem(activeOrganizationKey)
    if (!savedOrganizationId) {
      return
    }

    let active = true
    void getOrganizationContext(accessToken, savedOrganizationId)
      .then((context) => {
        if (active) {
          onConnected(context)
          setCheckingWorkspace(false)
        }
      })
      .catch((cause: unknown) => {
        if (!active) {
          return
        }
        setCheckingWorkspace(false)
        if (
          cause instanceof Error &&
          'status' in cause &&
          cause.status === 404
        ) {
          try {
            window.sessionStorage.removeItem(activeOrganizationKey)
          } catch {
            setError(
              'The saved organization is no longer available, and this tab could not clear its saved selection.',
            )
          }
          return
        }
        setError(
          cause instanceof Error
            ? cause.message
            : 'Could not verify access to the saved organization.',
        )
      })

    return () => {
      active = false
    }
  }, [accessToken, onConnected])

  const rememberVerifiedOrganization = (context: OrganizationContext) => {
    onConnected(context)
    setEditing(false)
    setError(null)
    try {
      window.sessionStorage.setItem(activeOrganizationKey, context.organization_id)
    } catch {
      setError(
        'Membership was verified, but this tab could not remember the organization. Re-enter its ID after a reload.',
      )
    }
  }

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created = await createOrganization(
        accessToken,
        name,
        idempotencyKey.current,
      )
      const verified = await getOrganizationContext(
        accessToken,
        created.organization_id,
      )
      rememberVerifiedOrganization(verified)
      setName('')
      setRefreshVersion((value) => value + 1)
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : 'Could not create and verify the organization.',
      )
    } finally {
      setBusy(false)
    }
  }

  const handleConnect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const verified = await getOrganizationContext(accessToken, organizationId.trim())
      rememberVerifiedOrganization(verified)
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : 'Could not verify access to the organization.',
      )
    } finally {
      setBusy(false)
    }
  }

  const handleSelect = async (selectedId: string) => {
    setBusy(true)
    setError(null)
    try {
      rememberVerifiedOrganization(await getOrganizationContext(accessToken, selectedId))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not verify access to the organization.')
    } finally {
      setBusy(false)
    }
  }

  const handleLoadMore = async () => {
    if (!organizations?.next_cursor) return
    setBusy(true)
    setListError(null)
    try {
      const page = await listOrganizations(accessToken, organizations.next_cursor)
      setOrganizations({
        items: [...organizations.items, ...page.items],
        next_cursor: page.next_cursor,
      })
    } catch (cause) {
      setListError(cause instanceof Error ? cause.message : 'Could not load more organizations.')
    } finally {
      setBusy(false)
    }
  }

  if (current && !editing) {
    return (
      <div className="workspace-connected">
        <p>
          <strong>Organization ID</strong>
          <code>{current.organization_id}</code>
        </p>
        <p>
          <strong>Verified role</strong>
          <span>{current.role}</span>
        </p>
        {error && (
          <p aria-live="polite" className="workspace-setup__error" role="alert">
            {error}
          </p>
        )}
        <button
          className="button button--secondary"
          onClick={() => setEditing(true)}
          type="button"
        >
          Change workspace
        </button>
      </div>
    )
  }

  if (checkingWorkspace && !current && !editing) {
    return <p>Verifying your organization access…</p>
  }

  return (
    <div className="workspace-setup">
      <div className="workspace-organizations">
        <strong>Your organizations</strong>
        {!organizations && !listError && <p>Loading organizations…</p>}
        {organizations && organizations.items.length === 0 && !organizations.next_cursor && (
          <p>No organizations found. Create one to get started.</p>
        )}
        {organizations && organizations.items.length > 0 && (
          <ul>
            {organizations.items.map((organization) => (
              <li key={organization.organization_id}>
                <span>
                  <strong>{organization.name}</strong>
                  <small>{organization.role}</small>
                </span>
                <button
                  className="button button--secondary"
                  disabled={busy}
                  onClick={() => void handleSelect(organization.organization_id)}
                  type="button"
                >
                  {current?.organization_id === organization.organization_id ? 'Select again' : 'Select'}
                </button>
              </li>
            ))}
          </ul>
        )}
        {organizations?.next_cursor && (
          <button className="button button--secondary" disabled={busy} onClick={() => void handleLoadMore()} type="button">
            Load more
          </button>
        )}
        {listError && (
          <>
            <p className="workspace-setup__error" role="alert">{listError}</p>
            <button className="button button--secondary" disabled={busy} onClick={() => setRefreshVersion((value) => value + 1)} type="button">
              Retry organization list
            </button>
          </>
        )}
      </div>
      <form className="workspace-form" onSubmit={(event) => void handleCreate(event)}>
        <label htmlFor="organization-name">Create your organization</label>
        <div className="workspace-form__controls">
          <input
            autoComplete="organization"
            disabled={busy}
            id="organization-name"
            maxLength={200}
            onChange={(event) => {
              setName(event.target.value)
              idempotencyKey.current = crypto.randomUUID()
            }}
            placeholder="Organization name"
            required
            value={name}
          />
          <button className="button button--primary" disabled={busy} type="submit">
            {busy ? 'Working…' : 'Create'}
          </button>
        </div>
      </form>

      <form className="workspace-form" onSubmit={(event) => void handleConnect(event)}>
        <label htmlFor="organization-id">Or connect using an organization ID</label>
        <div className="workspace-form__controls">
          <input
            autoComplete="off"
            disabled={busy}
            id="organization-id"
            onChange={(event) => setOrganizationId(event.target.value)}
            placeholder="Organization ID"
            required
            value={organizationId}
          />
          <button className="button button--secondary" disabled={busy} type="submit">
            Verify access
          </button>
        </div>
      </form>

      {error && (
        <p aria-live="polite" className="workspace-setup__error" role="alert">
          {error}
        </p>
      )}
      {current && (
        <button
          className="button button--secondary"
          onClick={() => setEditing(false)}
          type="button"
        >
          Keep current workspace
        </button>
      )}
    </div>
  )
}
