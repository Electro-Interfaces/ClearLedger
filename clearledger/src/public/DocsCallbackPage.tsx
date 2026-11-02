/** Minimal public callback: no Swagger/spec/main application import. */
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { post } from '@/services/apiClient'
import { cancelDocsRuntime, docsCallbackInput, finishDocsLogin, logoutDocs } from '@/services/developerDocsService'

export function DocsCallbackPage() {
  const { user, loading } = useAuth()
  const location = useLocation()
  const input = useRef(docsCallbackInput(location.search))
  const [error, setError] = useState('')
  useEffect(() => {
    if (loading) return
    let alive = true
    if (!user) {
      void logoutDocs()
      return () => { alive = false }
    }
    void finishDocsLogin(input.current).then(async (session) => {
      if (!alive) return
      if (session.userId !== user.id) { await logoutDocs(session); throw new Error('Учётная запись изменилась. Начните вход заново.') }
      await post<void>('/api/auth/gate') // Core transport only, partner bearer never reaches this endpoint.
      if (alive) window.location.replace('/developer/api')
    }).catch(() => { if (alive) setError('Ответ авторизации недействителен или просрочен. Начните подключение заново.') })
    return () => { alive = false; cancelDocsRuntime() }
  }, [user, loading])
  const message = !loading && !user ? 'Войдите в пространство и начните подключение документации заново.' : error
  return <main className="mx-auto max-w-xl space-y-4 px-4 py-12">
    <h1 className="font-headline text-xl font-semibold">Возврат в документацию API</h1>
    {message ? <><p role="alert" className="text-sm">{message}</p>
      <Link to="/login?next=%2Fdeveloper%2Fapi" className="text-sm text-primary underline underline-offset-4">Войти и начать заново</Link></>
      : <p role="status" className="text-sm">Проверяем одноразовый ответ авторизации…</p>}
  </main>
}
