import { describe, expect, it } from 'vitest'
import { checkPlatformHealth } from './service-health'

describe('checkPlatformHealth', () => {
  it('reports the API and database as healthy for successful health responses', async () => {
    const fetcher: typeof fetch = async () =>
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })

    await expect(checkPlatformHealth(fetcher)).resolves.toEqual({
      api: {
        state: 'healthy',
        message: 'The API process is responding.',
      },
      database: {
        state: 'healthy',
        message: 'The API can reach its database.',
      },
    })
  })

  it('keeps API liveness healthy when database readiness returns 503', async () => {
    const fetcher: typeof fetch = async (input) => {
      const path = String(input)
      if (path === '/health/ready') {
        return new Response(
          JSON.stringify({ detail: 'Database is unavailable.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }

    await expect(checkPlatformHealth(fetcher)).resolves.toEqual({
      api: {
        state: 'healthy',
        message: 'The API process is responding.',
      },
      database: {
        state: 'unavailable',
        message: 'The API reports that its database is unavailable.',
      },
    })
  })

  it('reports unavailable when the API cannot be reached', async () => {
    const fetcher: typeof fetch = async () => {
      throw new TypeError('Network error')
    }

    await expect(checkPlatformHealth(fetcher)).resolves.toEqual({
      api: {
        state: 'unavailable',
        message: 'Unable to reach the API process.',
      },
      database: {
        state: 'unavailable',
        message: 'Unable to check database readiness.',
      },
    })
  })
})
