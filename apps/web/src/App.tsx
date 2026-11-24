import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode, SVGProps } from 'react'
import { useAuth } from './auth/AuthContext'
import { CrawlWorkflow } from './components/CrawlWorkflow'
import { AIModelSettings } from './components/AIModelSettings'
import { LoginPage } from './components/LoginPage'
import { PublicAuditTool } from './components/PublicAuditTool'
import { PublicLanding } from './components/PublicLanding'
import { InvitationsPage } from './components/InvitationsPage'
import { PlatformAccess } from './components/PlatformAccess'
import { PlatformOperations } from './components/PlatformOperations'
import { OperationsOverview } from './components/OperationsOverview'
import { AccountSecurity } from './components/AccountSecurity'
import { OrganizationMembers } from './components/OrganizationMembers'
import { WorkspacePages } from './components/WorkspacePages'
import { WorkspaceSetup } from './components/WorkspaceSetup'
import { WebsiteOnboarding } from './components/WebsiteOnboarding'
import { restoreSavedOrganization } from './lib/organizations'
import type { OrganizationContext } from './lib/organizations'
import { checkPlatformHealth } from './lib/service-health'
import type { PlatformHealth, ServiceState } from './lib/service-health'
import './App.css'

type IconName =
  | 'activity'
  | 'arrow'
  | 'audit'
  | 'book'
  | 'check'
  | 'chevron'
  | 'globe'
  | 'grid'
  | 'menu'
  | 'moon'
  | 'spark'
  | 'sun'
  | 'users'

function Icon({
  name,
  ...props
}: SVGProps<SVGSVGElement> & { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    activity: (
      <>
        <path d="M3 12h4l3-8 4 16 3-8h4" />
      </>
    ),
    arrow: (
      <>
        <path d="M7 17 17 7" />
        <path d="M8 7h9v9" />
      </>
    ),
    audit: (
      <>
        <path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-3" />
        <path d="M16 3h5v5" />
        <path d="m10 14 2 2 9-9" />
      </>
    ),
    book: (
      <>
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
        <path d="M8 7h8M8 11h7" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    chevron: <path d="m9 18 6-6-6-6" />,
    globe: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    moon: <path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z" />,
    spark: (
      <>
        <path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3Z" />
        <path d="m19 14 1 2.5 2.5 1-2.5 1L19 21l-1-2.5-2.5-1 2.5-1L19 14Z" />
      </>
    ),
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
      </>
    ),
    users: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="10" cy="7" r="4" />
        <path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
      </>
    ),
  }

  return (
    <svg
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
      {...props}
    >
      {paths[name]}
    </svg>
  )
}

type NavigationItem = {
  label: string
  icon: IconName
  available: boolean
}

const navigationGroups: { label: string; items: NavigationItem[] }[] = [
  {
    label: 'Start',
    items: [
      { label: 'Overview', icon: 'grid', available: true },
      { label: 'Quick audit', icon: 'audit', available: true },
      { label: 'Websites', icon: 'globe', available: true },
    ],
  },
  {
    label: 'Audit & optimize',
    items: [
      { label: 'Technical audits', icon: 'audit', available: true },
      { label: 'Site Bot', icon: 'activity', available: true },
      { label: 'Recommendations', icon: 'spark', available: true },
      { label: 'Keywords', icon: 'spark', available: true },
      { label: 'Content Studio', icon: 'book', available: true },
      { label: 'E-Commerce', icon: 'grid', available: true },
      { label: 'Media & Query', icon: 'audit', available: true },
      { label: 'Emerging / GEO', icon: 'spark', available: true },
      { label: 'LinkPilot', icon: 'arrow', available: true },
      { label: 'Local SEO', icon: 'globe', available: true },
      { label: 'Enterprise', icon: 'users', available: true },
    ],
  },
  {
    label: 'Automation',
    items: [
      { label: 'Approvals', icon: 'check', available: true },
      { label: 'Agent activity', icon: 'activity', available: true },
      { label: 'Ask SEO Copilot', icon: 'spark', available: true },
      { label: 'Reports', icon: 'book', available: true },
    ],
  },
  {
    label: 'Workspace',
    items: [
      { label: 'Agency Workspace', icon: 'users', available: true },
      { label: 'Integrations', icon: 'grid', available: true },
      { label: 'System settings', icon: 'spark', available: true },
      { label: 'Account security', icon: 'users', available: true },
    ],
  },
  {
    label: 'Platform',
    items: [
      { label: 'Platform operations', icon: 'activity', available: true },
    ],
  },
]

