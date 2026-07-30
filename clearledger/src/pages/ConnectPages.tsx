/**
 * Страницы приложения «Подключения» — внешнего контура пространства.
 *
 * Отделены от «Управления» (решение МАГа 30.07.2026): там вопрос «кто из людей что
 * может», здесь «откуда приходят данные и живо ли подключение». Ходят сюда разные люди:
 * админ по людям не настраивает ключи STS, инженер интеграций не раздаёт роли.
 *
 * Экраны те же самые компоненты, что стояли разделами «Управления» — переехал только
 * вход. Ниже лишь обёртки: берут активную компанию из контекста пространства (в
 * «Управлении» её отдавал Outlet) и ставят заголовок раздела.
 */
import type { ReactNode } from 'react'
import { Bell, Blocks, Cable } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Connections } from '@/components/admin/Connections'
import { Notifications } from '@/components/admin/Notifications'
import { CompanyApps } from '@/components/admin/CompanyApps'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

/**
 * Право править настройку связи = администрирование открытой организации. Тот же
 * расчёт, что в `AdminLayout`: суперадмин контейнера или админ этой организации.
 */
function useCanManage() {
  const { user } = useAuth()
  const { companyId } = useCompany()
  return {
    companyId,
    isSuperadmin: !!user?.is_superadmin,
    canManage: !!user?.is_superadmin || (user?.companies ?? []).some((c) => c.id === companyId && c.role === 'admin'),
  }
}

function Page({ icon: Icon, title, hint, children }: {
  icon: React.ComponentType<{ className?: string }>
  title: string; hint: string; children: ReactNode
}) {
  return (
    <div className="w-full space-y-4">
      <div className="flex items-center gap-2.5">
        <Icon className="h-6 w-6 text-primary" />
        <div className="min-w-0">
          <h2 className="text-xl font-bold leading-tight">{title}</h2>
          <p className="truncate text-sm text-muted-foreground">{hint}</p>
        </div>
      </div>
      {children}
    </div>
  )
}

function NoCompany() {
  return <Card><CardContent className="py-10 text-center text-muted-foreground">Нет доступных организаций</CardContent></Card>
}

/** Состояние: каналы связи платформы + витрина прикладных подключений. */
export function ConnectionsPage() {
  return (
    <Page icon={Cable} title="Состояние"
      hint="Каналы связи пространства и источники данных приложений — что живо и когда приносили данные">
      <Connections />
    </Page>
  )
}

export function NotificationsPage() {
  const { companyId, canManage } = useCanManage()
  return (
    <Page icon={Bell} title="Оповещения" hint="О чём сообщать и куда — в чат организации или на почту">
      {companyId ? <Notifications companyId={companyId} canManage={canManage} /> : <NoCompany />}
    </Page>
  )
}

export function SpaceAppsPage() {
  const { companyId, canManage, isSuperadmin } = useCanManage()
  return (
    <Page icon={Blocks} title="Приложения и модули"
      hint="Что подключено пространству: продукты, их модули и разделы">
      {companyId
        ? <CompanyApps companyId={companyId} canManage={canManage} isSuperadmin={isSuperadmin} />
        : <NoCompany />}
    </Page>
  )
}
