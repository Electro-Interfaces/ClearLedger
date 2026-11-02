import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { useAuth } from '@/contexts/AuthContext'
import { getToken, isApiEnabled, isDemoMode } from '@/services/apiClient'
import {
  AUTHORIZATION_PROBLEMS, authorizationProblem, authorizationRequestId,
  approveAuthorizationRequest, denyAuthorizationRequest, eligibleAuthorizationScopes,
  getAuthorizationRequest, type AuthorizationProblem, type AuthorizationRequest,
} from '@/services/developerService'

function Frame({ children, email }: { children: ReactNode; email?: string }) {
  return <main className="min-h-dvh bg-muted/40 px-4 py-8 sm:py-12">
    <div className="mx-auto w-full max-w-xl space-y-6">
      <header className="space-y-2">
        <h1 className="font-headline text-xl font-semibold">Доступ внешнего приложения</h1>
        {email && <p className="break-words text-sm text-muted-foreground">Вы вошли как {email}</p>}
      </header>
      {children}
    </div>
  </main>
}

function Problem({ kind }: { kind: AuthorizationProblem }) {
  const problem = AUTHORIZATION_PROBLEMS[kind]
  return <div role="alert" className="space-y-1 rounded-md border border-destructive/30 bg-destructive/5 p-4">
    <h2 className="text-sm font-semibold">{problem.title}</h2>
    <p className="text-sm text-muted-foreground">{problem.description}</p>
  </div>
}

function LoginAgain({ requestId }: { requestId: string }) {
  const from = `/developer/authorize?requestId=${encodeURIComponent(requestId)}`
  return <Link to={`/login?next=${encodeURIComponent(from)}`} state={{ from }}
    className="text-sm text-primary underline underline-offset-4">Войти снова</Link>
}

type LoadState = { status: 'loading' } | { status: 'error'; problem: AuthorizationProblem; context: object }
  | { status: 'ready'; request: AuthorizationRequest; generation: number; context: object }

