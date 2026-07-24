/**
 * Shell Центра управления — самостоятельного приложения экосистемы (не раздел Ledger).
 * Управление контейнером: компании, приложения, пользователи, регистрация/доступы, аудит.
 * Приложения-продукты (Ledger, Support) своей админки НЕ имеют — она вынесена сюда.
 *
 * Свой каркас (шапка + выход на рабочий стол), без сайдбара и вкладок Ledger: открывается
 * как отдельное приложение со стола, а не внутри рабочей области учёта.
 */
import { Navigate, useNavigate } from 'react-router-dom'
import { ShieldCheck, LayoutGrid, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CompanySelector } from '@/components/company/CompanySelector'
import { EcoRail } from '@/components/layout/EcoRail'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import { AdminPage } from '@/pages/AdminPage'
import { ECOSYSTEM_TITLE } from '@/config/brand'

export function AdminLayout() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const { company, companies, isCompanyAdmin, isLoading } = useCompany()

  // Центр управления — только администраторам. Не админ → на рабочий стол.
  if (!isLoading && !isCompanyAdmin) return <Navigate to="/" replace />

  return (
    <div className="flex min-h-svh bg-background">
      <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-header items-center justify-between gap-4 border-b border-border px-4 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <span className="rounded-xl bg-primary/10 p-2 text-primary">
            <ShieldCheck className="size-5" />
          </span>
          <div className="min-w-0">
            <div className="truncate font-semibold leading-tight">Центр управления</div>
            <div className="truncate text-xs text-muted-foreground">{company.name} · {ECOSYSTEM_TITLE}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          {companies.length > 1 && <CompanySelector />}
          <Button variant="outline" size="sm" onClick={() => navigate('/')} title="К рабочему столу">
            <LayoutGrid className="size-4" />
            <span className="ml-2 hidden sm:inline">Рабочий стол</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={logout} title="Выйти">
            <LogOut className="size-4" />
          </Button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8">
        <AdminPage />
      </main>
      </div>

      {/* Тот же экосистемный рельс, что в приложениях: отсюда — в приложения и на стол. */}
      <aside className="hidden w-12 shrink-0 flex-col items-center gap-1 border-l border-border/50 bg-card py-2 md:flex">
        <EcoRail standalone />
      </aside>
    </div>
  )
}
