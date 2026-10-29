import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { Button } from '@/components/ui/button'
import { isApiEnabled, isDemoMode } from '@/services/apiClient'
import { beginDocsLogin, cancelDocsRuntime, docsCallbackInput, DocsError, finishDocsLogin, getDocsMetadata, getDocsSession, logoutDocs,
  type DocsMetadata, type DocsSession } from '@/services/developerDocsService'

function DocsPortal({ userId, callback }: { userId: string; callback: boolean }) {
  const [metadata, setMetadata] = useState<DocsMetadata>()
  const [session, setSession] = useState<DocsSession>()
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const frame = useRef<HTMLIFrameElement>(null)
  const decision = useRef(false)
  const location = useLocation()
  const callbackInput = useRef(callback ? docsCallbackInput(location.search) : '')
  const navigate = useNavigate()
  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    const load = async () => {
      try {
        const config = await getDocsMetadata(controller.signal)
        if (!alive) return
        setMetadata(config)
        if (!config.ready) return
        let current: DocsSession | undefined
        try { current = callback ? await finishDocsLogin(callbackInput.current) : await getDocsSession(controller.signal) }
        catch (e) { if (callback || !(e instanceof DocsError && e.status === 401)) throw e }
        if (!alive) return
        if (current && (current.userId !== userId || current.userId !== config.coreUserId)) { await logoutDocs(current, config); current = undefined }
        setSession(current)
        if (callback && current) navigate('/developer/api', { replace: true })
      } catch (e) { if (alive) setError(e instanceof Error ? e.message : 'Документация недоступна') }
      finally { if (alive) setBusy(false) }
    }
    void load()
    return () => { alive = false; controller.abort(); cancelDocsRuntime() }
  }, [userId, callback, navigate])
  useEffect(() => {
    if (!session) return
    const timer = setInterval(() => {
      void getDocsSession().then((current) => {
        if (current.userId !== userId) throw new DocsError('Учётная запись изменилась')
      }).catch(() => { setSession(undefined); setError('Доступ к документации завершён или отозван') })
    }, 10000)
    return () => clearInterval(timer)
  }, [session, userId])
  const act = async (logout: boolean) => {
    if (decision.current) return
    decision.current = true; setBusy(true); setError('')
    try {
      if (logout) {
        frame.current?.contentWindow?.postMessage({ type: 'docs:logout' }, window.location.origin)
        await logoutDocs(session, metadata); setSession(undefined)
      } else if (metadata) await beginDocsLogin(metadata)
    } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось выполнить действие') }
    finally { decision.current = false; setBusy(false) }
  }
  return <main className="min-h-dvh bg-muted/40 px-4 py-8 sm:px-6">
    <div className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1"><h1 className="font-headline text-xl font-semibold">API для разработчиков</h1>
          <p className="text-sm text-muted-foreground">Документация и доступ к API выдаются отдельными согласиями.</p></div>
        {session && <Button variant="outline" disabled={busy} onClick={() => void act(true)}>Выйти из документации</Button>}
      </header>
      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm">{error}</p>}
      {busy && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />Проверяем доступ…</p>}
      {metadata && !metadata.sandboxReady && <div className="space-y-1 rounded-xl border bg-card p-4">
        <h2 className="text-sm font-semibold">Требуется настройка тестового контура</h2>
        <p className="text-sm text-muted-foreground">Выполнение запросов отключено. Администратор должен настроить публичный клиент и тестовый API этого пространства.</p>
      </div>}
      {!session && !busy && metadata?.ready && <section className="max-w-xl space-y-4 rounded-xl border bg-card p-5">
        <h2 className="text-lg font-semibold">Открыть защищённую документацию</h2>
        <p className="text-sm text-muted-foreground">Потребуется явное согласие на чтение документации. Право выполнять запросы к данным выдаётся отдельно в Swagger Authorize.</p>
        <Button onClick={() => void act(false)}>Открыть документацию</Button>
      </section>}
      {metadata && !metadata.ready && !busy && <p role="status" className="text-sm">Портал не настроен. Обратитесь к администратору пространства.</p>}
      {session && <iframe ref={frame} src="/api/developer/docs/ui" title="Защищённая Swagger документация" className="min-h-[70dvh] w-full rounded-xl border bg-card" />}
      <Link to="/" className="text-sm text-primary underline underline-offset-4">На главную</Link>
    </div>
  </main>
}

export function DeveloperApiPage() {
  const { user, loading, isAuthenticated } = useAuth()
  const location = useLocation()
  const callback = location.pathname.endsWith('/callback')
  useEffect(() => { document.title = 'API для разработчиков' }, [])
  if (!isApiEnabled() || isDemoMode()) return <main className="p-8"><p role="alert">Документация API недоступна в demo/offline.</p></main>
  if (loading) return <ProtectedRoute><span /></ProtectedRoute>
  if (!isAuthenticated || !user) return <Navigate to="/login?next=%2Fdeveloper%2Fapi" replace state={{ from: '/developer/api' }} />
  return <ProtectedRoute><DocsPortal key={`${user.id}:${callback}`} userId={user.id} callback={callback} /></ProtectedRoute>
}
