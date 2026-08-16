/**
 * Гард авторизации: пускает в приложение только авторизованных.
 * Пока грузится /me — спиннер; нет сессии — редирект на /login.
 */
import { Navigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  // Путь относительный — базу сборки роутер применяет сам.
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}
