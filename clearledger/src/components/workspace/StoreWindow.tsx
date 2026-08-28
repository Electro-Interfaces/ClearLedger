/**
 * Пункт «Магазина» поверх текущего экрана.
 *
 * Раньше клик по строке или отчёту уводил в другой пункт с заменой истории:
 * человек терял отбор, прокрутку и раскрытые панели, а «Назад» возвращало не
 * туда — вообще из «Магазина». Теперь пункт открывается окном поверх того, что
 * человек уже настроил, и закрытие возвращает ровно на прежнее место.
 *
 * Окно живёт параметром адреса (`?win=`), а не состоянием: тогда «Назад»,
 * Esc, F5 и пересылаемая ссылка достаются от роутера и Radix бесплатно.
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useFilters } from '@/contexts/FilterContext'
import { useCompany } from '@/contexts/CompanyContext'
import { useWorkspace } from '@/contexts/WorkspaceContext'
import { useLocations } from '@/hooks/useLocations'
import { scopeStationCodes } from '@/services/locationService'
import { getStoreView, storeCanonKey, storeModeForKey, STORE_KEYS } from '@/config/storeCatalog'
import { StoreView } from './StorePanel'

/**
 * Пункты, которые окном не открываются: рабочее место АЗС держит собственную
 * сессию к агенту станции, и вторая копия в окне завела бы вторую — с чужим
 * авторством действий.
 */
const ТОЛЬКО_ЭКРАНОМ = new Set(['station_console'])

/** Открыть пункт окном: параметр адреса + запись в историю (в отличие от смены пункта). */
export function useStoreWindow() {
  const [, setSearchParams] = useSearchParams()
  return useCallback((key: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('win', key)
      return next
    }, { replace: false })
  }, [setSearchParams])
}

/** Можно ли показать пункт окном (иначе вызывающий делает обычный переход). */
export function окномМожно(key: string): boolean {
  const канон = storeCanonKey(key)
  return STORE_KEYS.includes(канон) && !ТОЛЬКО_ЭКРАНОМ.has(канон)
}

export function StoreWindow() {
  const [searchParams, setSearchParams] = useSearchParams()
  const win = searchParams.get('win') ?? ''
  const { period, locationIds, regionIds } = useFilters()
  const { companyId } = useCompany()
  const { setCoreMode } = useWorkspace()
  const locations = useLocations()
  const stations = useMemo(
    () => scopeStationCodes(locations, locationIds, regionIds).map(String),
    [locations, locationIds, regionIds],
  )

  const close = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.delete('win')
      return next
    }, { replace: true })
  }, [setSearchParams])

  const view = getStoreView(win)
  // Неизвестный ключ адрес не чинит: окно просто не открывается. Починка
  // подменяла бы адрес под собой и путала «Назад».
  if (!win || !view || !окномМожно(win)) return null

  return (
    <Dialog open onOpenChange={(o) => { if (!o) close() }}>
      {/* Позиция считается, а не сдвигается трансформом: любой transform делает
          окно точкой отсчёта для вложенных карточек с `fixed`, и карточка
          товара, открытая внутри, легла бы по краю окна вместо экрана. */}
      <DialogContent
        className="max-w-none w-[min(1500px,96vw)] h-[92vh] top-[4vh] left-[calc((100vw-min(1500px,96vw))/2)]
          translate-none p-0 gap-0 grid-rows-[auto_1fr] sm:max-w-none
          max-sm:w-screen max-sm:h-[100dvh] max-sm:top-0 max-sm:left-0 max-sm:rounded-none"
        aria-describedby={undefined}
      >
        <DialogHeader className="flex-row items-center justify-between gap-4 border-b px-5 py-3 space-y-0">
          <div className="min-w-0">
            <DialogTitle className="truncate pr-6">{view.title}</DialogTitle>
            {view.subtitle ? (
              <DialogDescription className="truncate text-[11px]">{view.subtitle}</DialogDescription>
            ) : null}
          </div>
          {/* Иногда с пунктом работают долго — тогда окно мешает, и нужен выход
              на целый экран, а не «закрыть и найти пункт заново». */}
          <Button
            variant="ghost" size="sm" className="shrink-0 text-xs text-muted-foreground"
            onClick={() => { close(); setCoreMode(storeModeForKey(win), win) }}
          >
            Открыть экраном
          </Button>
        </DialogHeader>
        <div className="min-h-0 overflow-hidden">
          <StoreView sub={win} companyId={companyId} dateFrom={period.from} dateTo={period.to} stations={stations} />
        </div>
      </DialogContent>
    </Dialog>
  )
}
