/**
 * Панель параметров текущего вида (таба) — 4-й уровень управления рабочей области.
 *
 * Иерархия сверху вниз:
 *   1. ЭКРАНЫ            — закрепление и переключение экранов (WorkspaceTabBar)
 *   2. ФИЛЬТР области    — общий контур: период · сеть · данные (WorkspaceToolbar)
 *   3. ВИД               — табы конкретного пункта меню (PanelViewTabs)
 *   4. ПАРАМЕТРЫ         — настройка того, что показано ниже (этот компонент)
 *   5. Карточки / таблицы / графики
 *
 * Состав параметров индивидуален для каждого таба (разрез, метрика, шаг,
 * свой период, число строк…) — компонент задаёт только единую оболочку.
 */

import { SlidersHorizontal } from 'lucide-react'
import type { ReactNode } from 'react'

export function ViewParamsBar({
  children,
  label = 'Параметры',
}: {
  children: ReactNode
  /** Подпись слева; null — без подписи. */
  label?: string | null
}) {
  return (
    <div
      data-export-ignore
      data-zone="Параметры: как показано"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5"
    >
      {label ? (
        <span className="flex shrink-0 items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <SlidersHorizontal className="size-3.5" aria-hidden="true" />
          {label}
        </span>
      ) : null}
      {children}
    </div>
  )
}
