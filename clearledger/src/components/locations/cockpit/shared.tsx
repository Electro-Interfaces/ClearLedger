/**
 * Общие примитивы и хелперы окна станции (cockpit).
 * Используются всеми вкладками: единый визуальный язык карточек/полей/заделов.
 */
import type { ReactNode, ComponentType } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { LocationType } from '@/types/location'

/**
 * Операционные статусы станции (метки + цвета бейджей).
 *
 * Первые четыре — состояние станции по данным CPO, переносятся 1:1 из выгрузки
 * («Активная»/«Нет связи»/«Отключена»/«Выведена из эксплуатации»). Остальные
 * приходят из других контуров: ручная смена статуса, HubEx, складской демонтаж.
 * unknown = данных CPO нет вообще (станции нет в выгрузке), а не «нет связи».
 */
export const OP_META: Record<string, { label: string; cls: string }> = {
  working: { label: 'Активная', cls: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' },
  no_link: { label: 'Нет связи', cls: 'bg-amber-400/15 text-amber-600 dark:text-amber-400/90' },
  disabled: { label: 'Отключена', cls: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400' },
  decommissioned: { label: 'Выведена из эксплуатации', cls: 'bg-zinc-500/10 text-zinc-500 dark:text-zinc-500' },
  not_working: { label: 'Не работает', cls: 'bg-red-500/15 text-red-600 dark:text-red-400' },
  on_repair: { label: 'На ремонте', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-400' },
  maintenance: { label: 'Обслуживание', cls: 'bg-blue-500/15 text-blue-600 dark:text-blue-400' },
  unknown: { label: 'Нет данных', cls: 'bg-muted text-muted-foreground' },
}
export const OP_OPTIONS = ['working', 'no_link', 'disabled', 'decommissioned',
  'not_working', 'on_repair', 'maintenance', 'unknown']

/**
 * Ключи metadata, относящиеся к ОБОРУДОВАНИЮ (вкладка «Оборудование»).
 * Паспорт показывает поля типа МИНУС эти, Оборудование — только эти. Без дублей.
 */
export const EQUIPMENT_KEYS = [
  'manufacturer', 'model', 'serialNumber',
  'connectorCount', 'connectorTypes', 'maxPowerKw', 'protocolOcpp', 'stage',
]

/** Флаги типа точки — единая точка ветвления контента по location.type. */
export function typeFlags(type: LocationType) {
  return {
    isFuel: type === 'fuel_station',
    // 'ezs' — зеркала реестра Поддержки: тип чужой, но объект тот же. Без этого
    // вкладки проваливались в ветку «офис» и писали «продажи не учитываются»
    // на действующей зарядной станции.
    isEv: type === 'ev_charging' || type === 'ezs',
    isRetail: type === 'retail',
    isFood: type === 'food',
    isWarehouse: type === 'warehouse',
    isOffice: type === 'office',
  }
}

/** Прокручиваемая обёртка тела вкладки (фикс. высота окна → внутренний скролл). */
export function ScrollTab({ children, maxWidth = 'max-w-3xl', plain }: {
  children: ReactNode
  maxWidth?: string
  /** Вкладка показана ВНУТРИ другой (паспорт вобрал оборудование и интеграции):
   *  своя область прокрутки и отступы тут лишние — вложенный скролл в скролле. */
  plain?: boolean
}) {
  if (plain) return <div className="space-y-4">{children}</div>
  return (
    <ScrollArea className="h-full">
      <div className={`p-5 space-y-4 ${maxWidth}`}>{children}</div>
    </ScrollArea>
  )
}

/** Карточка-секция с заголовком и опциональным действием справа. */
export function SectionCard({
  title, icon: Icon, action, children, muted,
}: {
  title: string
  icon?: ComponentType<{ className?: string }>
  action?: ReactNode
  children: ReactNode
  /** Приглушённый вид для блоков-заделов «в разработке». */
  muted?: boolean
}) {
  return (
    <Card className={muted ? 'border-dashed bg-muted/20' : undefined}>
      <CardContent className="pt-5">
        <div className="mb-3 flex items-center gap-2">
          {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
          <span className="text-xs font-medium text-muted-foreground">{title}</span>
          {action && <div className="ml-auto">{action}</div>}
        </div>
        {children}
      </CardContent>
    </Card>
  )
}

/** Строка «подпись → значение» в две колонки. */
export function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`font-medium break-words ${mono ? 'font-mono text-xs' : ''}`}>{value}</div>
    </div>
  )
}

/** Однострочная пара dt/dd с разделителем (для перечней реквизитов-заделов). */
export function InfoRow({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border/30 py-1.5 text-sm last:border-0">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="break-all text-right font-medium">{value}</span>
    </div>
  )
}

/** Пометка «в разработке» для блоков-заделов без источника данных. */
export function WipBadge({ children = 'в разработке' }: { children?: ReactNode }) {
  return (
    <Badge variant="outline" className="border-amber-400/40 text-[10px] font-normal text-amber-600 dark:text-amber-400/80">
      {children}
    </Badge>
  )
}

/** Центрированная заглушка для неприменимых разделов. */
export function Placeholder({ icon: Icon, title, text }: { icon: ComponentType<{ className?: string }>; title: string; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <Icon className="mb-3 h-10 w-10 opacity-40" />
      <p className="font-medium text-foreground/80">{title}</p>
      <p className="mt-1 max-w-md text-sm">{text}</p>
    </div>
  )
}
