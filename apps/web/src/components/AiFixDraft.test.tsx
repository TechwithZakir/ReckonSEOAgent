import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { AiFixDraft } from './AiFixDraft'
import type { OrganizationContext } from '../lib/organizations'

const organization = {
  organization_id: '11111111-2222-4333-8444-555555555555',
  name: 'Acme',
  role: 'owner',
} as unknown as OrganizationContext

describe('AI fix drafting panel', () => {
  it('explains the approval-gated flow before any website is loaded', () => {
    const html = renderToStaticMarkup(
      <AiFixDraft accessToken="token" organization={organization} onDrafted={vi.fn()} />,
    )
    expect(html).toContain('Draft a fix with AI')
    expect(html).toContain('Nothing changes on your site until you approve it')
    expect(html).toContain('Verify a website first')
    expect(html).not.toContain('Draft with AI</button>')
  })
})
