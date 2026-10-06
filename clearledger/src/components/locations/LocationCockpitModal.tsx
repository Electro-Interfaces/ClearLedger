/**
 * «Окно станции» (cockpit) — панель по точке обслуживания, открывается ВНУТРИ
 * рабочей области (правее сайдбара, под шапкой), не на весь вьюпорт.
 *
 * Тонкая оболочка: шапка (идентификация · статусы · действия) + четыре раздела,
 * внутри каждого — виды. Состав и причина именно такой группировки —
 * `./cockpit/tabsConfig.ts`; содержимое каждого вида — отдельный компонент в
 * `./cockpit/*`.
 *
 * Два уровня вместо одиннадцати вкладок (20.09.2026). Раздел отвечает на вопрос
 * «с какой стороны смотрим на станцию» — паспорт, право, работа, сервис; вид
 * внутри — «какой именно срез». Одиннадцать равноправных вкладок не помещались
 * в ряд и обрывались молча: половину разделов человек просто не находил.
 *
 * Действия (заявка, поручение, обсуждение) живут в шапке, а не внутри раздела:
 * они относятся к станции целиком. Инженер, нашедший беду в «Работе», заводит
 * заявку не уходя в «Сервис».
 */
import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCompany } from '@/contexts/CompanyContext'
import { getStationVisits } from '@/services/opsService'
import { AskSupportButton } from '@/components/support/AskSupportButton'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { Tabs } from '@/components/ui/tabs'
import { Tabs as TabsPrimitive } from 'radix-ui'
import { Badge } from '@/components/ui/badge'
import { X } from 'lucide-react'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { useLocationContracts } from '@/hooks/useReferences'
import { resolveLocationIcon } from '@/components/locationTypes/locationIcons'
import { LOCATION_STATUS_META, locationValues, type ServiceLocation } from '@/types/location'
import {
  cockpitSectionsFor, resolveLegacyTab, type CockpitVariant,
} from './cockpit/tabsConfig'
import { PanelViewTabs } from '@/components/workspace/PanelViewTabs'
import { MappingTab } from './cockpit/MappingTab'
import { StationActions } from '@/components/locations/StationActions'
import { OP_META } from './cockpit/shared'
import { PassportTab } from './cockpit/PassportTab'
import { EnergyTab } from './cockpit/EnergyTab'
import { StatusDiagnosticsTab } from './cockpit/StatusDiagnosticsTab'
import { WorkTab } from './cockpit/WorkTab'
import { ServiceTab } from './cockpit/ServiceTab'
import { CheckTab } from './cockpit/CheckTab'
import { TrackTab } from './cockpit/TrackTab'
import { ChatsTab } from './cockpit/ChatsTab'
import { ContractsTab } from './cockpit/ContractsTab'
import { ObligationsTab } from './cockpit/ObligationsTab'
import { SalesTab } from './cockpit/SalesTab'
import { SupplyTab } from './cockpit/SupplyTab'

/**
 * Успех приездов рядом с состоянием станции.
 *
 * «Работает» отвечает на вопрос, включена ли станция, а инженеру нужен второй:
 * уезжают ли от неё заряженными. Станция, у которой каждый пятый клиент уехал
 * ни с чем, числится работающей и в глаза не бросается — пока не посмотришь
 * раздел «Работа». Поэтому цифра стоит в шапке, у статуса.
 *
 * Считаем не здесь: те же визиты, что и во вкладке «Работа», и тот же ключ
 * кеша — при открытой вкладке запрос один на двоих.
 */
function УспехПриездов({ locationId }: { locationId: string }) {
  const { companyId } = useCompany()
  const { data } = useQuery({
    queryKey: ['station-visits', companyId, locationId, 90, false],
    queryFn: () => getStationVisits(companyId, locationId, { days: 90 }),
    enabled: !!companyId,
    staleTime: 60_000,
  })
  if (!data || !data.totals.visits) return null
  const успех = Math.round((100 - data.totals.failedPct) * 10) / 10
  return (
    <Badge variant="secondary" className={`text-[11px] ${
      успех >= 90 ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
        : успех >= 80 ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
          : 'bg-red-500/15 text-red-700 dark:text-red-400'}`}
      title={`За 90 дней приездов ${data.totals.visits}, уехали ни с чем ${data.totals.failed}. `
        + `Попыток на приезд ${data.totals.attemptsPerVisit}`}>
      зарядились {успех} %
    </Badge>
  )
}

