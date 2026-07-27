/**
 * Дерево прав компании: продукты (из реестра) + их разделы (из карты меню).
 *
 * Модули приходят с сервера только у тех продуктов, что заведены в реестре с составом
 * (Учёт, Управление). У продуктов разреза сервер знает лишь сам продукт, а состав —
 * это пункты меню, поэтому берётся из `config/productAccess.ts`: те же массивы, что
 * рисуют интерфейс. Группы нужны, чтобы 25 пунктов «Магазина» читались списком.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isApiEnabled } from '@/services/apiClient'
import { getAccessCatalog } from '@/services/registryService'
import { productModules } from '@/config/productAccess'
import { ACCESS_MODULES } from '@/config/accessModules'

export interface AccessGroup { name: string; modules: { key: string; code: string; name: string }[] }
export interface AccessApp { app: string; name: string; groups: AccessGroup[]; count: number }

export function useAccessTree(companyId: string) {
  const q = useQuery({
    queryKey: ['access-catalog', companyId],
    queryFn: () => getAccessCatalog(companyId),
    enabled: isApiEnabled() && !!companyId,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const tree = useMemo<AccessApp[]>(() => {
    const catalog = q.data ?? (q.isLoading ? [] : [{
      // Офлайн-контур: реестр недоступен — остаются модули Учёта (legacy-каталог).
      app: 'ledger', name: 'Учёт', icon: 'book-open',
      modules: ACCESS_MODULES.map((m) => ({ key: `ledger:${m.key}`, code: m.key, name: m.label })),
    }])
    return catalog.map((app) => {
      const local = productModules(app.app)
      const groups: AccessGroup[] = []
      const push = (group: string, mod: { key: string; code: string; name: string }) => {
        const last = groups[groups.length - 1]
        if (last && last.name === group) last.modules.push(mod)
        else groups.push({ name: group, modules: [mod] })
      }
      if (local.length) {
        for (const m of local) push(m.group, { key: `${app.app}:${m.code}`, code: m.code, name: m.label })
      } else {
        for (const m of app.modules) push('Разделы', m)
      }
      return { app: app.app, name: app.name, groups, count: groups.reduce((s, g) => s + g.modules.length, 0) }
    })
  }, [q.data, q.isLoading])
  return { tree, isLoading: q.isLoading }
}
