import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { CompanyProvider, useCompany } from '@/contexts/CompanyContext'
import { SupportProvider } from '@/contexts/SupportContext'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { AuditorPanel } from '@/components/auditor/AuditorPanel'
import { Toaster } from 'sonner'
import '@/index.css'

// Actual providers, panel, dictation hook and service. Only HTTP/media-device
// boundaries are synthetic. No copied request guards or conversation state.
const asks: { body: unknown; signal?: AbortSignal | null; writer: ReadableStreamDefaultController<Uint8Array>; cancelled: boolean }[] = []
const uploads: { resolve: (value: Response) => void }[] = []
const dictations: { resolve: (value: Response) => void }[] = []
const user = { id: 'user-A', email: 'synthetic@example.test', name: 'Тест', role: 'user', is_superadmin: true,
  companies: ['company-A', 'company-B'].map((id) => ({ id, name: id, slug: id, profile_id: 'fuel' })) }
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
const nativeFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin), path = url.pathname
  if (url.origin !== location.origin) throw new Error('External network forbidden')
  if (path === '/auditor/api/ask') {
    let writer!: ReadableStreamDefaultController<Uint8Array>
    const call = { body: JSON.parse(init?.body as string), signal: init?.signal, writer, cancelled: false }
    const body = new ReadableStream<Uint8Array>({ start(controller) { call.writer = controller }, cancel() { call.cancelled = true } })
    asks.push(call); return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
  }
  if (path === '/auditor/api/upload') return new Promise((resolve) => uploads.push({ resolve }))
  if (path === '/auditor/api/dictate') return new Promise((resolve) => dictations.push({ resolve }))
  if (path === '/auditor/health') return json({ ok: true, dictation: true })
  if (path.endsWith('/auth/me')) return json(user)
  if (path === '/api/registry/company-apps') return json({ apps: [] })
  if (path.includes('/organizations')) return json(['org-A', 'org-B'].map((id) => ({ id, name: id })))
  if (path.startsWith('/api/') || path.startsWith('/auditor/api/')) return json([])
  return nativeFetch(input, init)
}

// Actual useDictation runs on synthetic audio hardware; no permission prompt,
// recording from a real microphone, backend ASR or media installation.
Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
  getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
} })
class SyntheticRecorder {
  stream: MediaStream
  mimeType = 'audio/webm'
  ondataavailable?: (event: { data: Blob }) => void
  onstop?: () => void
  constructor(stream: MediaStream) { this.stream = stream }
  start() {}
  stop() { this.ondataavailable?.({ data: new Blob(['synthetic audio']) }); this.onstop?.() }
}
Object.assign(window, { MediaRecorder: SyntheticRecorder })
localStorage.setItem('clearledger-token', 'synthetic-A')

export function Login() {
  const auth = useAuth(), navigate = useNavigate()
  return <button onClick={async () => { await auth.applySession('synthetic-A'); navigate('/fixture') }}>Войти снова</button>
}
export function Scope() {
  const { companyId, organizationId, setCompanyId, setOrganizationId } = useCompany()
  const auth = useAuth()
  // Same company/user parent identity as App.tsx; organization deliberately has
  // no fixture key: the actual panel must own that missing lifetime boundary.
  return <main>
    <h1>Проверка разговора аудитора</h1>
    <output data-testid="scope">{companyId}:{organizationId ?? ''}</output>
    <button onClick={() => setOrganizationId('org-A')}>Организация А</button>
    <button onClick={() => setOrganizationId('org-B')}>Организация Б</button>
    <button onClick={() => setCompanyId('company-B')}>Компания Б</button>
    <button onClick={() => auth.logout()}>Выйти</button>
    <div key={`${companyId}:${auth.user?.id ?? ''}`} style={{ height: 600 }}>
      <SupportProvider><AuditorPanel /></SupportProvider>
    </div>
    <Toaster />
  </main>
}
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={qc}><MemoryRouter initialEntries={['/fixture']}>
    <AuthProvider><CompanyProvider><Routes>
      <Route path="/fixture" element={<ProtectedRoute><Scope /></ProtectedRoute>} />
      <Route path="/login" element={<Login />} />
    </Routes></CompanyProvider></AuthProvider>
  </MemoryRouter></QueryClientProvider>,
)
Object.assign(window, { auditorFixture: {
  asks, uploads, dictations,
  send(index: number, wire: string) { const call = asks[index]; if (!call.cancelled) call.writer.enqueue(new TextEncoder().encode(wire)) },
  upload(index: number, failed = false) { uploads[index].resolve(failed
    ? new Response('{"error":"late upload error"}', { status: 503, headers: { 'Content-Type': 'application/json' } })
    : json({ id: `file-${index}`, name: `attached-${index}.txt`, size: 4 })) },
  dictate(index: number, text: string) { dictations[index].resolve(json({ text })) },
} })
