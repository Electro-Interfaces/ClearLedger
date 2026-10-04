/**
 * Активный раздел страницы пространства («Объекты», «Загрузка», «Контрагенты»).
 *
 * Нужен и меню (`SpacePageLayout`), и самой странице: меню раздел ставит,
 * страница по нему решает, что показать. Живёт в адресе (`?sub=`), как у
 * разделов продукта, — ссылку на конкретный раздел можно дать, и она откроется
 * там же. Неизвестный ключ молча приводится к первому пункту: ссылка на снятый
 * раздел не должна показывать пустоту.
 */
import { useLocation, useSearchParams } from 'react-router-dom'
import { useCompany } from '@/contexts/CompanyContext'
import { spacePageItems, type SpacePageItem } from '@/config/spacePageMenus'

export function useSpacePageSub(): [string, (key: string) => void, SpacePageItem[]] {
  const { pathname } = useLocation()
  const { company } = useCompany()
  const [params, setParams] = useSearchParams()
  const items = spacePageItems(pathname, company?.profileId === 'energy')
  const fromUrl = params.get('sub')
  const active = fromUrl && items.some((i) => i.key === fromUrl)
    ? fromUrl
    : (items[0]?.key ?? '')
  const set = (key: string) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    next.set('sub', key)
    return next
  }, { replace: true })
  return [active, set, items]
}
