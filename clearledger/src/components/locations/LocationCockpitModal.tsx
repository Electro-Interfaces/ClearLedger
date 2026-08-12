/**
 * «Окно станции» (cockpit) — панель по точке обслуживания, открывается ВНУТРИ
 * рабочей области (правее сайдбара, под шапкой), не на весь вьюпорт.
 *
 * Тонкая оболочка: шапка (идентификация + статусы) + группированные вкладки.
 * Содержимое каждой вкладки — отдельный компонент в ./cockpit/*. IA: 9 вкладок в
 * 4 группах (Объект · Подключение · Сервис · Коммерция), контент адаптивен по типу.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Tabs as TabsPrimitive } from 'radix-ui'
import { Badge } from '@/components/ui/badge'
import { X } from 'lucide-react'
import { useLocationTypes } from '@/hooks/useLocationTypes'
import { useLocationContracts } from '@/hooks/useReferences'
import { resolveLocationIcon } from '@/components/locationTypes/locationIcons'
import { LOCATION_STATUS_META, locationValues, type ServiceLocation } from '@/types/location'
import { cockpitTabsFor, type CockpitGroup, type CockpitVariant } from './cockpit/tabsConfig'
import { OP_META } from './cockpit/shared'
import { PassportTab } from './cockpit/PassportTab'
import { EnergyTab } from './cockpit/EnergyTab'
import { StatusDiagnosticsTab } from './cockpit/StatusDiagnosticsTab'
import { ServiceTab } from './cockpit/ServiceTab'
import { ChatsTab } from './cockpit/ChatsTab'
import { ContractsTab } from './cockpit/ContractsTab'
import { SalesTab } from './cockpit/SalesTab'
import { SupplyTab } from './cockpit/SupplyTab'

export function LocationCockpitModal({
  location,
  onClose,
  onChanged,
  renderEdit,
  variant = 'full',
}: {
  location: ServiceLocation | null
  onClose: () => void
  onChanged?: () => void
  /** Триггер редактирования паспорта (оборачивает кнопку в LocationEditDialog). */
  renderEdit?: (location: ServiceLocation, child: ReactNode) => ReactNode
  /** intake = 4 таба (сырой ввод, левое меню), full = все табы (модуль «Объекты»). */
  variant?: CockpitVariant
}) {
  const types = useLocationTypes()
  // Карточка станции не режется по продукту (решение МАГа 12.08.2026): станция —
  // ось работы, и все направления по ней — паспорт, железо, энергия, связь,
  // обслуживание, договоры, реализация, снабжение — открываются из любого
  // рабочего места. Раньше разрез продукта прятал направления: из «Продаж» не
  // было видно ни оборудования, ни заявок, и человек считал, что их нет вовсе.

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

  // Сборка ряда вкладок с разделителями и подписями групп.
  const triggers: ReactNode[] = []
  let prevGroup: CockpitGroup | null = null
  for (const tab of cockpitTabsFor(variant, location.type)) {
    if (tab.group !== prevGroup) {
      if (prevGroup !== null) {
        triggers.push(<span key={`sep-${tab.group}`} aria-hidden className="mx-1.5 h-5 w-px shrink-0 self-center bg-border/60" />)
      }
      prevGroup = tab.group
    }
    const TabIcon = tab.icon
    triggers.push(
      <TabsPrimitive.Trigger
        key={tab.value}
        value={tab.value}
        className="group/tab relative -mb-px inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-t-md border border-b-0 border-transparent px-3.5 py-2 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-muted/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring data-[state=active]:border-border/60 data-[state=active]:bg-background data-[state=active]:text-primary"
      >
        <span aria-hidden className="absolute inset-x-0 top-[-1px] h-0.5 rounded-full bg-primary opacity-0 transition-opacity group-data-[state=active]/tab:opacity-100" />
        <TabIcon className="h-4 w-4 opacity-60 transition-opacity group-data-[state=active]/tab:opacity-100" />
        {tab.label}
        {tab.value === 'contracts' && contractsCount > 0 && (
          <Badge variant="secondary" className="ml-0.5 h-4 min-w-4 justify-center px-1 text-[10px] tabular-nums">
            {contractsCount}
          </Badge>
        )}
      </TabsPrimitive.Trigger>,
    )
  }

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
            </DialogPrimitive.Title>
            <DialogPrimitive.Close
              aria-label="Закрыть окно станции"
              className="ml-auto shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
          </div>

          <Tabs defaultValue="passport" className="flex flex-1 flex-col gap-0 overflow-hidden">
            <TabsPrimitive.List className="flex shrink-0 items-end gap-1 overflow-x-auto border-b border-border/50 bg-muted/20 px-2 pt-1.5">
              {triggers}
            </TabsPrimitive.List>

            <div className="flex-1 overflow-hidden">
              <TabsContent value="passport" className="m-0 h-full">
                <PassportTab location={location} renderEdit={renderEdit} />
              </TabsContent>
              <TabsContent value="energy" className="m-0 h-full">
                <EnergyTab location={location} />
              </TabsContent>
              <TabsContent value="diagnostics" className="m-0 h-full">
                <StatusDiagnosticsTab location={location} onChanged={onChanged} />
              </TabsContent>
              <TabsContent value="service" className="m-0 h-full">
                <ServiceTab location={location} />
              </TabsContent>
              <TabsContent value="contracts" className="m-0 h-full">
                <ContractsTab location={location} />
              </TabsContent>
              <TabsContent value="sales" className="m-0 h-full">
                <SalesTab location={location} />
              </TabsContent>
              <TabsContent value="supply" className="m-0 h-full">
                <SupplyTab location={location} />
              </TabsContent>
              <TabsContent value="chats" className="m-0 h-full">
                <ChatsTab location={location} />
              </TabsContent>
            </div>
          </Tabs>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
