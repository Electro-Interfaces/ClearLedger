/**
 * Доступ к контексту приложения «Управление»: какая компания открыта и куда вести
 * человека, если раздел не указан или закрыт правами.
 *
 * Живёт отдельно от `AdminLayout`, потому что shell отдаёт контекст через Outlet,
 * а пользуются им экраны разделов — общий файл избавляет от кольцевого импорта.
 */
import { useOutletContext } from 'react-router-dom'
import { companySections, ecosystemSections, findSection, type AdminScope } from '@/config/adminNav'
import { useAuth } from '@/contexts/AuthContext'
import { useCompany } from '@/contexts/CompanyContext'
import type { OrgProfile } from '@/services/userService'

export interface AdminOutletContext {
  company?: OrgProfile
  companies: OrgProfile[]
  /** Может ли текущий пользователь администрировать открытую компанию. */
  canManage: boolean
  selectCompany: (id: string) => void
}

export function useAdminCompany() {
  return useOutletContext<AdminOutletContext>()
}

/** Ключ последнего открытого раздела — пишет shell, читает редирект `/admin`. */
export const LAST_SECTION_KEY = 'cl-admin-last-section'

/** Первый раздел, доступный этому человеку: куда вести с `/admin` и из закрытого раздела. */
export function useAdminHome(): string {
  const { user } = useAuth()
  const { canModule } = useCompany()
  if (user?.is_superadmin) return `/admin/eco/${ecosystemSections[0].code}`
  const first = companySections.find((s) => canModule('admin', s.code))
  return first ? `/admin/company/${first.code}` : '/'
}

/**
 * Куда вести с `/admin`: в последний открытый раздел, если он ещё существует.
 * Права не проверяем здесь — экран раздела сам уводит на доступный, если запрещено.
 */
export function useAdminEntry(): string {
  const home = useAdminHome()
  try {
    const last = localStorage.getItem(LAST_SECTION_KEY)
    const [, , scope, code] = (last ?? '').split('/')
    if (last?.startsWith('/admin/') && findSection(scope as AdminScope, code)) return last
  } catch { /* ignore */ }
  return home
}