const initialHealth: PlatformHealth = {
  api: { state: 'checking', message: 'Checking API…' },
  database: { state: 'checking', message: 'Checking database…' },
}

function stateLabel(state: ServiceState): string {
  switch (state) {
    case 'healthy':
      return 'Operational'
    case 'unavailable':
      return 'Unavailable'
    case 'checking':
      return 'Checking'
  }
}

function HealthRow({
  label,
  state,
  message,
}: {
  label: string
  state: ServiceState
  message: string
}) {
  return (
    <div className="health-row">
      <div className="health-row__service">
        <span className={`status-dot status-dot--${state}`} aria-hidden="true" />
        <div>
          <strong>{label}</strong>
          <p>{message}</p>
        </div>
      </div>
      <span className={`status-label status-label--${state}`}>
        {stateLabel(state)}
      </span>
    </div>
  )
}

const navigationLabels = new Set(
  navigationGroups.flatMap((group) => group.items.map((item) => item.label)),
)

function App() {
  const [path, setPath] = useState(() => window.location.pathname)
  useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname)
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])
  const navigate = useCallback((next: string) => {
    if (window.location.pathname !== next) window.history.pushState({}, '', next)
    setPath(window.location.pathname)
    window.scrollTo(0, 0)
  }, [])
  const auth = useAuth()
  const signedIn = auth.status === 'signed-in'
  if (path === '/audit') return <PublicLanding onNavigate={navigate} signedIn={signedIn} />
  if (path === '/' && auth.status === 'initializing') {
    return <div className="app-loading" role="status">Loading…</div>
  }
  if (path === '/' && !signedIn) return <PublicLanding onNavigate={navigate} signedIn={false} />
  if (path === '/login' || path === '/auth/verify' || path === '/auth/reset') return <LoginPage onNavigate={navigate} />
  if (path === '/invitations') return <InvitationsPage onNavigate={navigate} />
  return <Dashboard onNavigate={navigate} />
}