/** Один запрос согласия; смена request/user размонтирует его вместе с выбором. */
function ConsentRequest({ requestId, token, email }: { requestId: string; token: string; email: string }) {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [companyId, setCompanyId] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [problem, setProblem] = useState<AuthorizationProblem | null>(null)
  const [pending, setPending] = useState<'approve' | 'deny' | null>(null)
  const generation = useRef(0)
  const submitting = useRef(false)
  const context = useMemo(() => ({ requestId, token }), [requestId, token])

  useEffect(() => {
    const current = ++generation.current
    const controller = new AbortController()
    getAuthorizationRequest(requestId, controller.signal).then((request) => {
      if (generation.current !== current || controller.signal.aborted) return
      if (getToken() !== context.token || isDemoMode()) {
        setState({ status: 'error', problem: 'unauthenticated', context }); return
      }
      setCompanyId(''); setScopes([]); setProblem(null); setPending(null)
      submitting.current = false
      setState(Date.parse(request.expiresAt) <= Date.now()
        ? { status: 'error', problem: 'expired', context }
        : { status: 'ready', request, generation: current, context })
    }).catch((error: unknown) => {
      if (generation.current !== current || controller.signal.aborted) return
      setState({ status: 'error', problem: authorizationProblem(error), context })
    })
    return () => { generation.current = current + 1; controller.abort() }
  }, [requestId, context])

  useEffect(() => {
    if (state.status !== 'ready' || state.context !== context) return
    let timer: ReturnType<typeof setTimeout>
    const expire = () => {
      const remaining = Date.parse(state.request.expiresAt) - Date.now()
      if (remaining <= 0) setProblem('expired')
      else timer = setTimeout(expire, Math.min(remaining, 2_147_483_647))
    }
    expire()
    return () => clearTimeout(timer)
  }, [state, context])

  const submit = async (decision: 'approve' | 'deny') => {
    if (state.status !== 'ready' || state.context !== context || submitting.current || problem || generation.current !== state.generation) return
    if (Date.parse(state.request.expiresAt) <= Date.now()) { setProblem('expired'); return }
    if (getToken() !== token || isDemoMode()) { setProblem('unauthenticated'); return }
    const allowed = eligibleAuthorizationScopes(state.request, companyId)
    if (decision === 'approve' && (!companyId || !scopes.length || scopes.some((scope) => !allowed.includes(scope)))) return
    if (decision === 'approve' && state.request.requestedScopes.some((scope) => scope.code === 'openid') && !scopes.includes('openid')) return
    const current = generation.current
    submitting.current = true // синхронно: два клика до следующего render дают одну команду.
    setPending(decision)
    let completed = false
    try {
      const redirectUrl = decision === 'approve'
        ? await approveAuthorizationRequest(state.request, companyId, scopes)
        : await denyAuthorizationRequest(state.request.id)
      if (generation.current !== current) return
      if (getToken() !== token || isDemoMode()) { setProblem('unauthenticated'); return }
      if (Date.parse(state.request.expiresAt) <= Date.now()) { setProblem('expired'); return }
      // Обычная навигация браузера: Core Bearer остаётся в apiClient и не едет на callback.
      completed = true
      window.location.assign(redirectUrl)
    } catch (error: unknown) {
      if (generation.current === current) setProblem(authorizationProblem(error))
    } finally {
      if (generation.current === current && !completed) {
        submitting.current = false
        setPending(null)
      }
    }
  }

  if (state.status === 'loading' || state.context !== context) return <Frame email={email}>
    <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />Загружаем запрос согласия…
    </p>
  </Frame>
  if (state.status === 'error') return <Frame email={email}>
    <Problem kind={state.problem} />
    {state.problem === 'unauthenticated' ? <LoginAgain requestId={requestId} />
      : <Link to="/" className="text-sm text-primary underline underline-offset-4">На главную</Link>}
  </Frame>

  const { request } = state
  const allowed = eligibleAuthorizationScopes(request, companyId)
  const identityRequired = request.requestedScopes.some((scope) => scope.code === 'openid')
  const disabled = !!pending || !!problem
  const canApprove = !disabled && !!companyId && scopes.length > 0 && scopes.every((scope) => allowed.includes(scope))
    && (!identityRequired || scopes.includes('openid'))
  return <Frame email={email}>
    <section aria-labelledby="client-name" className="space-y-6 rounded-xl border bg-card p-5 sm:p-6">
      <div className="space-y-2">
        <h2 id="client-name" className="break-words text-lg font-semibold">«{request.clientName}» запрашивает доступ</h2>
        <p className="text-sm text-muted-foreground">Выберите компанию и действия, которые разрешаете приложению.</p>
      </div>
      <div className="space-y-2">
        <label htmlFor="consent-company" className="text-sm font-medium">Компания</label>
        <select id="consent-company" value={companyId} disabled={disabled}
          className="h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50"
          onChange={(event) => { setCompanyId(event.target.value); setScopes([]) }}>
          <option value="">Выберите компанию</option>
          {request.companies.map((company) => <option key={company.id} value={company.id}
            disabled={!eligibleAuthorizationScopes(request, company.id).length}>{company.name}</option>)}
        </select>
        {!request.companies.some((company) => eligibleAuthorizationScopes(request, company.id).length > 0)
          && <p className="text-sm text-muted-foreground">Нет компаний с доступными действиями. Вы можете отказать приложению.</p>}
      </div>
      <fieldset disabled={disabled} className="min-w-0">
        <legend className="mb-2 text-sm font-medium">Запрошенные действия</legend>
        {!companyId && <p className="mb-2 text-sm text-muted-foreground">Выберите компанию, чтобы отметить доступные действия.</p>}
        <div className="divide-y">
          {request.requestedScopes.map((scope) => <label key={scope.code}
            className="flex min-h-11 items-start gap-3 py-3">
            <input type="checkbox" checked={scopes.includes(scope.code)} disabled={!allowed.includes(scope.code)}
              className="mt-1 size-4 shrink-0 accent-primary"
              onChange={(event) => setScopes((previous) => event.target.checked
                ? [...previous, scope.code] : previous.filter((code) => code !== scope.code))} />
            <span className="min-w-0 space-y-1 text-sm">
              <span className="block break-words">{scope.description || scope.code}</span>
              <span className="block break-all font-mono text-xs text-muted-foreground">{scope.code}</span>
              {scope.code === 'openid' && <span className="block text-xs text-muted-foreground">Обязательно для подтверждения личности при подключении</span>}
              {companyId && !allowed.includes(scope.code)
                && <span className="block text-xs text-muted-foreground">Недоступно для выбранной компании</span>}
            </span>
          </label>)}
        </div>
        {!request.requestedScopes.length && <p className="text-sm text-muted-foreground">Приложение не запросило действий. Доступ нельзя предоставить.</p>}
      </fieldset>
      <p className="text-xs text-muted-foreground">Запрос действует до{' '}
        <time dateTime={request.expiresAt}>{new Date(request.expiresAt).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}</time>.
      </p>
      {problem && <Problem kind={problem} />}
      <div className="flex flex-col-reverse gap-3 border-t pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="outline" disabled={disabled} onClick={() => void submit('deny')}>
          {pending === 'deny' && <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />}Отказать
        </Button>
        <Button type="button" disabled={!canApprove} onClick={() => void submit('approve')}>
          {pending === 'approve' && <Loader2 aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />}Разрешить выбранные действия
        </Button>
      </div>
      {pending && <p role="status" className="text-sm text-muted-foreground">Сохраняем решение…</p>}
      {problem === 'unauthenticated' && <LoginAgain requestId={requestId} />}
    </section>
  </Frame>
}

export function DeveloperAuthorizePage() {
  const { user, token, isAuthenticated, loading } = useAuth()
  const location = useLocation()
  const requestId = authorizationRequestId(location.search)
  useEffect(() => {
    const title = document.title
    document.title = 'Доступ внешнего приложения'
    return () => { document.title = title }
  }, [])
  if (!isApiEnabled() || isDemoMode()) return <Frame><Problem kind="unavailable" /></Frame>
  if (loading) return <ProtectedRoute><Frame><p role="status">Проверяем вход…</p></Frame></ProtectedRoute>
  const returnTo = requestId ? `/developer/authorize?requestId=${encodeURIComponent(requestId)}` : '/developer/authorize'
  // LoginPage уже проверяет next через safeBackTo. Дублируем штатный state.from
  // внутренним next: обвязка login может заменить history state при синхронизации фильтра.
  if (!isAuthenticated || !user || !token || token !== getToken()) return <Navigate to={`/login?next=${encodeURIComponent(returnTo)}`} replace
    state={{ from: returnTo }} />
  if (!requestId) return <Frame email={user.email}><Problem kind="invalid" /></Frame>
  return <ProtectedRoute><ConsentRequest key={`${user.id}:${requestId}`} requestId={requestId} token={token} email={user.email} /></ProtectedRoute>
}
