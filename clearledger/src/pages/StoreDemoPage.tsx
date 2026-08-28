import { useMemo, useState } from 'react'
import {
  Bookmark, CalendarDays, ChevronDown, CircleHelp, Fuel, Gauge, Grid2X2,
  Headphones, Lightbulb, ListChecks, MapPin, Menu, MessageCircle, MonitorSmartphone,
  PanelLeftClose, Pin, RadioTower, RefreshCw, SlidersHorizontal,
  UserRound, Video,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { StoreView } from '@/components/workspace/StorePanel'
import { STORE_SECTIONS, STORE_VIEWS, type StoreMode } from '@/config/storeCatalog'
import { StoreDemoRichView } from '@/demo/StoreDemoRichView'
import { cn } from '@/lib/utils'
import { STORE_DEMO_STATIONS } from '@/services/storeDemoService'

const END_DATE = '2026-08-24'

const PERIODS = [
  { days: 7, label: '7 дней' },
  { days: 14, label: '14 дней' },
  { days: 24, label: '1–24 августа' },
] as const

const DEMO_VIEWS = new Set(['overview', 'sales', 'stock', 'stations'])

const DEFAULT_VIEW: Partial<Record<StoreMode, string>> = {
  store: 'overview',
  store_stock: 'stock',
  store_network: 'station_console',
}

const DEMO_CONSOLE_STATIONS = [
  { ...STORE_DEMO_STATIONS[0], state: 'онлайн', version: '1.101.5', queue: 0 },
  { ...STORE_DEMO_STATIONS[1], state: 'онлайн', version: '1.101.5', queue: 0 },
  { ...STORE_DEMO_STATIONS[2], state: 'нет связи', version: '1.100.9', queue: 4 },
]

function startDate(days: number): string {
  const date = new Date(`${END_DATE}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - days + 1)
  return date.toISOString().slice(0, 10)
}

function periodLabel(dateFrom: string): string {
  const from = Number(dateFrom.slice(8, 10))
  return `${from} авг – 24 авг 2026`
}

function DemoStationConsole({ onOpen }: { onOpen: (stationId: string) => void }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl space-y-6 p-6">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <MonitorSmartphone className="h-4 w-4 text-primary" aria-hidden="true" />
            Рабочее место АЗС
          </h2>
          <p className="mt-1 max-w-4xl text-sm leading-relaxed text-muted-foreground">
            Выберите станцию, чтобы работать на ней из центра: приёмка, инвентаризация,
            остатки, карточки. Открывается сам агент станции, а не копия его экранов, —
            всё введённое сразу становится учётом АЗС и помечается вашим именем.
            В демо кнопка открывает данные выбранной станции в этой вкладке.
          </p>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          {DEMO_CONSOLE_STATIONS.map((station) => {
            const online = station.state === 'онлайн'
            return (
              <div key={station.id} className={cn(
                'rounded-lg border p-4',
                online ? 'border-border' : 'border-dashed border-border',
              )}>
                <div className="flex flex-col items-stretch justify-between gap-3 sm:flex-row sm:items-start">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 font-medium">
                      <RadioTower className={cn('h-4 w-4', online ? 'text-emerald-500' : 'text-muted-foreground')} aria-hidden="true" />
                      {station.name}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {online
                        ? `на связи · агент ${station.version}`
                        : `${station.state} · в очереди ${station.queue} пакета`}
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground/75">
                      {station.city} · {station.address}
                    </div>
                  </div>
                  <Button size="sm" className="w-full sm:w-auto" disabled={!online} onClick={() => onOpen(station.id)}>
                    Работать
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function StoreDemoPage() {
  const [section, setSection] = useState<StoreMode>('store_network')
  const [view, setView] = useState('station_console')
  const [periodDays, setPeriodDays] = useState(24)
  const [stations, setStations] = useState<string[]>(STORE_DEMO_STATIONS.map((station) => station.id))
  const dateFrom = useMemo(() => startDate(periodDays), [periodDays])
  const sectionViews = useMemo(() => STORE_VIEWS.filter((item) => item.section === section), [section])

  function selectSection(mode: StoreMode) {
    const nextViews = STORE_VIEWS.filter((item) => item.section === mode)
    setSection(mode)
    setView(DEFAULT_VIEW[mode] ?? nextViews[0]?.key ?? 'overview')
  }

  function toggleStation(id: string, checked: boolean) {
    setStations((current) => {
      if (checked) return current.includes(id) ? current : [...current, id]
      return current.length === 1 ? current : current.filter((station) => station !== id)
    })
  }

  function openStation(stationId: string) {
    setStations([stationId])
    setSection('store')
    setView('overview')
  }

  return (
    <div className="dark flex h-dvh min-w-0 flex-col overflow-hidden bg-background text-foreground">
      <header className="grid h-[88px] shrink-0 grid-cols-[minmax(0,1fr)_auto] border-b border-border/50 bg-card xl:grid-cols-[280px_minmax(0,1fr)_54px]">
        <div className="hidden items-center gap-3 border-r border-border/40 px-7 xl:flex">
          <img src={`${import.meta.env.BASE_URL}pwa/gig/icon.svg`} alt="" className="size-12 rounded-xl" />
          <div className="min-w-0 leading-none">
            <div className="flex items-center gap-2">
              <span className="text-lg font-semibold">Магазин</span>
              <Badge variant="outline" className="px-1.5 py-0 text-[10px] text-muted-foreground">Демо</Badge>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">ГИГ</p>
          </div>
        </div>

        <div className="flex min-w-0 items-center gap-2 px-3 sm:px-5 xl:px-7">
          <Button variant="ghost" size="icon" className="xl:hidden" aria-label="Открыть меню">
            <Menu />
          </Button>
          <div className="flex items-center gap-2 xl:hidden">
            <img src={`${import.meta.env.BASE_URL}pwa/gig/icon.svg`} alt="" className="size-10 rounded-xl" />
            <span className="font-semibold">Магазин</span>
          </div>

          <div className="ml-auto hidden h-10 items-center gap-2 rounded-lg border border-border bg-background/20 px-3 text-sm font-medium md:flex">
            <span className="size-2 rounded-full bg-primary" aria-hidden="true" />
            ООО ГИГ (ГазИнвест)
            <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
          </div>

          <div className="hidden h-8 w-px bg-border/60 md:block" />
          <HeaderAction icon={Video} label="Конференция" hideOnMobile />
          <HeaderAction icon={MessageCircle} label="Чат" compact />
          <HeaderAction icon={ListChecks} label="Трек" compact />
          <HeaderAction icon={CircleHelp} label="Инфо" compact />

          <div className="ml-1 hidden items-center gap-3 pl-2 lg:flex">
            <Gauge className="size-4 text-muted-foreground" aria-hidden="true" />
            <Lightbulb className="size-4 text-muted-foreground" aria-hidden="true" />
            <div className="grid size-10 place-items-center rounded-xl border border-primary/50 bg-primary text-primary-foreground">
              <UserRound className="size-5" aria-hidden="true" />
            </div>
            <div className="hidden min-w-0 2xl:block">
              <div className="max-w-40 truncate text-xs font-semibold">Демо-пользователь</div>
              <div className="mt-1 text-[11px] text-muted-foreground">Только просмотр</div>
            </div>
          </div>
        </div>

        <div className="hidden border-l border-border/40 xl:block" />
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[280px] shrink-0 flex-col border-r border-border/40 bg-[#080d17] xl:flex">
          <div className="flex items-center gap-3 border-b border-border/60 px-7 py-6 text-sm font-semibold text-muted-foreground">
            <Grid2X2 className="size-4" aria-hidden="true" />
            Приложения
          </div>
          <nav aria-label="Разделы магазина" className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {STORE_SECTIONS.map((item, index) => {
              const Icon = item.icon
              const active = section === item.mode
              return (
                <div key={item.mode}>
                  {item.separatorBefore && index > 0 && <div className="mx-2 my-3 h-px bg-border/60" />}
                  <button
                    type="button"
                    onClick={() => selectSection(item.mode)}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'relative flex h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-semibold transition-colors',
                      active
                        ? 'bg-primary/15 text-foreground before:absolute before:-left-4 before:h-8 before:w-0.5 before:bg-primary'
                        : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground',
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden="true" />
                    {item.label}
                  </button>
                </div>
              )
            })}
            <button type="button" className="mt-1 flex h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-semibold text-muted-foreground hover:bg-accent/40 hover:text-foreground">
              <CircleHelp className="size-4" aria-hidden="true" />
              Помощь
            </button>
            <div className="mx-2 my-4 h-px bg-border/60" />
            <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/60">Пространство</div>
            <button type="button" className="flex h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-semibold text-muted-foreground hover:bg-accent/40 hover:text-foreground">
              <Grid2X2 className="size-4" aria-hidden="true" />
              Объекты
            </button>
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-card px-3">
            <div className="hidden items-center gap-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70 sm:flex">
              <Grid2X2 className="size-3.5" aria-hidden="true" />
              Экраны
            </div>
            <div className="hidden h-5 w-px bg-border sm:block" />
            <button type="button" className="rounded-md bg-background/50 px-3 py-1.5 text-xs font-medium">Рабочий стол</button>
            <Button variant="ghost" size="xs" className="ml-auto hidden sm:flex">
              <Pin data-icon="inline-start" />
              Закрепить экран
            </Button>
          </div>

          <div className="flex min-h-0 flex-1">
            <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-card lg:flex">
              <div className="flex justify-end px-3 py-3">
                <Button variant="ghost" size="icon-xs" aria-label="Свернуть меню подразделов">
                  <PanelLeftClose />
                </Button>
              </div>
              <nav aria-label="Подразделы" className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
                {sectionViews.map((item, index) => {
                  const previousGroup = sectionViews[index - 1]?.group
                  return (
                    <div key={item.key}>
                      {item.group && item.group !== previousGroup && (
                        <div className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                          {item.group}
                        </div>
                      )}
                      <button
                        type="button"
                        onClick={() => setView(item.key)}
                        aria-current={view === item.key ? 'page' : undefined}
                        className={cn(
                          'w-full rounded-md px-3 py-2 text-left text-[13px] transition-colors',
                          view === item.key
                            ? 'bg-primary/15 font-medium text-primary'
                            : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground',
                        )}
                      >
                        {item.label}
                      </button>
                    </div>
                  )
                })}
              </nav>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex shrink-0 items-center gap-3 overflow-x-auto border-b border-border bg-card px-3 py-3">
                <div className="hidden shrink-0 items-center gap-2 border-r border-border/60 pr-3 md:flex">
                  <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <SlidersHorizontal className="size-4" aria-hidden="true" />
                  </span>
                  <span className="leading-tight">
                    <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Фильтр</span>
                    <span className="block text-xs font-semibold">рабочей области</span>
                  </span>
                </div>

                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="outline" className="h-11 shrink-0">
                      <SlidersHorizontal data-icon="inline-start" />
                      Фильтры
                      <Badge variant="secondary" className="ml-1 px-1.5">{stations.length}</Badge>
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className="w-80">
                    <div className="font-medium">Станции демо-сети</div>
                    <p className="mt-1 text-xs text-muted-foreground">Выбор применяется ко всем рабочим экранам магазина.</p>
                    <div className="mt-4 space-y-2.5">
                      {STORE_DEMO_STATIONS.map((station) => (
                        <label key={station.id} className="flex cursor-pointer items-start gap-3 rounded-md p-2 hover:bg-accent/50">
                          <Checkbox checked={stations.includes(station.id)} onCheckedChange={(checked) => toggleStation(station.id, checked === true)} />
                          <span className="min-w-0">
                            <span className="block text-sm font-medium">{station.name}</span>
                            <span className="block truncate text-xs text-muted-foreground">{station.city} · {station.address}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                    {stations.length !== STORE_DEMO_STATIONS.length && (
                      <Button variant="ghost" size="sm" className="mt-3 w-full" onClick={() => setStations(STORE_DEMO_STATIONS.map((station) => station.id))}>
                        Выбрать всю сеть
                      </Button>
                    )}
                  </PopoverContent>
                </Popover>

                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="outline" className="h-11 shrink-0 justify-between border-primary/50 bg-primary/10 text-left text-primary hover:bg-primary/15">
                      <CalendarDays data-icon="inline-start" />
                      <span className="leading-tight">
                        <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Период</span>
                        <span className="block text-xs font-semibold">{periodLabel(dateFrom)}</span>
                      </span>
                      <ChevronDown className="size-4" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="start" className="w-56 p-2">
                    {PERIODS.map((period) => (
                      <button key={period.days} type="button" onClick={() => setPeriodDays(period.days)} className={cn(
                        'w-full rounded-md px-3 py-2 text-left text-sm hover:bg-accent',
                        periodDays === period.days && 'bg-primary/10 text-primary',
                      )}>
                        {period.label}
                      </button>
                    ))}
                  </PopoverContent>
                </Popover>

                <ToolbarValue icon={MapPin} label="Область учёта" value={stations.length === STORE_DEMO_STATIONS.length ? 'Вся сеть' : `${stations.length} АЗС`} />
                <ToolbarValue icon={Fuel} label="Вид топлива" value="Все виды" />

                <Button variant="ghost" className="ml-auto hidden shrink-0 xl:flex">
                  <Bookmark data-icon="inline-start" />
                  Виды
                </Button>
                <Button variant="ghost" size="icon" className="hidden shrink-0 xl:flex" aria-label="Обновить данные">
                  <RefreshCw />
                </Button>
              </div>

              <div className="flex gap-1 overflow-x-auto border-b border-border bg-card p-2 lg:hidden">
                {sectionViews.map((item) => (
                  <Button key={item.key} size="sm" variant={view === item.key ? 'secondary' : 'ghost'} className="shrink-0" onClick={() => setView(item.key)}>
                    {item.label}
                  </Button>
                ))}
              </div>

              <main className="min-h-0 flex-1 overflow-hidden bg-background" aria-live="polite">
                {view === 'station_console' ? (
                  <DemoStationConsole onOpen={openStation} />
                ) : DEMO_VIEWS.has(view) ? (
                  <StoreView
                    sub={view}
                    companyId="demo-shop"
                    dateFrom={dateFrom}
                    dateTo={END_DATE}
                    stations={stations}
                    demo
                  />
                ) : (
                  <StoreDemoRichView
                    key={view}
                    viewKey={view}
                    dateFrom={dateFrom}
                    dateTo={END_DATE}
                    stations={stations}
                  />
                )}
              </main>
            </div>
          </div>
        </div>

        <aside className="hidden w-[54px] shrink-0 flex-col items-center border-l border-border/40 bg-card xl:flex">
          <RightRailAction icon={MessageCircle} label="Чат" />
          <RightRailAction icon={ListChecks} label="Трек" />
          <RightRailAction icon={Headphones} label="Поддержка" />
          <RightRailAction icon={CircleHelp} label="Инфо" />
        </aside>
      </div>
    </div>
  )
}

function HeaderAction({ icon: Icon, label, compact = false, hideOnMobile = false }: {
  icon: typeof Video
  label: string
  compact?: boolean
  hideOnMobile?: boolean
}) {
  return (
    <Button variant="outline" className={cn(
      'h-10 border-primary/50 bg-primary/10 text-primary hover:bg-primary/15',
      compact && 'px-3',
      hideOnMobile && 'hidden sm:inline-flex',
    )}>
      <Icon data-icon="inline-start" />
      <span className="hidden 2xl:inline">{label}</span>
    </Button>
  )
}

function ToolbarValue({ icon: Icon, label, value }: {
  icon: typeof MapPin
  label: string
  value: string
}) {
  return (
    <div className="hidden h-11 shrink-0 items-center gap-2 rounded-lg border border-border bg-background/20 px-3 lg:flex">
      <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      <span className="leading-tight">
        <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
        <span className="block text-xs font-semibold">{value}</span>
      </span>
    </div>
  )
}

function RightRailAction({ icon: Icon, label }: { icon: typeof MessageCircle; label: string }) {
  return (
    <button type="button" className="flex w-full flex-col items-center gap-1.5 px-1 py-4 text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground">
      <Icon className="size-4" aria-hidden="true" />
      <span className="text-[10px]">{label}</span>
    </button>
  )
}
