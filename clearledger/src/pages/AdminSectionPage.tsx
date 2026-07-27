/**
 * Экран раздела «Управления»: по адресу `/admin/<scope>/<code>` показывает нужный
 * раздел. Соответствие «код → экран» держится здесь одной картой, состав и порядок
 * разделов — в `config/adminNav` (там же их видит левое меню).
 *
 * Права: уровень «Экосистема» — суперадмину-владельцу контейнера, уровень
 * «Компания» — по модулю роли (`canModule('admin', code)`). Прямой заход на
 * недоступный раздел уводит на разрешённый, а не показывает пустой экран.
 */
import type { ComponentType } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { InvitationsCard, MembersCard, RolesAccessTab } from '@/components/admin/CompanyTeam'
import { AuditLog } from '@/components/admin/AuditLog'
import { Connections } from '@/components/admin/Connections'
import { Notifications } from '@/components/admin/Notifications'
import { CompanyApps } from '@/components/admin/CompanyApps'
import { CompanyProfileCard } from '@/components/admin/CompanyProfile'
import { CoreOverview } from '@/components/admin/CoreOverview'
import { CoreSettings } from '@/components/admin/CoreSettings'
import { EcosystemCompanies } from '@/components/admin/EcosystemCompanies'
import { SpaceMap } from '@/components/admin/SpaceMap'
import { SpaceObjects } from '@/components/admin/SpaceObjects'
import { SpaceRefs } from '@/components/admin/SpaceRefs'
import { useAdminCompany, useAdminEntry, useAdminHome } from '@/hooks/useAdminSpace'
import { companySections } from '@/config/adminNav'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'

/** `/admin` без раздела — в последний открытый (или первый доступный). */
export function AdminHomeRedirect() {
  return <Navigate to={useAdminEntry()} replace />
}

function Empty({ text }: { text: string }) {
  return <Card><CardContent className="py-10 text-center text-muted-foreground">{text}</CardContent></Card>
}

// ─── Уровень «Экосистема» ────────────────────────────────────────────────────
// «Каталог», «Пользователи» и «Аудит» отсюда убраны как дубли разделов организации:
// каталог продуктов стал секцией «Приложений», состав людей живёт в «Сотрудниках» и
// «Компаниях» (а сводно — в «Карте»), журнал переключает охват сам.
const ECO_SCREENS: Record<string, ComponentType> = {
  overview: CoreOverview,
  companies: EcosystemCompanies,
  settings: CoreSettings,
}

// ─── Уровень «Компания» ──────────────────────────────────────────────────────
function CompanyScreen({ code }: { code: string }) {
  const { user } = useAuth()
  const { company, canManage } = useAdminCompany()

  if (!company) return <Empty text="Нет доступных компаний" />

  switch (code) {
    case 'members': return <MembersCard companyId={company.id} canManage={canManage} selfId={user!.id} />
    // Тот же состав пространства, другая сторона: люди компаний-партнёров, сгруппированные
    // по их компании. Один компонент — чтобы роли, доступ и скоуп объектов не разъезжались
    // между разделами.
    case 'partners': return <MembersCard companyId={company.id} canManage={canManage} selfId={user!.id} party="external" />
    case 'roles': return <RolesAccessTab companyId={company.id} canManage={canManage} />
    // Каталог платформы — второй секцией этого же раздела, владельцу контейнера.
    case 'apps': return <CompanyApps companyId={company.id} canManage={canManage}
      isSuperadmin={!!user?.is_superadmin} />
    case 'objects': return <SpaceObjects companyId={company.id} canManage={canManage} />
    case 'refs': return <SpaceRefs companyId={company.id} canManage={canManage} />
    case 'notify': return <Notifications companyId={company.id} canManage={canManage} />
    // Витрина: состояние каналов платформы и подключений приложений; настройка — у владельца.
    case 'connections': return <Connections />
    // Одна карта на оба охвата — переключатель внутри, как в журнале.
    case 'map': return <SpaceMap companyId={company.id} isSuperadmin={!!user?.is_superadmin} />
    case 'profile': return <CompanyProfileCard company={company} canEdit={canManage} />
    // Приглашения и журнал — действия администратора организации, не наблюдателя.
    case 'invites': return canManage ? <InvitationsCard companyId={company.id} /> : <Empty text="Раздел доступен администратору организации" />
    // Один журнал на оба охвата: у суперадмина внутри переключатель «организация /
    // весь контейнер», у админа организации — только её события.
    case 'audit': return canManage
      ? <AuditLog companyId={company.id} isSuperadmin={!!user?.is_superadmin} />
      : <Empty text="Раздел доступен администратору организации" />
    default: return <Empty text="Раздел не найден" />
  }
}

export function AdminSectionPage() {
  const { scope, section } = useParams()
  const { user } = useAuth()
  const { canModule } = useCompany()
  const home = useAdminHome()

  if (scope === 'eco') {
    if (!user?.is_superadmin) return <Navigate to={home} replace />
    const Screen = section ? ECO_SCREENS[section] : undefined
    return Screen ? <Screen /> : <Navigate to={home} replace />
  }

  if (!section || !companySections.some((s) => s.code === section)) return <Navigate to={home} replace />
  if (!canModule('admin', section)) return <Navigate to={home} replace />
  return <CompanyScreen code={section} />
}

export default AdminSectionPage
