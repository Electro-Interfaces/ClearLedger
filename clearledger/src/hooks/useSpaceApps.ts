/**
 * Каталог продуктов пространства — один на всех, кто его показывает.
 *
 * Показывают его двое: рабочий стол (`EcosystemHomePage`, плитки или список) и меню
 * приложений в левом рельсе. Запрос один и тот же ключом `['sso-apps', companyId]`,
 * поэтому второе место берёт готовый ответ из кэша, а не ходит на сервер снова.
 *
 * RBAC-гейт здесь же: `allowed_apps` — коды, доступные роли в компании (null — без
 * ограничений, напр. суперадмин). Бэкенд уже отфильтровал список, здесь отсекаются
 * внутренние плитки, которые он отдаёт всем.
 */
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { isApiEnabled } from '@/services/apiClient'
import { listSsoApps, type SsoApp } from '@/services/ssoService'
import { launcherSections, type LauncherSection } from '@/config/spaceLauncher'

export function useSpaceApps(): {
  apps: SsoApp[]
  sections: LauncherSection[]
  isLoading: boolean
} {
  const { companyId } = useCompany()
  const q = useQuery({
    queryKey: ['sso-apps', companyId],
    queryFn: () => listSsoApps(companyId),
    enabled: isApiEnabled(),
    staleTime: 5 * 60_000,
  })
  const allowed = q.data?.allowed_apps ?? null
  const apps: SsoApp[] = (q.data?.apps ?? [])
    .filter((a) => allowed === null || allowed.includes(a.code))
  return { apps, sections: launcherSections(apps), isLoading: q.isLoading }
}
