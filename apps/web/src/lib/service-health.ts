export type ServiceState = 'checking' | 'healthy' | 'unavailable'

export type ServiceHealth = {
  state: ServiceState
  message: string
}

export type PlatformHealth = {
  api: ServiceHealth
  database: ServiceHealth
}

type HealthResponse = {
  status?: unknown
}

async function checkEndpoint(
  path: '/health/live' | '/health/ready',
  fetcher: typeof fetch,
): Promise<ServiceHealth> {
  try {
    const response = await fetcher(path, {
      cache: 'no-store',
      signal: AbortSignal.timeout(5_000),
    })

    if (!response.ok) {
      return {
        state: 'unavailable',
        message:
          path === '/health/ready' && response.status === 503
            ? 'The API reports that its database is unavailable.'
            : `The endpoint returned HTTP ${response.status}.`,
      }
    }

    const body: HealthResponse = await response.json()
    if (body.status !== 'ok') {
      return {
        state: 'unavailable',
        message: 'The endpoint returned an unexpected health response.',
      }
    }

    return {
      state: 'healthy',
      message:
        path === '/health/live'
          ? 'The API process is responding.'
          : 'The API can reach its database.',
    }
  } catch {
    return {
      state: 'unavailable',
      message:
        path === '/health/live'
          ? 'Unable to reach the API process.'
          : 'Unable to check database readiness.',
    }
  }
}

export async function checkPlatformHealth(
  fetcher: typeof fetch = fetch,
): Promise<PlatformHealth> {
  const [api, database] = await Promise.all([
    checkEndpoint('/health/live', fetcher),
    checkEndpoint('/health/ready', fetcher),
  ])
  return { api, database }
}