export function LocationCockpitModal({
  location,
  onClose,
  onChanged,
  renderEdit,
  variant = 'full',
  initialTab,
}: {
  location: ServiceLocation | null
  onClose: () => void
  onChanged?: () => void
  /** Триггер редактирования паспорта (оборачивает кнопку в LocationEditDialog). */
  renderEdit?: (location: ServiceLocation, child: ReactNode) => ReactNode
  /** intake = сырой ввод (левое меню), full = все разделы (модуль «Объекты»). */
  variant?: CockpitVariant
  /** С какого места открыть: прежний ключ вкладки («contracts», «work»…). */
  initialTab?: string | null
}) {
  const types = useLocationTypes()
  // Карточка станции не режется по продукту (решение МАГа 12.08.2026): станция —
  // ось работы, и все направления по ней — паспорт, железо, энергия, связь,
  // обслуживание, договоры, реализация, снабжение — открываются из любого
  // рабочего места. Раньше разрез продукта прятал направления: из «Продаж» не
  // было видно ни оборудования, ни заявок, и человек считал, что их нет вовсе.

  // Куда открыть: прежние ключи вкладок продолжают работать — ссылки на
  // карточку живут в чужих экранах и в закладках людей.
  const начало = resolveLegacyTab(initialTab)
  const [раздел, setРаздел] = useState(начало.section)
  // Вид помним по каждому разделу: вернувшись в «Работу», человек попадает туда,
  // где был, а не на первый сегмент.
  const [виды, setВиды] = useState<Record<string, string>>({
    [начало.section]: начало.view,
  })

  // Портал направляем в рабочую область (SidebarInset), а не в body.
  const [container, setContainer] = useState<HTMLElement | null>(null)
  useEffect(() => {
    setContainer(document.getElementById('workspace-area'))
  }, [])

  // Счётчик договоров — для бейджа на вкладке (кэш разделяется с ContractsTab).
  const contractsQ = useLocationContracts(location?.id ?? null)
  const contractsCount = contractsQ.data?.contracts.length ?? 0

  if (!location) return null

  const typeDef = types.find((t) => t.code === location.type)
  const meta = locationValues(location)
  const Icon = resolveLocationIcon(typeDef?.icon)
  const curOp = location.operationalStatus ?? 'unknown'
  const lifeMeta = LOCATION_STATUS_META[location.status]

  const разделы = cockpitSectionsFor(variant, location.type)
  const текущий = разделы.find((s) => s.value === раздел) ?? разделы[0]
  const вид = виды[текущий.value] ?? текущий.views[0].k
  const видЕсть = текущий.views.some((v) => v.k === вид)
  const активныйВид = видЕсть ? вид : текущий.views[0].k

  const triggers: ReactNode[] = разделы.map((sec) => {
    const TabIcon = sec.icon
    return (
      <TabsPrimitive.Trigger
        key={sec.value}
        value={sec.value}
        className="group/tab relative -mb-px inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-t-md border border-b-0 border-transparent px-4 py-2 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-muted/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-border/60 data-[state=active]:bg-background data-[state=active]:text-primary"
      >
        <span aria-hidden className="absolute inset-x-0 top-[-1px] h-0.5 rounded-full bg-primary opacity-0 transition-opacity group-data-[state=active]/tab:opacity-100" />
        <TabIcon className="h-4 w-4 opacity-60 transition-opacity group-data-[state=active]/tab:opacity-100" />
        {sec.label}
        {/* Счётчик договоров — на разделе, где они лежат: «29» на «Праве»
            отвечает, есть ли вообще договорная обвязка, до открытия. */}
        {sec.value === 'legal' && contractsCount > 0 && (
          <Badge variant="secondary" className="ml-0.5 h-4 min-w-4 justify-center px-1 text-[10px] tabular-nums">
            {contractsCount}
          </Badge>
        )}
      </TabsPrimitive.Trigger>
    )
  })

  return (
    <DialogPrimitive.Root open={!!location} modal={false} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogPrimitive.Portal container={container ?? undefined}>
        <DialogPrimitive.Content
          onInteractOutside={(e) => e.preventDefault()}
          aria-describedby={undefined}
          className="absolute inset-0 z-40 flex flex-col gap-0 overflow-hidden border-l border-border/50 bg-background shadow-xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-right-4 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-right-4"
        >
          {/* Шапка */}
          <div className="flex items-start gap-3 border-b border-border/50 px-5 py-3">
            <DialogPrimitive.Title className="flex flex-1 flex-wrap items-center gap-3 text-lg">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
                <Icon className="h-4 w-4 text-muted-foreground" />
              </span>
              <span>{location.name}</span>
              <span className="font-mono text-sm text-muted-foreground">
                {String(meta.number ?? location.code)}
              </span>
              <Badge variant="secondary">{typeDef?.name ?? location.type}</Badge>
              {lifeMeta && <Badge variant="outline" className="text-[11px]">{lifeMeta.label}</Badge>}
              <Badge variant="secondary" className={`text-[11px] ${OP_META[curOp]?.cls ?? ''}`}>
                {OP_META[curOp]?.label ?? curOp}
              </Badge>
              {(location.type === 'ev_charging' || location.type === 'ezs') && (
                <УспехПриездов locationId={location.id} />
              )}
            </DialogPrimitive.Title>
            {/* Вопрос по объекту — поставщику программы, отсюда же: предметом
                уезжает номер и название, данные объекта остаются здесь
                (docs/BRIDGE.md §4.2). */}
            {/* Действия по станции целиком: завести заявку, поставить
                поручение, позвать людей в чат. В шапке, а не внутри раздела —
                беда находится в «Работе», а чинится в «Сервисе», и ходить между
                ними ради кнопки человек не станет. */}
            <span className="ml-auto flex shrink-0 items-center gap-2">
              <StationActions compact station={{
                id: location.id, name: location.name, code: location.code,
                number: String(meta.number ?? '') || null,
              }} />
              <AskSupportButton variant="ghost" subject={{
                kind: 'object', ref: String(location.id),
                label: `${location.name} · ${String(meta.number ?? location.code)}`,
              }} />
            </span>
            <DialogPrimitive.Close
              aria-label="Закрыть окно станции"
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>

          <Tabs value={текущий.value} onValueChange={setРаздел}
            className="flex flex-1 flex-col gap-0 overflow-hidden">
            <div className="relative shrink-0">
              <TabsPrimitive.List className="flex items-end gap-1 overflow-x-auto border-b border-border/50 bg-muted/20 px-2 pt-1.5">
                {triggers}
              </TabsPrimitive.List>
            </div>

            {/* Виды раздела — второй уровень (канон рабочей области §1): один и
                тот же предмет с разных сторон, поэтому сегменты, а не вкладки. */}
            {текущий.views.length > 1 && (
              <div className="shrink-0 border-b border-border/50 bg-muted/10 px-3">
                <PanelViewTabs
                  value={активныйВид}
                  onChange={(k) => setВиды((было) => ({ ...было, [текущий.value]: k }))}
                  label={null}
                  ariaLabel={`Виды раздела «${текущий.label}»`}
                  tabs={текущий.views.map((v) => ({ k: v.k, label: v.label }))} />
              </div>
            )}

            <div className="flex-1 overflow-hidden">
              {/* Паспорт */}
              {текущий.value === 'passport' && активныйВид === 'about' && (
                <PassportTab location={location} renderEdit={renderEdit} />
              )}
              {/* Маппинг */}
              {текущий.value === 'mapping' && <MappingTab location={location} />}

              {/* Право */}
              {текущий.value === 'legal' && активныйВид === 'obligations' && (
                <ObligationsTab location={location} />
              )}
              {текущий.value === 'legal' && активныйВид === 'contracts' && (
                <ContractsTab location={location} />
              )}
              {текущий.value === 'legal' && активныйВид === 'supply' && (
                <SupplyTab location={location} />
              )}

              {/* Работа */}
              {текущий.value === 'work' && активныйВид === 'diagnostics' && (
                <StatusDiagnosticsTab location={location} onChanged={onChanged} />
              )}
              {текущий.value === 'work' && активныйВид === 'visits' && (
                <WorkTab location={location} />
              )}
              {текущий.value === 'work' && активныйВид === 'energy' && (
                <EnergyTab location={location} />
              )}
              {текущий.value === 'work' && активныйВид === 'sales' && (
                <SalesTab location={location} />
              )}

              {/* Сервис */}
              {текущий.value === 'service' && активныйВид === 'tickets' && (
                <ServiceTab location={location} />
              )}
              {текущий.value === 'service' && активныйВид === 'check' && (
                <CheckTab location={location} />
              )}
              {текущий.value === 'service' && активныйВид === 'track' && (
                <TrackTab location={location} />
              )}
              {текущий.value === 'service' && активныйВид === 'chats' && (
                <ChatsTab location={location} />
              )}
            </div>
          </Tabs>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
