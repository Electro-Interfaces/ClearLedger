import { StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'

// Actual provider, service and HTTP client. Only network outcomes are controlled
// by Playwright; no copy of the effect or replacement auth/storage implementation.
let root: Root | undefined
let auth: ReturnType<typeof useAuth> | undefined
let finished = 0
let started = 0
const completed = new Set<number>()
const aborted = new Set<number>()
const nativeFetch = window.fetch.bind(window)
window.fetch = async (...args) => {
  const attempt = ++started
  const [input, options] = args
  const headers = new Headers(options?.headers)
  headers.set('X-React-Probe-Request', String(attempt))
  options?.signal?.addEventListener('abort', () => aborted.add(attempt))
  try { return await nativeFetch(input, { ...options, headers }) }
  finally { finished += 1; completed.add(attempt) }
}

function Probe() {
  auth = useAuth()
  return <main><h1>AuthContext lifecycle</h1><output data-testid="auth-state">{JSON.stringify({
    user: auth.user?.id ?? null, token: auth.token,
    authenticated: auth.isAuthenticated, loading: auth.loading,
  })}</output></main>
}

const fixture = {
  mount(strict = false) {
    root = createRoot(document.getElementById('root')!)
    const provider = <AuthProvider><Probe /></AuthProvider>
    flushSync(() => root!.render(strict ? <StrictMode>{provider}</StrictMode> : provider))
  },
  unmount() { flushSync(() => root?.unmount()); root = undefined; auth = undefined },
  applySession: (token: string) => auth!.applySession(token),
  login: (otp?: string) => auth!.login('synthetic@example.invalid', 'synthetic-password', otp),
  logout: () => auth!.logout(),
  refreshMe: () => auth!.refreshMe(),
  finished: () => finished,
  started: () => started,
  completed: (attempt: number) => completed.has(attempt),
  aborted: (attempt: number) => aborted.has(attempt),
}
Object.assign(window, { fixture })
