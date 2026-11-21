import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AIModelSettings } from './AIModelSettings'

describe('AI model settings', () => {
  it('explains setup without claiming an AI provider is connected', () => {
    const html = renderToStaticMarkup(<AIModelSettings accessToken="" organization={null} />)
    expect(html).toContain('AI model')
    expect(html).toContain('OpenAI or Anthropic')
    expect(html).toContain('Sign in and connect an organization')
    expect(html).toContain('Test AI sends a short, metered request')
  })

  it('restricts settings to organization managers', () => {
    const html = renderToStaticMarkup(
      <AIModelSettings accessToken="token" organization={{ organization_id: 'org', role: 'editor' }} />,
    )
    expect(html).toContain('Only organization owners and admins')
    expect(html).not.toContain('Save AI settings')
  })
})
