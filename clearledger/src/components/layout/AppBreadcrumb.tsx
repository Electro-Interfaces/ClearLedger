/**
 * AppBreadcrumb — автоматические breadcrumbs на основе текущего маршрута.
 * Показывается для вложенных маршрутов (глубина > 1).
 */

import { Link, useLocation } from 'react-router-dom'
import {
  Breadcrumb, BreadcrumbList, BreadcrumbItem,
  BreadcrumbLink, BreadcrumbPage, BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { useCompany } from '@/contexts/CompanyContext'
import { useEntry } from '@/hooks/useEntries'
import { useConnector } from '@/hooks/useConnectors'

const ROUTE_LABELS: Record<string, string> = {
  '': 'Дашборд',
  'inbox': 'Входящие',
  'input': 'Приём',
  'data': 'Данные',
  'connectors': 'Коннекторы',
  'search': 'Поиск',
  'settings': 'Настройки',
}

export function AppBreadcrumb() {
  const location = useLocation()
  const { effectiveCategories } = useCompany()

  // Разбираем путь
  const segments = location.pathname.replace(/^\//, '').split('/').filter(Boolean)

  // Не показываем breadcrumbs для корневых маршрутов
  if (segments.length <= 1) return null

  const crumbs: Array<{ label: string; path: string }> = []

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const path = '/' + segments.slice(0, i + 1).join('/')

    // Маппинг сегментов в лейблы
    if (i === 0) {
      crumbs.push({ label: ROUTE_LABELS[seg] ?? seg, path })
    } else if (segments[0] === 'data' && i === 1) {
      // Категория данных
      const cat = effectiveCategories.find((c) => c.id === seg)
      crumbs.push({ label: cat?.label ?? seg, path })
    } else if (segments[0] === 'settings' && i === 1) {
      crumbs.push({ label: seg === 'companies' ? 'Компании' : seg, path })
    } else {
      // Для ID-сегментов используем специальную метку (будет заменена ниже)
      crumbs.push({ label: '...', path })
    }
  }

  return (
    <Breadcrumb className="mb-4">
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink asChild>
            <Link to="/">Главная</Link>
          </BreadcrumbLink>
        </BreadcrumbItem>
        {crumbs.map((crumb, idx) => (
          <BreadcrumbItemResolved
            key={crumb.path}
            crumb={crumb}
            isLast={idx === crumbs.length - 1}
            segments={segments}
            index={idx}
          />
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  )
}

function BreadcrumbItemResolved({
  crumb,
  isLast,
  segments,
  index,
}: {
  crumb: { label: string; path: string }
  isLast: boolean
  segments: string[]
  index: number
}) {
  // Для последнего сегмента-ID пытаемся подгрузить название
  const isEntryId = segments[0] === 'data' && index === 2
  const isConnectorId = segments[0] === 'connectors' && index === 1
  const isInboxId = segments[0] === 'inbox' && index === 1

  const entryId = (isEntryId || isInboxId) ? segments[index] : ''
  const connectorId = isConnectorId ? segments[index] : ''

  const { data: entry } = useEntry(entryId)
  const { data: connector } = useConnector(connectorId)

  let label = crumb.label
  if (entry) label = entry.title.length > 40 ? entry.title.slice(0, 40) + '...' : entry.title
  else if (connector) label = connector.name
  else if (crumb.label === '...') label = segments[index]?.slice(0, 8) ?? '...'

  return (
    <>
      <BreadcrumbSeparator />
      <BreadcrumbItem>
        {isLast ? (
          <BreadcrumbPage>{label}</BreadcrumbPage>
        ) : (
          <BreadcrumbLink asChild>
            <Link to={crumb.path}>{label}</Link>
          </BreadcrumbLink>
        )}
      </BreadcrumbItem>
    </>
  )
}
