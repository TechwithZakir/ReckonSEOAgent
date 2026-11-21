import { describe, expect, it, vi } from 'vitest'
import { deleteAISettings, getAISettings, saveAISettings, testAISettings } from './ai-settings'

describe('AI settings API', () => {
  it('saves the selected provider without exposing the key in the response', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      configured: true, provider: 'openai', model: 'test-model', endpoint_url: 'https://proxy.example.com/v1', encryption_available: true,
    }), { status: 200 }))
    const result = await saveAISettings('session-token', 'org-id', 'openai', 'test-model', 'fake-key', 'https://proxy.example.com/v1', fetcher)
    expect(result.model).toBe('test-model')
    expect(JSON.stringify(result)).not.toContain('fake-key')
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/organizations/org-id/ai-settings',
      expect.objectContaining({
        method: 'PUT',
        cache: 'no-store',
        body: JSON.stringify({ provider: 'openai', model: 'test-model', api_key: 'fake-key', endpoint_url: 'https://proxy.example.com/v1' }),
      }),
    )
  })

  it('rejects responses containing unexpected credential fields', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      configured: true, provider: 'anthropic', model: 'test', endpoint_url: 'https://api.anthropic.com/v1', encryption_available: true,
      api_key: 'fake-key',
    }), { status: 200 }))
    await expect(getAISettings('token', 'org', fetcher)).rejects.toThrow('invalid AI settings')
  })

  it('reports server failures without reflecting their response body', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('fake-key', { status: 422 }))
    await expect(saveAISettings('token', 'org', 'anthropic', 'test', 'fake-key', 'https://api.anthropic.com/v1', fetcher))
      .rejects.toThrow('Check the provider')
    const remove = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }))
    await expect(deleteAISettings('token', 'org', remove)).resolves.toBeUndefined()
  })

  it('rejects a configured response without an endpoint', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      configured: true, provider: 'openai', model: 'test', endpoint_url: null, encryption_available: true,
    })))
    await expect(getAISettings('token', 'org', fetcher)).rejects.toThrow('invalid AI settings')
  })

  it('tests saved settings and rejects unverified responses without exposing server errors', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response(JSON.stringify({
      verified: true, provider: 'openai', model: 'test', input_tokens: 10, output_tokens: 2,
    }))).mockResolvedValueOnce(new Response('secret provider error', { status: 502 }))
    await expect(testAISettings('token', 'org', 'test-key-1', fetcher)).resolves.toEqual({
      provider: 'openai', model: 'test', input_tokens: 10, output_tokens: 2,
    })
    expect(fetcher).toHaveBeenCalledWith('/api/v1/organizations/org/ai-settings/test', expect.objectContaining({
      method: 'POST', headers: { Authorization: 'Bearer token', 'Idempotency-Key': 'test-key-1' },
    }))
    await expect(testAISettings('token', 'org', 'test-key-2', fetcher)).rejects.toThrow('could not be verified')
  })
})
