/**
 * Установка нового пароля по ссылке из письма — публичная страница `/reset-password/:token`.
 * Валидирует токен (getResetPreview), затем форма нового пароля.
 */
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { FileText, Loader2, CheckCircle2 } from 'lucide-react'
import * as authService from '@/services/authService'

export function ResetPasswordPage() {
  const { token = '' } = useParams()
  const navigate = useNavigate()

  const [email, setEmail] = useState<string | null>(null)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    let alive = true
    authService.getResetPreview(token)
      .then((p) => { if (alive) setEmail(p.email) })
      .catch((e) => { if (alive) setLoadError(e?.message || 'Ссылка недействительна или истекла') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (password !== confirm) { setError('Пароли не совпадают'); return }
    setSubmitting(true)
    try {
      await authService.resetPassword(token, password)
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось изменить пароль')
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls = "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <FileText className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold">Ledger</h1>
          <p className="text-sm text-muted-foreground">Новый пароль</p>
        </div>

        {loading && (
          <div className="flex justify-center py-6"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
        )}

        {!loading && loadError && (
          <div className="space-y-4 text-center">
            <div className="rounded-md bg-destructive/10 px-3 py-3 text-sm text-destructive">{loadError}</div>
            <button className="text-sm text-primary hover:underline" onClick={() => navigate('/login')}>На страницу входа</button>
          </div>
        )}

        {!loading && done && (
          <div className="space-y-4 text-center">
            <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" />
            <p className="text-sm">Пароль изменён. Войдите с новым паролем.</p>
            <button className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={() => navigate('/login')}>Войти</button>
          </div>
        )}

        {!loading && !loadError && !done && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <p className="text-sm text-muted-foreground">Аккаунт: <b>{email}</b></p>
            {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}
            <div className="space-y-2">
              <label className="text-sm font-medium">Новый пароль (мин. 6 символов)</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} autoComplete="new-password" className={inputCls} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Повторите пароль</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={6} autoComplete="new-password" className={inputCls} />
            </div>
            <button type="submit" disabled={submitting}
              className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Сохранить пароль
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

export default ResetPasswordPage
