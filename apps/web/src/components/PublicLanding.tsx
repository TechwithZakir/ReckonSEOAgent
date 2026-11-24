import { PublicAuditTool } from './PublicAuditTool'
import './PublicLanding.css'

const CHECKS = [
  { title: 'Crawlability', text: 'HTTP status, noindex directives, canonical tags and robots.txt rules.' },
  { title: 'On-page basics', text: 'Titles, meta descriptions and heading structure, with length guidance.' },
  { title: 'Content structure', text: 'Subheadings and internal links that help engines understand your pages.' },
  { title: 'Images', text: 'Missing alt text that hurts accessibility and image search.' },
  { title: 'Sitemaps', text: 'Whether your sitemap exists, is readable and lists your key pages.' },
  { title: 'Linked pages', text: 'Errors and missing basics on pages linked from your homepage.' },
]

const STEPS = [
  { n: '1', title: 'Enter your website', text: 'No account or card. Just your domain.' },
  { n: '2', title: 'We check it safely', text: 'A bounded, read-only crawl that obeys robots.txt.' },
  { n: '3', title: 'Get a clear plan', text: 'Every issue explains what we saw, why it matters and how to fix it.' },
]

export function PublicLanding({ onNavigate, signedIn }: {
  onNavigate: (path: string) => void
  signedIn: boolean
}) {
  const go = (path: string) => (event: { preventDefault: () => void }) => {
    event.preventDefault()
    onNavigate(path)
  }
  return (
    <div className="pl">
      <a className="pl-skip" href="#audit">Skip to the audit</a>
      <header className="pl-header">
        <a className="pl-brand" href="/" onClick={go('/')}>
          reckon <span>SEO AUTOPILOT</span>
        </a>
        <nav aria-label="Primary" className="pl-nav">
          <a href="#how">How it works</a>
          <a href="#checks">What we check</a>
          <a className="pl-link-strong" href={signedIn ? '/' : '/login'} onClick={go(signedIn ? '/' : '/login')}>
            {signedIn ? 'Open dashboard' : 'Sign in'}
          </a>
        </nav>
      </header>

      <main>
        <section className="pl-hero" id="audit" aria-labelledby="pl-title">
          <p className="pl-eyebrow">FREE SEO AUDIT</p>
          <h1 id="pl-title">Find what is holding your site back in search</h1>
          <p className="pl-lead">
            Get an evidence-based audit of your website&apos;s technical and on-page SEO in seconds,
            with clear, prioritized fixes.
          </p>
          <PublicAuditTool onSignUp={() => onNavigate('/login')} />
        </section>

        <section className="pl-section" id="how" aria-labelledby="how-title">
          <h2 id="how-title">How it works</h2>
          <ol className="pl-steps">
            {STEPS.map((step) => (
              <li key={step.n}>
                <span className="pl-step-n" aria-hidden="true">{step.n}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="pl-section pl-section--tint" id="checks" aria-labelledby="checks-title">
          <h2 id="checks-title">What the audit checks</h2>
          <div className="pl-grid">
            {CHECKS.map((check) => (
              <article key={check.title}>
                <h3>{check.title}</h3>
                <p>{check.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="pl-section pl-final" aria-labelledby="final-title">
          <h2 id="final-title">Ready to fix it, not just find it?</h2>
          <p>
            Reckon SEO Autopilot proposes fixes, waits for your approval, applies them to your
            CMS and verifies each change with a re-crawl.
          </p>
          <a className="pl-cta" href={signedIn ? '/' : '/login'} onClick={go(signedIn ? '/' : '/login')}>
            {signedIn ? 'Open dashboard' : 'Create your free account'}
          </a>
        </section>
      </main>

      <footer className="pl-footer">
        <span>© 2026 Reckon Technologies Ltd.</span>
        <span>We only read public pages and honour robots.txt. Audit results are not stored.</span>
      </footer>
    </div>
  )
}
