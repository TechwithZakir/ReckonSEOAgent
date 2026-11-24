import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { EngineSetupPrompt } from './WorkspacePages'

describe('engine setup prompt', () => {
  it('tells a new workspace to add a website and offers the free audit', () => {
    const html = renderToStaticMarkup(<EngineSetupPrompt kind="no-website" onNavigate={vi.fn()} />)
    expect(html).toContain('Add a website to unlock this page')
    expect(html).toContain('Add a website</button>')
    expect(html).toContain('Try the free Quick audit')
    expect(html).not.toContain('required before')
  })

  it('distinguishes unverified sites and missing crawls', () => {
    expect(renderToStaticMarkup(<EngineSetupPrompt kind="pending-website" />)).toContain('Finish verifying')
    expect(renderToStaticMarkup(<EngineSetupPrompt kind="no-crawl" />)).toContain('Run your first crawl')
  })
})
