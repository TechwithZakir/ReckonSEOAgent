import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AccountSecurity } from './AccountSecurity'
import { PlatformOperations } from './PlatformOperations'
import { SeoActionInbox } from './SeoActionInbox'

const organization = {
  organization_id: '11111111-1111-4111-8111-111111111111',
  role: 'owner' as const,
}

describe('operations panels render without fabricated data', () => {
  it('renders the approval inbox with an empty proposal list and a create form', () => {
    const html = renderToStaticMarkup(
      <SeoActionInbox accessToken="token" organization={organization} />,
    )
    expect(html).toContain('Approval Inbox')
    expect(html).toContain('Create proposal')
    expect(html).not.toContain('Approve</button>')
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('undefined')
  })

  it('renders account security without leaking the access token', () => {
    const html = renderToStaticMarkup(<AccountSecurity accessToken="secret-token" />)
    expect(html).toContain('MFA and sessions')
    expect(html).toContain('Authenticator app')
    expect(html).not.toContain('secret-token')
    expect(html).not.toContain('NaN')
  })

  it('renders platform administration without leaking the access token', () => {
    const html = renderToStaticMarkup(<PlatformOperations accessToken="secret-token" />)
    expect(html).toContain('Platform administration')
    expect(html).not.toContain('secret-token')
    expect(html).not.toContain('NaN')
  })
})
