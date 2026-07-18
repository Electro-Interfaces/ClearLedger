/**
 * Общий тулбар рабочего стола — над рабочей областью.
 * Ключевой инструмент: слева якорь-метка зоны «Фильтр рабочей области», далее —
 * свёрнутый основной фильтр (`WorkspaceFilterBar`): период · область · данные · источник.
 * Переключатель разрезов учёта — в вертикальном меню слева (`WorkspaceModeSidebar`).
 */

import { Filter } from 'lucide-react'
import { WorkspaceFilterBar } from './WorkspaceFilterBar'

export function WorkspaceToolbar() {
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-border bg-card px-3 py-3">
      {/* Якорь-метка зоны — фильтр важен для каждой рабочей области, обозначаем явно */}
      <div className="hidden shrink-0 items-center gap-2 self-stretch border-r border-border/60 pr-3 md:flex">
        <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Filter className="size-4" aria-hidden="true" />
        </span>
        <span className="leading-tight">
          <span className="block text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Фильтр</span>
          <span className="block text-xs font-semibold text-foreground">рабочей области</span>
        </span>
      </div>
      <WorkspaceFilterBar />
    </div>
  )
}
