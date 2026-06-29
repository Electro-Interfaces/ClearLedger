/**
 * Страница логина — показывается только в API-режиме.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import * as authService from '@/services/authService'
import { FileText, Loader2, CheckCircle2 } from 'lucide-react'

export function LoginPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  // Режим «восстановление пароля».
  const [mode, setMode] = useState<'login' | 'forgot'>('login')
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotLoading, setForgotLoading] = useState(false)
  const [forgotSent, setForgotSent] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      // login() из контекста: токен + /me + обновление состояния auth (иначе
      // ProtectedRoute не увидит авторизацию и вернёт назад на /login).
      await login(email, password)
      navigate('/', { replace: true })
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Ошибка входа'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault()
    setForgotLoading(true)
    try {
      await authService.forgotPassword(forgotEmail)
      setForgotSent(true)
    } catch {
      // По дизайну не раскрываем, есть ли email — показываем тот же успех.
      setForgotSent(true)
    } finally {
      setForgotLoading(false)
    }
  }

  const inputCls = "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"

  if (mode === 'forgot') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex flex-col items-center gap-2">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <FileText className="h-6 w-6" />
            </div>
            <h1 className="text-2xl font-bold">Ledger</h1>
            <p className="text-sm text-muted-foreground">Восстановление пароля</p>
          </div>

          {forgotSent ? (
            <div className="space-y-4 text-center">
              <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" />
              <p className="text-sm">Если аккаунт с таким email существует, мы отправили на него ссылку для восстановления пароля. Ссылка действует 1 час.</p>
              <button className="text-sm text-primary hover:underline"
                onClick={() => { setMode('login'); setForgotSent(false); setForgotEmail('') }}>
                ← Вернуться ко входу
              </button>
            </div>
          ) : (
            <form onSubmit={handleForgot} className="space-y-4">
              <p className="text-sm text-muted-foreground">Укажите email — пришлём ссылку для установки нового пароля.</p>
              <div className="space-y-2">
                <label htmlFor="forgot-email" className="text-sm font-medium">Email</label>
                <input id="forgot-email" type="email" value={forgotEmail} required autoComplete="email"
                  onChange={(e) => setForgotEmail(e.target.value)} className={inputCls} placeholder="you@example.ru" />
              </div>
              <button type="submit" disabled={forgotLoading}
                className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                {forgotLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Отправить ссылку
              </button>
              <button type="button" className="block w-full text-center text-sm text-muted-foreground hover:text-foreground"
                onClick={() => setMode('login')}>
                ← Вернуться ко входу
              </button>
            </form>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <FileText className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold">Ledger</h1>
          <p className="text-sm text-muted-foreground">Вход в систему</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="admin@clearledger.ru"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium">
              Пароль
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="text-right">
            <button type="button" onClick={() => setMode('forgot')}
              className="text-xs text-muted-foreground hover:text-primary">
              Забыли пароль?
            </button>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Войти
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Для получения доступа обратитесь к администратору
        </p>
      </div>
    </div>
  )
}
