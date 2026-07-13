/**
 * Общий тулбар рабочего стола — над панелями режимов.
 * Содержит свёрнутый основной фильтр рабочей области (`WorkspaceFilterBar`):
 * период · станция · точки · регионы · типы, с открытием модалки настройки.
 * Переключатель видов учёта — в вертикальном меню слева (`WorkspaceModeSidebar`).
 */

import { WorkspaceFilterBar } from './WorkspaceFilterBar'

export function WorkspaceToolbar() {
  return (
    <div className="flex shrink-0 items-center border-b border-border/60 bg-background px-2 py-1.5">
      <WorkspaceFilterBar />
    </div>
  )
}