function Dashboard({ onNavigate }: { onNavigate: (path: string) => void }) {
  const auth = useAuth()
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    try {
      return window.localStorage.getItem('reckon.theme') === 'dark' ? 'dark' : 'light'
    } catch {
      return 'light'
    }
  })
  useEffect(() => {
    try {
      window.localStorage.setItem('reckon.theme', theme)
    } catch {
      // preference storage is optional
    }
  }, [theme])
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])
  const [health, setHealth] = useState<PlatformHealth>(initialHealth)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [platformAdmin, setPlatformAdmin] = useState(false)
  const [activeNavigation, setActiveNavigation] = useState(() => {
    // Keep the open page across a refresh; only known page labels are accepted.
    try {
      const saved = window.sessionStorage.getItem('reckon.nav')
      return saved && navigationLabels.has(saved) ? saved : 'Overview'
    } catch {
      return 'Overview'
    }
  })
  useEffect(() => {
    try {
      window.sessionStorage.setItem('reckon.nav', activeNavigation)
    } catch {
      // navigation persistence is optional
    }
  }, [activeNavigation])
  const [workspaceState, setWorkspaceState] = useState<{
    subject: string
    context: OrganizationContext
  } | null>(null)
  const requestId = useRef(0)
  const subject = auth.user
    ? JSON.stringify([auth.user.profile.iss ?? '', auth.user.profile.sub, auth.sessionId])
    : ''
  const workspace =
    subject && workspaceState?.subject === subject
      ? workspaceState.context
      : null
  const handleWorkspaceConnected = useCallback(
    (context: OrganizationContext) => {
      if (subject) {
        setWorkspaceState({ subject, context })
      }
    },
    [subject],
  )

  // WorkspaceSetup only renders on Overview, so restore the saved organization here too;
  // otherwise a refresh on any other page loses the workspace.
  const accessToken = auth.status === 'signed-in' ? auth.user?.access_token : undefined
  useEffect(() => {
    if (!accessToken || !subject || workspace || activeNavigation === 'Overview') {
      return
    }
    let active = true
    void restoreSavedOrganization(accessToken, window.sessionStorage).then((context) => {
      if (active && context) handleWorkspaceConnected(context)
    })
    return () => { active = false }
  }, [accessToken, subject, workspace, activeNavigation, handleWorkspaceConnected])

  const refreshHealth = useCallback(async (showSpinner = false) => {
    const currentRequest = ++requestId.current
    if (showSpinner) {
      setRefreshing(true)
    }

    const nextHealth = await checkPlatformHealth()
    if (requestId.current !== currentRequest) {
      return
    }

    setHealth(nextHealth)
    setCheckedAt(new Date())
    setRefreshing(false)
  }, [])

  useEffect(() => {
    const initialCheckId = window.setTimeout(() => void refreshHealth(), 0)
    const intervalId = window.setInterval(() => void refreshHealth(), 30_000)

    return () => {
      requestId.current += 1
      window.clearTimeout(initialCheckId)
      window.clearInterval(intervalId)
    }
  }, [refreshHealth])

  useEffect(() => {
    if (auth.status !== 'signed-in' || !auth.user?.access_token) {
      return
    }
    let active = true
    void fetch('/api/v1/platform/access', {
      headers: { Authorization: `Bearer ${auth.user.access_token}` },
      cache: 'no-store',
    }).then(async (response) => {
      if (!response.ok) throw new Error('Platform access unavailable.')
      const value: unknown = await response.json()
      if (active && value && typeof value === 'object' && 'is_platform_admin' in value) {
        setPlatformAdmin(value.is_platform_admin === true)
      }
    }).catch(() => {
      if (active) setPlatformAdmin(false)
    })
    return () => { active = false }
  }, [auth.status, auth.user?.access_token])

  const toggleTheme = () => {
    setTheme((currentTheme) => (currentTheme === 'light' ? 'dark' : 'light'))
  }

  const handleWebsiteNavigation = () => {
    setActiveNavigation('Websites')
    const target =
      document.getElementById('website-onboarding') ??
      document.getElementById('workspace-card')
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const handleOverviewNavigation = () => {
    setActiveNavigation('Overview')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleSettingsNavigation = () => {
    setActiveNavigation('System settings')
    document.getElementById('ai-settings')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const handleAccountSecurityNavigation = () => {
    setActiveNavigation('Account security')
    document.getElementById('account-security')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const handleWorkflowAction = () => {
    if (auth.status !== 'signed-in') {
      onNavigate('/login')
      return
    }
    const target = workspace
      ? document.getElementById('website-onboarding')
      : document.getElementById('workspace-card')
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const workflowActionLabel =
    auth.status === 'initializing'
      ? 'Checking access…'
      : auth.status === 'signed-in'
        ? workspace
          ? 'Open website workspace'
          : 'Connect a workspace'
        : 'Sign in to continue'

  return (
    <div className="app-shell" data-theme={theme}>
      <aside className={`sidebar${menuOpen ? ' sidebar--open' : ''}`} id="app-sidebar">
        <a aria-label="Reckon SEO Autopilot home" className="brand" href="/">
          <span className="brand__mark">
            <Icon name="spark" />
          </span>
          <span className="brand__text">
            <strong>reckon</strong>
            <span>SEO AUTOPILOT</span>
          </span>
        </a>

        <div
          className="workspace-picker"
          aria-label={workspace ? 'Workspace connected' : 'Workspace not connected'}
        >
          <span className="workspace-picker__icon">
            <Icon name="users" />
          </span>
          <span className="workspace-picker__copy">
            <span>WORKSPACE</span>
            <strong>
              {workspace
                ? `${workspace.role} access`
                : auth.status === 'signed-in'
                  ? 'Setup required'
                  : 'Not connected'}
            </strong>
          </span>
          <Icon className="workspace-picker__chevron" name="chevron" />
        </div>

        <nav aria-label="Main navigation" className="sidebar-nav">
          {navigationGroups.map((group) => (
            platformAdmin || group.label !== 'Platform'
              ? (
            <div className="nav-group" key={group.label}>
              <p className="nav-group__label">{group.label}</p>
              {group.items.map((item) => (
                <button
                  aria-current={
                    activeNavigation === item.label
                      ? item.label === 'Overview'
                        ? 'page'
                        : 'location'
                      : undefined
                  }
                  aria-disabled={!item.available || (item.label === 'Platform operations' && !platformAdmin)}
                  className={`nav-item${activeNavigation === item.label ? ' nav-item--active' : ''}`}
                  disabled={!item.available || (item.label === 'Platform operations' && !platformAdmin)}
                  key={item.label}
                  title={
                    item.available
                      ? undefined
                      : `${item.label} is not available in this build`
                  }
                  onClick={() => {
                    setMenuOpen(false)
                    if (item.label === 'Websites') handleWebsiteNavigation()
                    else if (item.label === 'Overview') handleOverviewNavigation()
                    else if (item.label === 'System settings') handleSettingsNavigation()
                    else if (item.label === 'Account security') handleAccountSecurityNavigation()
                    else {
                      setActiveNavigation(item.label)
                      window.scrollTo({ top: 0, behavior: 'smooth' })
                    }
                  }}
                  type="button"
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                  {!item.available && (
                    <span className="nav-item__soon">Planned</span>
                  )}
                </button>
              ))}
            </div>
              )
              : null
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-status">
            <span
              className={`status-dot status-dot--${health.api.state}`}
              aria-hidden="true"
            />
            <span>API {stateLabel(health.api.state).toLowerCase()}</span>
          </div>
          <a className="sidebar-link" href="/docs" rel="noreferrer" target="_blank">
            <Icon name="book" />
            <span>API reference</span>
            <Icon className="sidebar-link__arrow" name="arrow" />
          </a>
          <p className="sidebar-version">Reckon SEO Autopilot · Local</p>
        </div>
      </aside>

      {menuOpen && <div className="sidebar-scrim" aria-hidden="true" onClick={() => setMenuOpen(false)} />}
      <div className="main-panel">
        <header className="topbar">
          <button aria-controls="app-sidebar" aria-expanded={menuOpen} aria-label="Open navigation menu"
            className="icon-button topbar__menu" onClick={() => setMenuOpen((open) => !open)} type="button">
            <Icon name="menu" />
          </button>
          <div className="breadcrumbs">
            <span>{navigationGroups.find((group) => group.items.some((item) => item.label === activeNavigation))?.label ?? 'Workspace'}</span>
            <Icon name="chevron" />
            <strong>{activeNavigation}</strong>
          </div>
          <div className="topbar__actions">
            <span className="environment-pill">
              <span className="environment-pill__dot" />
              Local preview
            </span>
            {auth.user && (
              <button
                className="button button--secondary topbar__sign-out"
                onClick={() => void auth.signOut()}
                type="button"
              >
                Sign out
              </button>
            )}
            {!auth.user && (
              <a className="button button--primary" href="/login"
                onClick={(event) => { event.preventDefault(); onNavigate('/login') }}>
                Sign in
              </a>
            )}
            <button
              aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
              className="icon-button"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
              type="button"
            >
              <Icon name={theme === 'light' ? 'moon' : 'sun'} />
            </button>
          </div>
        </header>

        <main className="page-content">
          {activeNavigation !== 'Overview' ? (
            activeNavigation === 'Quick audit' ? (
              <section aria-labelledby="quick-audit-title" className="quick-audit">
                <p className="section-kicker">QUICK AUDIT</p>
                <h1 id="quick-audit-title">Audit any public website</h1>
                <p className="quick-audit__lead">
                  Check technical and on-page SEO for any site, yours or a competitor&apos;s. Results are
                  not saved; add a site under Websites for monitoring and fixes.
                </p>
                <PublicAuditTool compact />
              </section>
            ) : activeNavigation === 'Platform operations' && platformAdmin ? (
              <PlatformOperations accessToken={auth.user?.access_token ?? ''} />
            ) : (
            <WorkspacePages
              page={activeNavigation}
              accessToken={auth.status === 'signed-in' ? auth.user?.access_token ?? '' : ''}
              organization={workspace}
            />
            )
          ) : (
          <>
          <section aria-labelledby="page-title" className="page-intro">
            <div>
              <p className="eyebrow">
                <span className="eyebrow__line" />
                YOUR SEO OPERATIONS WORKSPACE
              </p>
              <h1 id="page-title">Your SEO operations, <span>in one place.</span></h1>
              <p className="page-intro__description">
                Connect your workspace, verify your website, and turn reliable
                crawl evidence into a clear picture of what needs attention.
              </p>
            </div>
            <a className="button button--primary" href="/docs" rel="noreferrer" target="_blank">
              <span>Explore API</span>
              <Icon name="arrow" />
            </a>
          </section>

          <OperationsOverview
            authStatus={auth.status}
            configKind={auth.config.kind}
            workspaceConnected={workspace !== null}
            health={health}
            actionLabel={workflowActionLabel}
            actionDisabled={auth.status === 'initializing'}
            onAction={handleWorkflowAction}
          />

          <CrawlWorkflow
            accountConnected={auth.status === 'signed-in'}
            workspaceConnected={workspace !== null}
            actionLabel={workflowActionLabel}
            actionDisabled={auth.status === 'initializing'}
            onAction={handleWorkflowAction}
          />

          <section aria-labelledby="health-title" className="health-card">
            <div className="section-heading">
              <div>
                <p className="section-kicker">SYSTEM STATUS</p>
                <h2 id="health-title">Platform health</h2>
              </div>
              <button
                className="button button--secondary"
                disabled={refreshing}
                onClick={() => void refreshHealth(true)}
                type="button"
              >
                <Icon className={refreshing ? 'icon-spin' : ''} name="activity" />
                <span>{refreshing ? 'Checking…' : 'Refresh status'}</span>
              </button>
            </div>

            <div aria-live="polite" className="health-list">
              <HealthRow
                label="API process"
                message={health.api.message}
                state={health.api.state}
              />
              <HealthRow
                label="Database"
                message={health.database.message}
                state={health.database.state}
              />
            </div>
            <div className="health-card__footer">
              <span>
                {checkedAt
                  ? `Last checked at ${checkedAt.toLocaleTimeString([], {
                      hour: 'numeric',
                      minute: '2-digit',
                    })}`
                  : 'Waiting for first status check'}
              </span>
              <a href="/docs" rel="noreferrer" target="_blank">
                View API documentation <Icon name="arrow" />
              </a>
            </div>
          </section>

          <AIModelSettings
            accessToken={auth.status === 'signed-in' ? auth.user?.access_token ?? '' : ''}
            key={workspace?.organization_id ?? 'no-workspace'}
            organization={workspace}
          />
          {auth.status === 'signed-in' && auth.user?.access_token &&
            (auth.user.profile.iss === 'reckon-native') && (
              <AccountSecurity accessToken={auth.user.access_token} />
            )}

          <section
            aria-labelledby="workspace-title"
            className={`workspace-card${workspace ? ' workspace-card--connected' : ''}`}
            id="workspace-card"
          >
            <div className="workspace-card__art" aria-hidden="true">
              <div className="orbit orbit--outer" />
              <div className="orbit orbit--inner" />
              <div className="orbit-core">
                <Icon name="spark" />
              </div>
              <span className="orbit-node orbit-node--one" />
              <span className="orbit-node orbit-node--two" />
              <span className="orbit-node orbit-node--three" />
            </div>
            <div className="workspace-card__content">
              {auth.status === 'initializing' && (
                <>
                  <span className="status-label status-label--muted">Account access</span>
                  <h2 id="workspace-title">Checking your sign-in</h2>
                  <p>Validating the current browser session.</p>
                </>
              )}
              {auth.status !== 'signed-in' && auth.status !== 'initializing' && (
                <>
                  <span className="status-label status-label--muted">Account access</span>
                  <h2 id="workspace-title">Sign in to connect a workspace</h2>
                  {auth.error && <p className="workspace-setup__error" role="alert">{auth.error}</p>}
                </>
              )}
              {auth.status !== 'signed-in' && auth.status !== 'initializing' && (
                <a className="button button--primary" href="/login"
                  onClick={(event) => { event.preventDefault(); onNavigate('/login') }}>
                  Open sign-in
                </a>
              )}
              {auth.status === 'signed-in' && auth.user?.access_token && (
                <>
                  <span className="status-label status-label--healthy">
                    Authenticated session
                  </span>
                  <h2 id="workspace-title">
                    {workspace ? 'Your workspace is connected' : 'Connect a workspace'}
                  </h2>
                  <p>
                    Organization access is checked by the API on every connection
                    and restored from this tab only after membership is verified.
                    Website onboarding and SEO evidence are separate next steps.
                  </p>
                  <PlatformAccess key={auth.sessionId} accessToken={auth.user.access_token} />
                  <a className="text-link" href="/invitations"
                    onClick={(event) => { event.preventDefault(); onNavigate('/invitations') }}>
                    My invitations
                  </a>
                  {auth.error && (
                    <p aria-live="polite" className="workspace-setup__error" role="alert">
                      {auth.error}
                    </p>
                  )}
                  <WorkspaceSetup
                    accessToken={auth.user.access_token}
                    current={workspace ?? undefined}
                    key={subject}
                    onConnected={handleWorkspaceConnected}
                  />
                  {workspace && (workspace.role === 'owner' || workspace.role === 'admin') && (
                    <OrganizationMembers
                      key={`members-${workspace.organization_id}`}
                      accessToken={auth.user.access_token}
                      organization={workspace}
                    />
                  )}
                  {workspace && (
                    <WebsiteOnboarding
                      accessToken={auth.user.access_token}
                      key={`websites-${workspace.organization_id}`}
                      organization={workspace}
                    />
                  )}
                </>
              )}
              <a className="text-link" href="/docs" rel="noreferrer" target="_blank">
                Review the available API <Icon name="arrow" />
              </a>
            </div>
          </section>

          <section aria-labelledby="capabilities-title" className="capabilities">
            <div className="section-heading section-heading--compact">
              <div>
                <p className="section-kicker">PRODUCT CAPABILITIES</p>
                <h2 id="capabilities-title">Implemented and planned</h2>
              </div>
              <span className="section-note">Current implementation status</span>
            </div>
            <div className="capability-grid">
              <CapabilityCard
                icon="globe"
                number="01"
                title="Verified website crawls"
                description="Register and DNS-verify authorized sites, then run bounded homepage crawls and review retained evidence."
                status="Implemented"
              />
              <CapabilityCard
                icon="audit"
                number="02"
                title="Deterministic homepage audits"
                description="Evidence-backed findings cover supported page and sitemap checks without fabricated scores."
                status="Implemented"
              />
              <CapabilityCard
                icon="check"
                number="03"
                title="Governed recommendations"
                description="Approval-governed external change workflows are still planned."
                status="Planned"
              />
            </div>
          </section>

          <footer className="page-footer">
            <span>Reckon SEO Autopilot</span>
            <span>Built around evidence, authorization, and verification.</span>
          </footer>
          </>
          )}
        </main>
      </div>
    </div>
  )
}

function CapabilityCard({
  icon,
  number,
  title,
  description,
  status,
}: {
  icon: IconName
  number: string
  title: string
  description: string
  status: 'Implemented' | 'Planned'
}) {
  return (
    <article className="capability-card">
      <div className="capability-card__top">
        <span className="capability-card__icon">
          <Icon name={icon} />
        </span>
        <span className="capability-card__number">{number}</span>
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      <span className="capability-card__status">
        <span
          className={`status-dot ${status === 'Implemented' ? 'status-dot--healthy' : 'status-dot--checking'}`}
          aria-hidden="true"
        />
        {status}
      </span>
    </article>
  )
}

export default App
