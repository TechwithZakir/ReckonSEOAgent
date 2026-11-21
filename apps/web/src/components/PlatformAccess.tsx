import { useEffect, useState } from 'react'

export function PlatformAccess({ accessToken }: { accessToken: string }) {
  const [state, setState] = useState<'loading' | 'admin' | 'user' | 'error'>('loading')
  useEffect(() => {
    let active = true
    void fetch('/api/v1/platform/access', {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    }).then(async (response) => {
      if (!response.ok) throw new Error('Platform access could not be verified.')
      const value: unknown = await response.json()
      if (!value || typeof value !== 'object' ||
          !('is_platform_admin' in value) || typeof value.is_platform_admin !== 'boolean') {
        throw new Error('Platform access could not be verified.')
      }
      if (active) setState(value.is_platform_admin ? 'admin' : 'user')
    }).catch(() => { if (active) setState('error') })
    return () => { active = false }
  }, [accessToken])

  if (state === 'admin') return <p>Platform administrator · Organization membership is still required.</p>
  if (state === 'error') return <p className="workspace-setup__error" role="alert">Platform access could not be verified.</p>
  return null
}
