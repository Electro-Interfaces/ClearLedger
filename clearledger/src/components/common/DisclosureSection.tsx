/**
 * Единый сворачиваемый раздел «Расширенные параметры / детали» —
 * санкционированный стандартом управления сложностью жест раскрытия (§6.1).
 * Заменяет разрозненные ad-hoc реализации (useState-аккордеоны, самодельные
 * гармошки), чтобы «раскрытие» выглядело и вело себя одинаково во всём продукте.
 *
 * Доступность (WCAG 2.2, §6.1) наследуется от Radix Collapsible: триггер — это
 * <button> с aria-expanded, работает с клавиатуры (Enter/Space), имеет видимый
 * фокус. Поворот шеврона уважает prefers-reduced-motion.
 *
 * «Липкость» (правило 4 / §2): через controlled-режим (open/onOpenChange)
 * вызывающий может персистить состояние (localStorage), чтобы эксперту раздел
 * не сворачивался каждый заход.
 *
 * Информационный запах (§6.1): title обязан осмысленно называть содержимое —
 * «Расширенные условия сверки», а не «Ещё».
 */
import type { ReactNode, ElementType } from 'react'
import { ChevronDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'

export function DisclosureSection({
  title,
  icon: Icon,
  iconBg,
  iconColor,
  count,
  badge,
  defaultOpen = false,
  open,
  onOpenChange,
  className,
  triggerClassName,
  contentClassName,
  children,
}: {
  title: ReactNode
  icon?: ElementType
  iconBg?: string
  iconColor?: string
  /** Счётчик элементов внутри (напр. число активных фильтров) — виден на свёрнутом заголовке. */
  count?: number
  badge?: { label: string; className?: string }
  defaultOpen?: boolean
  /** Controlled-режим для «липкости»: передайте open+onOpenChange и персистите снаружи. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
  triggerClassName?: string
  contentClassName?: string
  children: ReactNode
}) {
  const controlled = open !== undefined
  return (
    <Collapsible
      defaultOpen={controlled ? undefined : defaultOpen}
      open={open}
      onOpenChange={onOpenChange}
      className={className}
    >
      <CollapsibleTrigger className={`flex items-center gap-3 w-full group py-2 cursor-pointer ${triggerClassName ?? ''}`}>
        {Icon && (
          <div
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
            style={iconBg ? { background: iconBg } : undefined}
          >
            <Icon className={`size-3.5 ${iconColor ?? 'text-muted-foreground'}`} />
          </div>
        )}
        <span className="text-sm font-medium text-foreground text-left">{title}</span>
        {count !== undefined && <Badge variant="secondary" className="text-xs">{count}</Badge>}
        {badge && (
          <Badge variant="outline" className={`text-xs ${badge.className ?? ''}`}>{badge.label}</Badge>
        )}
        <ChevronDown className="size-4 ml-auto text-muted-foreground transition-transform motion-reduce:transition-none group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className={contentClassName ?? 'mt-2 mb-4'}>
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}
