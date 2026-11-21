import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OrganizationMembers } from './OrganizationMembers'

describe('organization management controls', () => {
  it('lets admins propose only editor and viewer roles', () => {
    const html = renderToStaticMarkup(
      <OrganizationMembers accessToken="token" organization={{ organization_id: 'org', role: 'admin' }} />,
    )
    expect(html).toContain('Review change')
    expect(html).toContain('Invite member')
    expect(html).toContain('Change member role')
    expect(html).not.toContain('value="owner"')
    expect(html).not.toContain('value="admin"')
  })

  it('offers owners the owner and admin roles', () => {
    const html = renderToStaticMarkup(
      <OrganizationMembers accessToken="token" organization={{ organization_id: 'org', role: 'owner' }} />,
    )
    expect(html).toContain('value="owner"')
    expect(html).toContain('value="admin"')
  })
})
