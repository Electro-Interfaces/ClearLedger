/**
 * Стандартная структура центральной панели:
 * вертикальное текстовое меню слева + рабочая область справа.
 */

import { type ReactNode } from 'react'

export interface CentralMenuItem {
  key: string
  label: string
  /** Секция меню (напр. имя канала); при смене рисуется заголовок-группа */
  group?: string
  /** Разрез не настроен (нет источника/вида сверки) — приглушён */
  disabled?: boolean
}

interface CentralPanelLayoutProps {
  items: CentralMenuItem[]
  activeKey: string
  onSelect: (key: string) => void
  children: ReactNode
}

export function CentralPanelLayout({ items, activeKey, onSelect, children }: CentralPanelLayoutProps) {
  return (
    <div className="flex h-full">
      {/* Вертикальное меню */}
      <div className="flex flex-col gap-0.5 py-2 px-1.5 border-r border-border/30 bg-muted/20 shrink-0 min-w-0 overflow-y-auto">
        {items.map((item, i) => {
          const showHeader = !!item.group && item.group !== items[i - 1]?.group
          return (
            <div key={item.key}>
              {showHeader && (
                <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/60 whitespace-nowrap">
                  {item.group}
                </div>
              )}
              <button
                onClick={() => onSelect(item.key)}
                className={`w-full px-3 py-2 rounded-md text-sm font-medium text-left whitespace-nowrap transition-colors ${item.group ? 'pl-5' : ''} ${
                  activeKey === item.key
                    ? 'bg-primary/15 text-primary'
                    : item.disabled
                      ? 'text-muted-foreground/45 hover:text-muted-foreground hover:bg-accent/30'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                }`}
              >
                {item.label}
                {item.disabled && (
                  <span className="ml-1.5 text-[9px] uppercase tracking-wide opacity-70">не настроен</span>
                )}
              </button>
            </div>
          )
        })}
      </div>

      {/* Рабочая область */}
      <div className="flex-1 overflow-hidden">
        {children}
      </div>
    </div>
  )
}
