/**
 * Гард авторизации: пускает в приложение только авторизованных.
 * Пока грузится /me — спиннер; нет сессии — редирект на /login.
 */
import { Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  // Путь относительный — базу сборки роутер применяет сам.
  // Куда человек шёл — помним: ссылку на работу (`/t/TF-42`) чаще всего
  // открывают из письма в свежей вкладке, и без этого вход уносил на главную,
  // а присланный адрес терялся.
  if (!isAuthenticated) {
    return <Navigate to="/login" replace
      state={{ from: `${location.pathname}${location.search}${location.hash}` }} />
  }
  return <>{children}</>
}
