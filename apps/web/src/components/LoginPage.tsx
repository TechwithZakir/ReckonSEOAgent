import { useAuth } from '../auth/AuthContext'
import { NativeAuth } from './NativeAuth'

export function LoginPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  const auth = useAuth()
  const returnPath = new URLSearchParams(window.location.search).get('next') === '/invitations'
    ? '/invitations' : '/'
  return (
    <div className="app-shell login-page">
      <header className="login-page__header">
        <a className="login-page__brand" href="/" onClick={(event) => { event.preventDefault(); onNavigate('/') }}>
          reckon <span>SEO AUTOPILOT</span>
        </a>
        <a href="/" onClick={(event) => { event.preventDefault(); onNavigate('/') }}>Back to overview</a>
      </header>
      <main className="login-page__main">
        <div className="login-page__intro">
          <span className="login-page__eyebrow">YOUR SEO OPERATIONS WORKSPACE</span>
          <h1>Welcome to Reckon</h1>
          <p>Sign in to manage your organizations and work with verified SEO evidence.</p>
        </div>
        <section className="login-card workspace-card__content" aria-labelledby="login-title">
          <span className="status-label status-label--muted">ACCOUNT ACCESS</span>
          <h2 id="login-title">Sign in to your account</h2>
          {auth.error && <p className="workspace-setup__error" role="alert">{auth.error}</p>}
          {auth.status === 'signed-in' ? (
            <button className="button button--primary" type="button" onClick={() => onNavigate(returnPath)}>
              Open your workspace
            </button>
          ) : (
            <>
              <NativeAuth onSignedIn={() => onNavigate(returnPath)} />
              {auth.config.kind === 'configured' && (
                <button className="button button--secondary" type="button"
                  disabled={auth.status === 'initializing'} onClick={() => void auth.signIn()}>
                  Sign in with identity provider
                </button>
              )}
              {auth.config.kind === 'invalid' && <p role="alert">{auth.config.message}</p>}
            </>
          )}
        </section>
      </main>
    </div>
  )
}
