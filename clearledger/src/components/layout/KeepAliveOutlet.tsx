/**
 * Keep-alive Outlet: ЗАКРЕПЛЁННЫЕ вкладки остаются смонтированными (скрыты
 * `display:none`) — возврат к ним без переформатирования. Текущая (не
 * закреплённая) страница показывается живьём и размонтируется при уходе.
 *
 * Ключ keep-alive инстанса — pathname (одна страница на pathname): смена
 * mode/sub рабочего стола идёт через search-параметры и НЕ размонтирует
 * инстанс. Идентификатор закладки при этом — полный URL (см. TabsContext).
 *
 * Скрытые вкладки изолированы снимком роутер-контекста (`UNSAFE_RouteContext`
 * + `UNSAFE_LocationContext`), чтобы их `useParams`/`useSearchParams` не
 * подхватывали URL активной вкладки. Только десктоп.
 */
import { useContext, useEffect, useState, type ReactNode } from 'react'
import {
  useOutlet, useLocation,
  UNSAFE_RouteContext as RouteContext,
  UNSAFE_LocationContext as LocationContext,
} from 'react-router-dom'
import { useTabs } from '@/contexts/TabsContext'
import { resolveTab } from '@/config/tabRegistry'
import { cn } from '@/lib/utils'

type RouteCtxValue = React.ContextType<typeof RouteContext>
type LocationCtxValue = React.ContextType<typeof LocationContext>

interface Entry {
  outlet: ReactNode
  routeCtx: RouteCtxValue
  locationCtx: LocationCtxValue
  workspace: boolean
}

export function KeepAliveOutlet() {
  const outlet = useOutlet()
  const location = useLocation()
  const routeCtx = useContext(RouteContext)
  const locationCtx = useContext(LocationContext)
  const { tabs } = useTabs()

  const pathname = location.pathname
  const resolved = resolveTab(pathname)

  // Снимки смонтированных страниц по pathname (активная рендерится живьём).
  const [mounted, setMounted] = useState<Map<string, Entry>>(() => new Map())

  // Pathname'ы закреплённых вкладок — их держим живыми.
  const pinnedPaths = tabs.map((t) => t.pathname)
  const keepKey = pinnedPaths.join('|')

  // Снимок делаем один раз на активацию pathname (замыкание держит outlet/контексты этого рендера).
  useEffect(() => {
    if (!resolved) return
    setMounted((prev) => {
      const next = new Map(prev)
      next.set(pathname, { outlet, routeCtx, locationCtx, workspace: resolved.workspace })
      return next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])

  // Держим живыми только закреплённые + текущую; остальные размонтируем.
  useEffect(() => {
    const keep = new Set(keepKey ? keepKey.split('|') : [])
    keep.add(pathname)
    setMounted((prev) => {
      let changed = false
      const next = new Map(prev)
      for (const k of [...next.keys()]) {
        if (!keep.has(k)) { next.delete(k); changed = true }
      }
      return changed ? next : prev
    })
  }, [keepKey, pathname])

  // Нетабуемый путь (напр. 404) — рендерим напрямую, без keep-alive.
  if (!resolved) {
    return <div className="flex-1 min-h-0 overflow-y-auto px-4 md:px-6 pt-4 pb-12">{outlet}</div>
  }

  // Рендерим: закреплённые (смонтированные) + текущую; активная — живьём.
  const keepSet = new Set(pinnedPaths)
  const keys = [...mounted.keys()].filter((k) => keepSet.has(k))
  if (!keys.includes(pathname)) keys.push(pathname)

  return (
    <div className="relative flex-1 min-h-0">
      {keys.map((k) => {
        const active = k === pathname
        const entry: Entry = active
          ? { outlet, routeCtx, locationCtx, workspace: resolved.workspace }
          : mounted.get(k)!
        return (
          <div key={k} className={cn('absolute inset-0', active ? 'block' : 'hidden')} aria-hidden={!active}>
            <div className={entry.workspace
              ? 'h-full min-h-0 overflow-hidden'
              : 'h-full min-h-0 overflow-y-auto px-4 md:px-6 pt-4 pb-12'}>
              <LocationContext.Provider value={entry.locationCtx}>
                <RouteContext.Provider value={entry.routeCtx}>
                  {entry.outlet}
                </RouteContext.Provider>
              </LocationContext.Provider>
            </div>
          </div>
        )
      })}
    </div>
  )
}
