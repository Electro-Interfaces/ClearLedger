/**
 * Стандартная структура центральной панели:
 * вертикальное текстовое меню слева + рабочая область справа.
 */

import { type ReactNode } from 'react'

export interface CentralMenuItem {
  key: string
  label: string
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
      <div className="flex flex-col gap-0.5 py-2 px-1.5 border-r border-border/30 bg-muted/20 shrink-0 min-w-0">
        {items.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onSelect(key)}
            className={`px-2.5 py-1.5 rounded-md text-[11px] font-medium text-left whitespace-nowrap transition-colors ${
              activeKey === key
                ? 'bg-primary/15 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Рабочая область */}
      <div className="flex-1 overflow-hidden">
        {children}
      </div>
    </div>
  )
}
