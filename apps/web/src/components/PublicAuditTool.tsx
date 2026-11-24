import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  groupFindings,
  runPublicAudit,
  scoreTone,
  severityCounts,
} from '../lib/public-audit'
import type { PublicAuditReport, PublicFinding } from '../lib/public-audit'
import './PublicAudit.css'

const SEVERITY_LABEL = { high: 'High', medium: 'Medium', low: 'Low' } as const

function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  return (
    <div className={`pa-ring pa-ring--${scoreTone(score)}`} role="img"
      aria-label={`Audit score ${score} out of 100, grade ${grade}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle className="pa-ring__track" cx="60" cy="60" r={radius} />
        <circle className="pa-ring__value" cx="60" cy="60" r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)} />
      </svg>
      <div className="pa-ring__label">
        <strong>{score}</strong>
        <span>/ 100</span>
      </div>
    </div>
  )
}

function FindingCard({ finding }: { finding: PublicFinding }) {
  return (
    <details className="pa-finding">
      <summary>
        <span className={`pa-badge pa-badge--${finding.severity}`}>
          {SEVERITY_LABEL[finding.severity]}
        </span>
        <span className="pa-finding__title">{finding.title}</span>
      </summary>
      <dl>
        <div><dt>What we found</dt><dd>{finding.found}</dd></div>
        <div><dt>Why it matters</dt><dd>{finding.why_it_matters}</dd></div>
        <div><dt>How to fix it</dt><dd>{finding.how_to_fix}</dd></div>
        <div>
          <dt>Page</dt>
          <dd className="pa-finding__url">{finding.url}</dd>
        </div>
      </dl>
    </details>
  )
}

export function AuditReport({ report, onSignUp }: {
  report: PublicAuditReport
  onSignUp?: () => void
}) {
  const counts = severityCounts(report.findings)
  const groups = [...groupFindings(report.findings).entries()]
  const passed = report.checks.filter((check) => check.passed)
  const failed = report.checks.filter((check) => !check.passed)
  return (
    <section className="pa-report" aria-labelledby="pa-report-title">
      <header className="pa-report__summary">
        <ScoreRing score={report.score} grade={report.grade} />
        <div className="pa-report__headline">
          <p className="pa-kicker">SITE AUDIT RESULT</p>
          <h2 id="pa-report-title">{report.host}</h2>
          <p className="pa-muted">
            {report.pages_checked} page{report.pages_checked === 1 ? '' : 's'} checked
            {report.cached ? ' · recent result' : ''}
          </p>
          <ul className="pa-counts" aria-label="Issues by severity">
            <li className="pa-counts__high"><strong>{counts.high}</strong> High</li>
            <li className="pa-counts__medium"><strong>{counts.medium}</strong> Medium</li>
            <li className="pa-counts__low"><strong>{counts.low}</strong> Low</li>
          </ul>
        </div>
        <button className="pa-button pa-button--ghost pa-print" type="button"
          onClick={() => window.print()}>
          Save as PDF
        </button>
      </header>

      <p className="pa-note">
        The score reflects only the issues this audit found on the pages it checked. It is not a
        ranking prediction. A clean result means these checks passed, not that rankings are guaranteed.
      </p>

      <div className="pa-checks">
        <h3>Checks</h3>
        <ul>
          {failed.map((check) => (
            <li key={check.label} className="pa-check pa-check--fail">
              <span aria-hidden="true">✕</span><span className="pa-sr">Failed: </span>{check.label}
            </li>
          ))}
          {passed.map((check) => (
            <li key={check.label} className="pa-check pa-check--pass">
              <span aria-hidden="true">✓</span><span className="pa-sr">Passed: </span>{check.label}
            </li>
          ))}
        </ul>
      </div>

      {groups.length === 0 ? (
        <div className="pa-empty">
          <h3>No issues found</h3>
          <p>Every check in this audit passed for the pages we looked at. Nice work.</p>
        </div>
      ) : (
        groups.map(([category, items]) => (
          <div className="pa-group" key={category}>
            <h3>{category} <span className="pa-muted">({items.length})</span></h3>
            {items.map((item) => <FindingCard finding={item} key={`${item.id}`} />)}
          </div>
        ))
      )}

      {onSignUp && (
        <aside className="pa-cta">
          <div>
            <h3>Want these fixed for you?</h3>
            <p>Create a free account to monitor this site, get approval-gated fixes, and see
              every change verified by a re-crawl.</p>
          </div>
          <button className="pa-button pa-button--primary" type="button" onClick={onSignUp}>
            Create your account
          </button>
        </aside>
      )}
    </section>
  )
}

export function PublicAuditTool({ onSignUp, compact = false }: {
  onSignUp?: () => void
  compact?: boolean
}) {
  const [value, setValue] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [report, setReport] = useState<PublicAuditReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => {
    if (state === 'done') resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [state])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const target = value.trim()
    if (!target || state === 'loading') {
      if (!target) {
        setError('Enter a website address such as example.com.')
        setState('error')
      }
      return
    }
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setState('loading')
    setError(null)
    try {
      const result = await runPublicAudit(target, fetch, current.signal)
      if (current.signal.aborted) return
      setReport(result)
      setState('done')
    } catch (cause) {
      if (current.signal.aborted) return
      setError(cause instanceof Error ? cause.message : 'The audit failed. Please try again.')
      setState('error')
    }
  }

  return (
    <div className={`pa-tool${compact ? ' pa-tool--compact' : ''}`}>
      <form className="pa-form" onSubmit={(event) => void submit(event)} noValidate>
        <label className="pa-sr" htmlFor="pa-url">Website address</label>
        <input id="pa-url" className="pa-input" type="text" inputMode="url"
          autoComplete="url" autoCapitalize="off" spellCheck={false}
          placeholder="Enter your website, e.g. example.com" value={value}
          aria-invalid={state === 'error'} aria-describedby="pa-status"
          onChange={(event) => setValue(event.target.value)} />
        <button className="pa-button pa-button--primary" type="submit" disabled={state === 'loading'}>
          {state === 'loading' ? 'Auditing…' : 'Get free audit'}
        </button>
      </form>
      <div id="pa-status" aria-live="polite" className="pa-status">
        {state === 'loading' && (
          <p className="pa-loading"><span className="pa-spinner" aria-hidden="true" />
            Checking robots.txt, sitemap and your pages. This usually takes 5–20 seconds.</p>
        )}
        {state === 'error' && error && <p className="pa-error" role="alert">{error}</p>}
        {state === 'idle' && (
          <p className="pa-muted">Free · no sign-up · we respect robots.txt and only read public pages.</p>
        )}
      </div>
      <div ref={resultRef}>
        {state === 'done' && report && <AuditReport report={report} onSignUp={onSignUp} />}
      </div>
    </div>
  )
}
