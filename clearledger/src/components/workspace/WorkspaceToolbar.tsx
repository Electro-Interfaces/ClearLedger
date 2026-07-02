/**
 * Общий тулбар рабочего стола — над панелями режимов.
 * Содержит свёрнутый основной фильтр рабочей области (`WorkspaceFilterBar`):
 * период · станция · точки · регионы · типы, с открытием модалки настройки.
 * Переключатель видов учёта — в вертикальном меню слева (`WorkspaceModeSidebar`).
 */

import { WorkspaceFilterBar } from './WorkspaceFilterBar'

export function WorkspaceToolbar() {
  return (
    <div className="flex items-center px-3 py-1.5 border-b border-border/50 bg-background flex-shrink-0">
      <WorkspaceFilterBar />
    </div>
  )
}
