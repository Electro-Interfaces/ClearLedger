/**
 * Вход инженера платформы в пространство клиента по пропуску.
 *
 * Пятый вход без учётки — рядом с приглашением, сбросом пароля, витриной и
 * документом по ссылке. Отличие в том, кто ручается: там ручается наш же токен,
 * здесь — подпись СОСЕДНЕГО пространства, которое у нас заведено поставщиком.
 *
 * Страница ничего не решает: она отдаёт пропуск Ядру и, если тот принят, кладёт
 * выданную сессию и уходит в пространство. Пропуск живёт две минуты, поэтому
 * задерживаться здесь нечего — только сказать человеку, почему не пустили.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, ShieldAlert } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { post } from '@/services/apiClient'

export function SpaceGuestPage() {
  const navigate = useNavigate()
  const { applySession } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const once = useRef(false)

  useEffect(() => {
    if (once.current) return
    once.current = true
    // Пропуск приходит в хэше, а не в пути: так он не попадает ни в журнал
    // сервера, ни в заголовок Referer при следующем переходе.
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const token = params.get('token')
    const space = params.get('space')
    if (!token || !space) { setError('В ссылке нет пропуска'); return }

    post<{ access_token: string }>('/api/eco/partner/visit', { token, space })
      .then(async (res) => {
        history.replaceState(null, '', window.location.pathname)
        await applySession(res.access_token)
        navigate('/', { replace: true })
      })
      .catch((e: Error) => setError(e.message || 'Пропуск не принят'))
  }, [applySession, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center">
        {error ? (
          <>
            <ShieldAlert className="mx-auto h-8 w-8 text-red-600 dark:text-red-400" />
            <h1 className="mt-3 text-base font-semibold text-foreground">Вход не состоялся</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{error}</p>
            <p className="mt-3 text-xs text-muted-foreground">
              Пропуск действует две минуты. Выпишите новый в своём пространстве.
            </p>
          </>
        ) : (
          <>
            <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" />
            <h1 className="mt-3 text-base font-semibold text-foreground">Проверяем пропуск…</h1>
          </>
        )}
      </div>
    </div>
  )
}

export default SpaceGuestPage
