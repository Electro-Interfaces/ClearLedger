/* eslint-disable react-refresh/only-export-components -- точка входа сборки: компоненты здесь не горячо заменяются */
/**
 * Публичная сборка пространства — то, что получает посетитель без входа (пункт 6
 * аудита безопасности 07.10.2026).
 *
 * Основное приложение nginx стека отдаёт только с меткой входа (HttpOnly cookie
 * `cl_gate`). Без неё — эта сборка: вход и восемь страниц по ссылкам (приглашение,
 * сброс пароля, витрина, документ, встреча, проверка документа, гость-партнёр).
 * Кода рабочих экранов здесь нет — посторонний его не скачает. Демо-магазин сюда не
 * входит: он тянет весь модуль «Магазин»; на боевых стеках он открывается после входа.
 *
 * Любой другой адрес: если в браузере уже есть рабочий токен (вошли до введения
 * меток или метка истекла раньше токена) — ставим метку по нему и перезагружаем
 * страницу, уже в основное приложение; иначе — на вход с возвратом.
 */
import { StrictMode, Suspense, lazy, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import '../index.css'
import { queryClient } from '@/lib/queryClient'
import { AuthProvider } from '@/contexts/AuthContext'
import { CompanyProvider } from '@/contexts/CompanyContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { getToken } from '@/services/apiClient'

// Пропуск гостя-партнёра приходит во фрагменте адреса — как в основной сборке.
if (window.location.pathname.replace(/\/$/, '').endsWith('/space-guest')
    && window.location.hash.includes('token=')) {
  try { sessionStorage.setItem('eco-space-pass', window.location.hash.replace(/^#/, '')) } catch { /* приватный режим */ }
  history.replaceState(null, '', window.location.pathname)
}

const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const AcceptInvitePage = lazy(() => import('@/pages/AcceptInvitePage').then((m) => ({ default: m.AcceptInvitePage })))
const ResetPasswordPage = lazy(() => import('@/pages/ResetPasswordPage').then((m) => ({ default: m.ResetPasswordPage })))
const SpaceGuestPage = lazy(() => import('@/pages/SpaceGuestPage').then((m) => ({ default: m.SpaceGuestPage })))
const DocSharePage = lazy(() => import('@/pages/DocSharePage').then((m) => ({ default: m.DocSharePage })))
const InvitePage = lazy(() => import('@/pages/InvitePage').then((m) => ({ default: m.InvitePage })))
const DocVerifyPage = lazy(() => import('@/pages/DocVerifyPage').then((m) => ({ default: m.DocVerifyPage })))
const ShowcaseLinkPage = lazy(() => import('@/pages/ShowcaseLinkPage').then((m) => ({ default: m.ShowcaseLinkPage })))

function Loading() {
  return <div className="flex h-[50vh] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
}

/** Адрес основного приложения: поставить метку по токену и перезагрузить, иначе — на вход. */
function ToApp() {
  const { pathname, search, hash } = useLocation()
  const target = `${pathname}${search}${hash}`
  const token = getToken()
  useEffect(() => {
    if (!token) return
    let gone = false
    fetch('/api/auth/gate', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, credentials: 'same-origin' })
      .then((r) => {
        if (gone) return
        // Метка поставлена — основное приложение отдастся; токен негоден — на вход.
        if (r.ok) window.location.replace(target)
        else window.location.replace(`/login?next=${encodeURIComponent(target)}`)
      })
      .catch(() => { if (!gone) window.location.replace(`/login?next=${encodeURIComponent(target)}`) })
    return () => { gone = true }
  }, [token, target])
  if (!token) return <Navigate to={`/login?next=${encodeURIComponent(target)}`} replace />
  return <Loading />
}

function Shell() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <CompanyProvider>
            <TooltipProvider>
              <Suspense fallback={<Loading />}><Outlet /></Suspense>
              <Toaster position="bottom-right" richColors closeButton />
            </TooltipProvider>
          </CompanyProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

const router = createBrowserRouter([{
  element: <Shell />,
  children: [
    { path: '/login', element: <LoginPage /> },
    { path: '/invite/:token', element: <AcceptInvitePage /> },
    { path: '/reset-password/:token', element: <ResetPasswordPage /> },
    { path: '/space-guest', element: <SpaceGuestPage /> },
    { path: '/showcase/:token', element: <ShowcaseLinkPage /> },
    { path: '/doc-share/:token', element: <DocSharePage /> },
    { path: '/meeting/:token', element: <InvitePage /> },
    { path: '/doc-verify/:token', element: <DocVerifyPage /> },
    { path: '*', element: <ToApp /> },
  ],
}])

createRoot(document.getElementById('root')!).render(
  <StrictMode><RouterProvider router={router} /></StrictMode>,
)
