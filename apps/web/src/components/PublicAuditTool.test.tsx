import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { AuditReport, PublicAuditTool } from './PublicAuditTool'
import { PublicLanding } from './PublicLanding'
import type { PublicAuditReport } from '../lib/public-audit'

const report: PublicAuditReport = {
  host: 'example.com',
  final_url: 'https://example.com/',
  score: 72,
  grade: 'C',
  pages_checked: 3,
  audit_version: 'public-homepage-v4',
  cached: false,
  notice: 'example.com redirects to www.example.com, so we audited www.example.com.',
  checks: [
    { category: 'On-page', label: 'Title tag present', passed: true },
    { category: 'On-page', label: 'Meta description present', passed: false },
  ],
  findings: [
    {
      id: 'missing_meta_description', category: 'On-page', severity: 'low',
      title: 'No meta description', found: 'None found.',
      why_it_matters: 'Snippets get auto-generated.', how_to_fix: 'Write one.',
      url: 'https://example.com/', autopilot: 'propose',
    },
  ],
}

describe('public audit UI', () => {
  it('renders the score, checks and fix guidance', () => {
    const html = renderToStaticMarkup(<AuditReport report={report} onSignUp={vi.fn()} />)
    expect(html).toContain('example.com')
    expect(html).toContain('Audit score 72 out of 100, grade C')
    expect(html).toContain('How to fix it')
    expect(html).toContain('Autopilot can propose this fix')
    expect(html).toContain('1 of 1')
    expect(html).toContain('redirects to www.example.com')
    expect(html).toContain('Failed: </span>Meta description present')
    expect(html).toContain('Passed: </span>Title tag present')
    expect(html).toContain('not a ranking prediction')
    expect(html).toContain('Create your account')
  })

  it('shows a positive empty state when nothing is found', () => {
    const html = renderToStaticMarkup(
      <AuditReport report={{ ...report, score: 100, grade: 'A', findings: [], checks: [] }} />,
    )
    expect(html).toContain('No issues found')
    expect(html).not.toContain('Create your account')
  })

  it('offers a labelled address field without needing an account', () => {
    const html = renderToStaticMarkup(<PublicAuditTool />)
    expect(html).toContain('Website address')
    expect(html).toContain('Get free audit')
    expect(html).toContain('no sign-up')
  })

  it('landing page links to sign-in for visitors and the dashboard when signed in', () => {
    const visitor = renderToStaticMarkup(<PublicLanding onNavigate={vi.fn()} signedIn={false} />)
    expect(visitor).toContain('AI agent that finds and fixes')
    expect(visitor).toContain('href="/login"')
    const member = renderToStaticMarkup(<PublicLanding onNavigate={vi.fn()} signedIn />)
    expect(member).toContain('Open dashboard')
    expect(member).not.toContain('Create your free account')
  })
})
