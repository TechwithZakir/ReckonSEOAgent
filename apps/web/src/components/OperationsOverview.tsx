import type { AuthStatus } from '../auth/AuthContext'
import type { OidcConfigResult } from '../auth/oidc'
import type { PlatformHealth } from '../lib/service-health'

type OperationsOverviewProps = {
  authStatus: AuthStatus
  configKind: OidcConfigResult['kind']
  workspaceConnected: boolean
  health: PlatformHealth
  actionLabel: string
  actionDisabled: boolean
  onAction: () => void
}

export function OperationsOverview({
  authStatus,
  configKind,
  workspaceConnected,
  health,
  actionLabel,
  actionDisabled,
  onAction,
}: OperationsOverviewProps) {
  const accountState =
    authStatus === 'initializing'
      ? 'Checking access'
      : authStatus === 'error' || configKind === 'invalid'
        ? 'Needs attention'
        : authStatus === 'signed-in'
          ? 'Signed in'
          : configKind === 'missing'
            ? 'Setup required'
            : 'Sign-in required'

  const healthState =
    health.api.state === 'unavailable' || health.database.state === 'unavailable'
      ? 'Needs attention'
      : health.api.state === 'checking' || health.database.state === 'checking'
        ? 'Checking'
        : 'Operational'

  return (
    <section aria-labelledby="operations-title" className="operations">
      <div className="operations__heading">
        <div>
          <p className="section-kicker">YOUR WORKSPACE</p>
          <h2 id="operations-title">SEO operations at a glance</h2>
        </div>
        <span>Live status &amp; next steps</span>
      </div>
      <div className="operations__grid">
        <article className="operations-card operations-card--account">
          <div className="operations-card__top">
            <span className="operations-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="8" r="3.5" />
                <path d="M5 20v-1a7 7 0 0 1 14 0v1" />
              </svg>
            </span>
            <span className="operations-card__tag">ACCOUNT</span>
          </div>
          <h3>Workspace access</h3>
          <strong className="operations-card__value">{accountState}</strong>
          <p>
            {workspaceConnected
              ? 'Your organization membership is connected.'
              : authStatus === 'signed-in'
                ? 'Connect an organization to access its websites.'
                : 'Connect an account to access your organization.'}
          </p>
          <button className="operations-card__link" disabled={actionDisabled} onClick={onAction} type="button">
            {actionLabel} <span aria-hidden="true">→</span>
          </button>
        </article>

        <article className="operations-card operations-card--evidence">
          <div className="operations-card__top">
            <span className="operations-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="16" rx="3" />
                <path d="M3 9h18M7 6.5h.01M10 6.5h.01M8 14h8M8 17h5" />
              </svg>
            </span>
            <span className="operations-card__tag">SITE EVIDENCE</span>
          </div>
          <h3>Homepage audits</h3>
          <strong className="operations-card__value">
            {workspaceConnected ? 'View your websites' : 'Not connected'}
          </strong>
          <p>
            {workspaceConnected
              ? 'Open a verified website to run a crawl or review its findings.'
              : 'Your crawl history and findings appear after you connect a workspace.'}
          </p>
          <button className="operations-card__link" disabled={actionDisabled} onClick={onAction} type="button">
            {workspaceConnected ? 'Open websites' : 'Get started'} <span aria-hidden="true">→</span>
          </button>
        </article>

        <article className="operations-card operations-card--health">
          <div className="operations-card__top">
            <span className="operations-card__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12h4l3-7 4 14 3-7h4" />
              </svg>
            </span>
            <span className="operations-card__tag">LIVE SYSTEM</span>
          </div>
          <h3>Platform health</h3>
          <strong className="operations-card__value">{healthState}</strong>
          <p>API: {health.api.state} · Database: {health.database.state}</p>
          <a className="operations-card__link" href="#health-title">
            View system status <span aria-hidden="true">→</span>
          </a>
        </article>
      </div>
    </section>
  )
}
