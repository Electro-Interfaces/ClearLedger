/**
 * Страница регистрации — создание нового аккаунта.
 */

import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import * as authService from '@/services/authService'
import { isApiEnabled, get } from '@/services/apiClient'
import { FileText, Loader2 } from 'lucide-react'

interface CompanyOption {
  id: string
  name: string
  slug: string
}

export function RegisterPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [companyId, setCompanyId] = useState('')
  const [companies, setCompanies] = useState<CompanyOption[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Загрузить список компаний
  useEffect(() => {
    if (!isApiEnabled()) return
    get<CompanyOption[]>('/api/companies')
      .then((list) => {
        setCompanies(list)
        if (list.length > 0) setCompanyId(list[0].id)
      })
      .catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!companyId) {
      setError('Выберите компанию')
      return
    }
    setError('')
    setLoading(true)
    try {
      const result = await authService.register({
        email,
        name,
        password,
        company_id: companyId,
      })
      // Авторизуем сразу — токен уже сохранён в authService.register
      if (result.user) {
        // Используем login для обновления AuthContext
        await login(email, password)
      }
      navigate('/', { replace: true })
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Ошибка регистрации'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const inputClass =
    'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <FileText className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold">ClearLedger</h1>
          <p className="text-sm text-muted-foreground">Регистрация</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="name" className="text-sm font-medium">Имя</label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoComplete="name"
              className={inputClass}
              placeholder="Иван Петров"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="reg-email" className="text-sm font-medium">Email</label>
            <input
              id="reg-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className={inputClass}
              placeholder="user@company.ru"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="reg-password" className="text-sm font-medium">Пароль</label>
            <input
              id="reg-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              autoComplete="new-password"
              className={inputClass}
              placeholder="Минимум 6 символов"
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="company" className="text-sm font-medium">Компания</label>
            <select
              id="company"
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
              required
              className={inputClass}
            >
              {companies.length === 0 && (
                <option value="">Загрузка...</option>
              )}
              {companies.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={loading || !companyId}
            className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Зарегистрироваться
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Уже есть аккаунт?{' '}
          <Link to="/login" className="text-primary hover:underline">
            Войти
          </Link>
        </p>
      </div>
    </div>
  )
}
