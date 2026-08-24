import { useMemo, useState } from 'react'
import { BarChart3, Boxes, CalendarDays, MapPin, RadioTower, ShieldCheck, ShoppingBasket, ShoppingCart } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { StoreView } from '@/components/workspace/StorePanel'
import { STORE_DEMO_STATIONS } from '@/services/storeDemoService'

const END_DATE = '2026-08-24'

const VIEWS = [
  { key: 'overview', label: 'Обзор', icon: BarChart3, hint: 'Деньги, поток и структура' },
  { key: 'sales', label: 'Продажи', icon: ShoppingCart, hint: 'Группировки и товары' },
  { key: 'stock', label: 'Остатки', icon: Boxes, hint: 'Полки, стоимость и минусы' },
  { key: 'stations', label: 'Станции', icon: RadioTower, hint: 'Связь и обмен с центром' },
] as const

const PERIODS = [
  { days: 7, label: '7 дней' },
  { days: 14, label: '14 дней' },
  { days: 30, label: '30 дней' },
] as const

function startDate(days: number): string {
  const date = new Date(`${END_DATE}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - days + 1)
  return date.toISOString().slice(0, 10)
}

export function StoreDemoPage() {
  const [view, setView] = useState<(typeof VIEWS)[number]['key']>('overview')
  const [periodDays, setPeriodDays] = useState(14)
  const [stations, setStations] = useState<string[]>(STORE_DEMO_STATIONS.map((station) => station.id))
  const dateFrom = useMemo(() => startDate(periodDays), [periodDays])
  const allSelected = stations.length === STORE_DEMO_STATIONS.length

  const toggleStation = (id: string, checked: boolean) => {
    setStations((current) => {
      if (checked) return current.includes(id) ? current : [...current, id]
      return current.length === 1 ? current : current.filter((station) => station !== id)
    })
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <header className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4 py-3 md:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-md shadow-primary/20">
            <ShoppingBasket aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-base font-semibold">Магазин</h1>
              <Badge variant="destructive">Демо</Badge>
            </div>
            <p className="truncate text-xs text-muted-foreground">Сопутка и общепит сети АЗС</p>
          </div>
        </div>
        <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
          <ShieldCheck aria-hidden="true" />
          Только просмотр
        </div>
      </header>

      <div role="status" className="shrink-0 border-b border-destructive/25 bg-destructive/10 px-4 py-2.5 text-sm md:px-6">
        <div className="mx-auto flex max-w-[1680px] items-start gap-2">
          <ShieldCheck className="mt-0.5 shrink-0 text-destructive" aria-hidden="true" />
          <p>
            <strong>Демонстрационные данные.</strong>{' '}
            Все цифры синтетические, изменяющие операции и выгрузки отключены. Демо не обращается к данным реальных станций.
          </p>
        </div>
      </div>

      <section aria-label="Контур демонстрации" className="shrink-0 border-b border-border bg-card px-4 py-3 md:px-6">
        <div className="mx-auto flex max-w-[1680px] flex-wrap items-center gap-x-6 gap-y-3">
          <fieldset className="flex min-w-0 flex-wrap items-center gap-3">
            <legend className="sr-only">Станции</legend>
            <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <MapPin aria-hidden="true" /> Станции
            </span>
            {STORE_DEMO_STATIONS.map((station) => {
              const checked = stations.includes(station.id)
              return (
                <label key={station.id} className="flex cursor-pointer items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted/50">
                  <Checkbox checked={checked} onCheckedChange={(value) => toggleStation(station.id, value === true)} />
                  <span className="font-medium">{station.name}</span>
                  <span className="hidden text-muted-foreground xl:inline">{station.city}</span>
                </label>
              )
            })}
            {!allSelected && (
              <Button variant="ghost" size="xs" onClick={() => setStations(STORE_DEMO_STATIONS.map((station) => station.id))}>
                Вся сеть
              </Button>
            )}
          </fieldset>

          <div className="flex items-center gap-2 md:ml-auto">
            <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <CalendarDays aria-hidden="true" /> Период
            </span>
            {PERIODS.map((period) => (
              <Button
                key={period.days}
                size="xs"
                variant={periodDays === period.days ? 'default' : 'outline'}
                onClick={() => setPeriodDays(period.days)}
              >
                {period.label}
              </Button>
            ))}
          </div>
        </div>
      </section>

      <main className="mx-auto flex min-h-0 w-full max-w-[1680px] flex-1 flex-col lg:flex-row">
        <nav aria-label="Разделы магазина" className="shrink-0 border-b border-border bg-card p-2 lg:w-60 lg:border-r lg:border-b-0 lg:p-3">
          <div className="flex gap-1 overflow-x-auto lg:flex-col">
            {VIEWS.map((item) => {
              const Icon = item.icon
              const selected = view === item.key
              return (
                <Button
                  key={item.key}
                  variant={selected ? 'secondary' : 'ghost'}
                  className="h-auto min-w-max justify-start px-3 py-2.5 lg:w-full"
                  aria-current={selected ? 'page' : undefined}
                  onClick={() => setView(item.key)}
                >
                  <Icon data-icon="inline-start" />
                  <span className="text-left">
                    <span className="block text-sm">{item.label}</span>
                    <span className="hidden text-[11px] font-normal text-muted-foreground lg:block">{item.hint}</span>
                  </span>
                </Button>
              )
            })}
          </div>
          <div className="mt-4 hidden rounded-xl border border-border bg-muted/30 p-3 text-xs leading-relaxed text-muted-foreground lg:block">
            Выбрано: {stations.length} из {STORE_DEMO_STATIONS.length} АЗС<br />
            Период: {dateFrom} — {END_DATE}
          </div>
        </nav>

        <section className="min-h-0 min-w-0 flex-1 overflow-hidden" aria-live="polite">
          <StoreView
            sub={view}
            companyId="demo-shop"
            dateFrom={dateFrom}
            dateTo={END_DATE}
            stations={stations}
            demo
          />
        </section>
      </main>
    </div>
  )
}
