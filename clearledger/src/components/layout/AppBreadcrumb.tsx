import { Link, useLocation } from 'react-router-dom'
import {
  Breadcrumb, BreadcrumbList, BreadcrumbItem,
  BreadcrumbLink, BreadcrumbPage, BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'

const ROUTE_LABELS: Record<string, string> = {
  'shifts': 'Сменные отчёты',
  'receipts': 'Поступления',
  'settings': 'Настройки',
  'data': 'Данные',
}

export function AppBreadcrumb() {
  const location = useLocation()
  const segments = location.pathname.replace(/^\//, '').split('/').filter(Boolean)

  if (segments.length <= 1 && segments[0] !== 'settings') return null

  const crumbs: Array<{ label: string; path: string }> = []

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const path = '/' + segments.slice(0, i + 1).join('/')

    if (i === 0) {
      crumbs.push({ label: ROUTE_LABELS[seg] ?? seg, path })
    } else {
      crumbs.push({ label: seg, path })
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
          <span key={crumb.path} className="contents">
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              {idx === crumbs.length - 1 ? (
                <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
              ) : (
                <BreadcrumbLink asChild>
                  <Link to={crumb.path}>{crumb.label}</Link>
                </BreadcrumbLink>
              )}
            </BreadcrumbItem>
          </span>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
