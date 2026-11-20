import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { OrganizationContext } from '../lib/organizations'
import {
  createWebsite,
  listWebsites,
  verifyWebsite,
} from '../lib/websites'
import type { Website } from '../lib/websites'

function canManageWebsites(role: OrganizationContext['role']): boolean {
  return role === 'owner' || role === 'admin'
}

export function WebsiteOnboarding({
  accessToken,
  organization,
}: {
  accessToken: string
  organization: OrganizationContext
}) {
  const [url, setUrl] = useState('')
  const [websites, setWebsites] = useState<Website[]>([])
  const [loading, setLoading] = useState(true)
  const [busyWebsiteId, setBusyWebsiteId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const idempotencyKey = useRef(crypto.randomUUID())
  const mayManage = canManageWebsites(organization.role)

  useEffect(() => {
    let active = true
    void listWebsites(accessToken, organization.organization_id)
      .then((items) => {
        if (active) {
          setWebsites(items)
          setError(null)
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(
            cause instanceof Error
              ? cause.message
              : 'Could not load websites for this organization.',
          )
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [accessToken, organization.organization_id, refreshVersion])

  const refresh = useCallback(() => {
    setLoading(true)
    setRefreshVersion((version) => version + 1)
  }, [])

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const website = await createWebsite(
        accessToken,
        organization.organization_id,
        url,
        idempotencyKey.current,
      )
      setWebsites((current) => [
        ...current.filter((item) => item.website_id !== website.website_id),
        website,
      ])
      setUrl('')
      idempotencyKey.current = crypto.randomUUID()
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : 'Could not register the website.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleVerify = async (website: Website) => {
    setBusyWebsiteId(website.website_id)
    setError(null)
    try {
      await verifyWebsite(
        accessToken,
        organization.organization_id,
        website.website_id,
      )
      setWebsites((current) =>
        current.map((item) =>
          item.website_id === website.website_id
            ? {
                ...item,
                verification_status: 'verified',
                dns_txt_value: null,
              }
            : item,
        ),
      )
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : 'Could not verify the website.',
      )
    } finally {
      setBusyWebsiteId(null)
    }
  }

  return (
    <section aria-labelledby="websites-title" className="website-onboarding">
      <div className="website-onboarding__heading">
        <div>
          <p className="section-kicker">WEBSITE ONBOARDING</p>
          <h3 id="websites-title">Verify a website you control</h3>
        </div>
        <button
          className="button button--secondary"
          disabled={loading || busyWebsiteId !== null}
          onClick={refresh}
          type="button"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      <p className="website-onboarding__description">
        Add the site’s DNS TXT record to prove control. Registration does not
        start a crawl; crawler network protections are a separate step.
      </p>

      {mayManage ? (
        <form
          className="website-form"
          onSubmit={(event) => void handleCreate(event)}
        >
          <label htmlFor="website-origin">Website origin</label>
          <div className="workspace-form__controls">
            <input
              autoComplete="url"
              disabled={submitting}
              id="website-origin"
              maxLength={2048}
              onChange={(event) => {
                setUrl(event.target.value)
                idempotencyKey.current = crypto.randomUUID()
              }}
              placeholder="https://example.com"
              required
              type="url"
              value={url}
            />
            <button
              className="button button--primary"
              disabled={submitting}
              type="submit"
            >
              {submitting ? 'Adding…' : 'Add website'}
            </button>
          </div>
        </form>
      ) : (
        <p className="website-onboarding__notice">
          Only organization owners and admins can add or verify websites.
        </p>
      )}

      {error && (
        <p aria-live="polite" className="workspace-setup__error" role="alert">
          {error}
        </p>
      )}

      {!loading && websites.length === 0 && (
        <p className="website-onboarding__empty">No websites are registered yet.</p>
      )}

      <div aria-live="polite" className="website-list">
        {websites.map((website) => (
          <article className="website-item" key={website.website_id}>
            <div className="website-item__heading">
              <strong>{website.origin}</strong>
              <span
                className={`status-label ${
                  website.verification_status === 'verified'
                    ? 'status-label--healthy'
                    : 'status-label--checking'
                }`}
              >
                {website.verification_status === 'verified'
                  ? 'Verified'
                  : 'Verification pending'}
              </span>
            </div>
            {website.verification_status === 'pending' && (
              <>
                {website.dns_txt_value ? (
                  <dl className="website-item__dns">
                    <div>
                      <dt>TXT record name</dt>
                      <dd>
                        <code>{website.dns_txt_name}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>TXT record value</dt>
                      <dd>
                        <code>{website.dns_txt_value}</code>
                      </dd>
                    </div>
                  </dl>
                ) : (
                  <p className="website-onboarding__notice">
                    Ask an organization owner or admin to complete DNS verification.
                  </p>
                )}
                {mayManage && (
                  <button
                    className="button button--secondary"
                    disabled={busyWebsiteId !== null}
                    onClick={() => void handleVerify(website)}
                    type="button"
                  >
                    {busyWebsiteId === website.website_id
                      ? 'Checking DNS…'
                      : 'Verify DNS record'}
                  </button>
                )}
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
