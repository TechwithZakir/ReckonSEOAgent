import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { OperationsOverview } from './OperationsOverview'

const healthy = {
  api: { state: 'healthy' as const, message: 'API is responding' },
  database: { state: 'healthy' as const, message: 'Database is responding' },
}

describe('operations overview', () => {
  it('shows setup and unavailable evidence without inventing results', () => {
    const html = renderToStaticMarkup(
      <OperationsOverview
        authStatus="unconfigured"
        configKind="missing"
        workspaceConnected={false}
        health={healthy}
        actionLabel="Open sign-in setup"
        actionDisabled={false}
        onAction={vi.fn()}
      />,
    )
    expect(html).toContain('Setup required')
    expect(html).toContain('Not connected')
    expect(html).toContain('Operational')
    expect(html).not.toContain('No findings')
    expect(html).not.toContain('0 websites')
  })

  it('shows connected access and reports unavailable health', () => {
    const html = renderToStaticMarkup(
      <OperationsOverview
        authStatus="signed-in"
        configKind="configured"
        workspaceConnected
        health={{ ...healthy, database: { state: 'unavailable', message: 'Unavailable' } }}
        actionLabel="Open website workspace"
        actionDisabled={false}
        onAction={vi.fn()}
      />,
    )
    expect(html).toContain('Signed in')
    expect(html).toContain('View your websites')
    expect(html).toContain('Needs attention')
    expect(html).toContain('Database: unavailable')
  })

  it('does not present a checking service as operational', () => {
    const html = renderToStaticMarkup(
      <OperationsOverview
        authStatus="initializing"
        configKind="configured"
        workspaceConnected={false}
        health={{ ...healthy, api: { state: 'checking', message: 'Checking' } }}
        actionLabel="Checking access"
        actionDisabled
        onAction={vi.fn()}
      />,
    )
    expect(html).toContain('Checking access')
    expect(html).toContain('Checking')
    expect(html).not.toContain('Operational')
  })
})
