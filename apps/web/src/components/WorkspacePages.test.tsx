import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WorkspacePages } from './WorkspacePages'

describe('mock workspace pages', () => {
  it.each([
    'AI Agent Control',
    'Recommendations',
    'Approvals',
    'Agency Workspace',
    'Ask SEO Copilot',
  ])('renders the %s page without fabricated workspace data', (page) => {
    const html = renderToStaticMarkup(
      <WorkspacePages page={page} accessToken="" organization={null} />,
    )
    expect(html).not.toContain('NaN')
  })

  it('renders the assistant state explicitly as provider-unavailable', () => {
    const html = renderToStaticMarkup(
      <WorkspacePages page="Ask SEO Copilot" accessToken="" organization={null} />,
    )
    expect(html).toContain('Live chat is unavailable')
  })

  it.each([
    'Keywords',
    'Content Studio',
    'LinkPilot',
    'Local SEO',
    'E-Commerce',
    'Enterprise',
    'Media & Query',
    'Emerging / GEO',
  ])('renders the %s engine page without fabricated live data', (page) => {
    const html = renderToStaticMarkup(
      <WorkspacePages page={page} accessToken="" organization={null} />,
    )
    expect(html).toContain('Connect a workspace')
  })
})
