import { describe, expect, it } from 'vitest'
import {
  clearNativeSession,
  loadNativeSession,
  saveNativeSession,
} from './native-session-store'

function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() { return data.size },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => { data.delete(key) },
    setItem: (key, value) => { data.set(key, value) },
  }
}

const session = {
  access_token: 'rk1_' + 'A'.repeat(43),
  user_id: '11111111-1111-4111-8111-111111111111',
  expires_in: 3600,
}

describe('native session store', () => {
  it('restores a session after refresh with the remaining lifetime', () => {
    const storage = memoryStorage()
    saveNativeSession(storage, session, 1_000_000)
    const restored = loadNativeSession(storage, 1_000_000 + 600_000)
    expect(restored).toEqual({ ...session, expires_in: 3000 })
  })

  it('drops and clears an expired session', () => {
    const storage = memoryStorage()
    saveNativeSession(storage, session, 0)
    expect(loadNativeSession(storage, 3_600_001)).toBeNull()
    expect(storage.length).toBe(0)
  })

  it('rejects tampered or malformed entries', () => {
    const storage = memoryStorage()
    storage.setItem('reckon.native.session', JSON.stringify({ access_token: 'x', user_id: 'y', expires_at: 9e15 }))
    expect(loadNativeSession(storage)).toBeNull()
    storage.setItem('reckon.native.session', '{not json')
    expect(loadNativeSession(storage)).toBeNull()
    expect(storage.length).toBe(0)
  })

  it('clears on sign-out', () => {
    const storage = memoryStorage()
    saveNativeSession(storage, session)
    clearNativeSession(storage)
    expect(loadNativeSession(storage)).toBeNull()
  })
})
