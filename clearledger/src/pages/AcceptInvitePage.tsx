/**
 * Принятие приглашения сотрудника — публичная страница `/invite/:token`.
 * Новый пользователь задаёт имя+пароль (автологин); существующий — принимает
 * и входит обычным способом.
 */
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { FileText, Loader2, CheckCircle2 } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import * as invitationService from '@/services/invitationService'
import type { AcceptPreview } from '@/services/invitationService'

const ROLE_LABEL: Record<string, string> = { admin: 'Администратор', user: 'Сотрудник' }

export function AcceptInvitePage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()
  const { applySession } = useAuth()

  const [preview, setPreview] = useState<AcceptPreview | null>(null)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [joined, setJoined] = useState(false)

  useEffect(() => {
    let alive = true
    invitationService.getAcceptPreview(token)
      .then((p) => { if (alive) setPreview(p) })
      .catch((e) => { if (alive) setLoadError(e?.message || 'Приглашение недействительно') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [token])

  async function handleAccept(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (preview?.user_exists) {
        await invitationService.acceptInvitation(token, {})
        setJoined(true)
      } else {
        const res = await invitationService.acceptInvitation(token, { name, password })
        if ('access_token' in res) {
          await applySession(res.access_token)
          navigate('/', { replace: true })
          return
        }
        setJoined(true)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось принять приглашение')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <FileText className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold">TradeLedger</h1>
        </div>

        {loading && (
          <div className="flex justify-center py-6"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
        )}

        {!loading && loadError && (
          <div className="space-y-4 text-center">
            <div className="rounded-md bg-destructive/10 px-3 py-3 text-sm text-destructive">{loadError}</div>
            <button className="text-primary hover:underline text-sm" onClick={() => navigate('/login')}>На страницу входа</button>
          </div>
        )}

        {!loading && joined && (
          <div className="space-y-4 text-center">
            <CheckCircle2 className="h-10 w-10 text-emerald-500 mx-auto" />
            <p className="text-sm">Готово! Вы добавлены в компанию «{preview?.company_name}». Войдите в систему.</p>
            <button className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={() => navigate('/login')}>Войти</button>
          </div>
        )}

        {!loading && !loadError && !joined && preview && (
          <form onSubmit={handleAccept} className="space-y-4">
            <div className="rounded-lg border border-border/50 p-3 text-sm">
              <p>Вас приглашают в компанию <b>«{preview.company_name}»</b></p>
              <p className="text-muted-foreground">Email: {preview.email} · Роль: {ROLE_LABEL[preview.role] ?? preview.role}</p>
            </div>

            {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

            {preview.user_exists ? (
              <p className="text-sm text-muted-foreground">
                У вас уже есть аккаунт с этим email. Нажмите «Принять», затем войдите в систему.
              </p>
            ) : (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">ФИО</label>
                  <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Фамилия Имя Отчество"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Пароль (мин. 6 символов)</label>
                  <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6}
                    autoComplete="new-password"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
                </div>
              </>
            )}

            <button type="submit" disabled={submitting}
              className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {preview.user_exists ? 'Принять приглашение' : 'Создать аккаунт и войти'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default AcceptInvitePage
