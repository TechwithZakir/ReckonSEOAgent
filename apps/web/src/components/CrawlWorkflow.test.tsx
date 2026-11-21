import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { CrawlWorkflow } from './CrawlWorkflow'

describe('crawl workflow overview', () => {
  it('explains the prerequisites before an account and workspace are connected', () => {
    const html = renderToStaticMarkup(
      <CrawlWorkflow
        accountConnected={false}
        workspaceConnected={false}
        actionLabel="Sign in to continue"
        actionDisabled={false}
        onAction={vi.fn()}
      />,
    )

    expect(html).toContain('Crawl verified websites')
    expect(html).toContain('Sign-in required')
    expect(html).toContain('After sign-in')
    expect(html).toContain('DNS check required before crawl')
  })

  it('shows connected setup without claiming a crawl has run', () => {
    const html = renderToStaticMarkup(
      <CrawlWorkflow
        accountConnected
        workspaceConnected
        actionLabel="Open website workspace"
        actionDisabled={false}
        onAction={vi.fn()}
      />,
    )

    expect(html).toContain('Signed in')
    expect(html).toContain('Workspace connected')
    expect(html).toContain('DNS check required before crawl')
    expect(html).not.toContain('Crawl completed')
  })
})
