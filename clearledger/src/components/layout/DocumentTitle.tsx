/**
 * Заголовок вкладки браузера = где человек находится.
 *
 * Продукты открываются каждый в своей вкладке, а `<title>` был статичным («Ledger») —
 * вкладки получались неразличимы: три одинаковых ярлыка без подсказки, где что.
 * Теперь вкладка называет продукт и компанию: «Эксплуатация · РусГидро».
 */
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { ECOSYSTEM_BRAND } from '@/config/brand'
import { useCompany } from '@/contexts/CompanyContext'
import { coreAppTitle, isCarvedProfile, productForPath, productLabel } from '@/config/spaceProducts'

function screenName(pathname: string, profileId: string | null | undefined): string {
  if (pathname === '/') return 'Рабочее пространство'
  if (pathname.endsWith('/demo/shop')) return 'Магазин — демо'
  const product = isCarvedProfile(profileId) ? productForPath(pathname) : null
  if (product) return productLabel(product, profileId)
  // Приложения Ядра («Заявки», «Инфо», «Данные», «Пульс», «Чаты», «Управление»)
  // называет общий словарь: вручную здесь перечислялись только три, и вкладки
  // «Заявок» и «Инфо» приходили подписанными «Учёт» — как чужой экран.
  return coreAppTitle(pathname) ?? 'Учёт'
}

export function DocumentTitle() {
  const { pathname } = useLocation()
  const { company } = useCompany()

  useEffect(() => {
    const name = screenName(pathname, company.profileId)
    // Компания в заголовке — чтобы вкладки не путались между пространствами, когда
    // человек работает сразу в нескольких (холдинг, инженер платформы).
    document.title = `${name} · ${company.name || ECOSYSTEM_BRAND}`
  }, [pathname, company.profileId, company.name])

  return null
}
