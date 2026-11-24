import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AdvancedAudit } from './AdvancedAudit'
import type { OrganizationContext } from '../lib/organizations'

const organization = {
  organization_id: '11111111-2222-4333-8444-555555555555',
  name: 'Acme',
  role: 'viewer',
} as unknown as OrganizationContext

describe('advanced audit panel', () => {
  it('describes the checks and the approval-gated AI fixes', () => {
    const html = renderToStaticMarkup(<AdvancedAudit accessToken="t" organization={organization} />)
    expect(html).toContain('Advanced SEO audit')
    expect(html).toContain('AI-search readiness')
    expect(html).toContain('only after you approve')
  })
})
