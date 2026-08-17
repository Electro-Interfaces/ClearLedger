/**
 * Стандартная структура центральной панели:
 * вертикальное текстовое меню слева + рабочая область справа.
 */

import { useEffect, useRef, type ReactNode } from 'react'

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
  const activeItem = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (window.matchMedia('(max-width: 1023px)').matches) {
      activeItem.current?.scrollIntoView({ block: 'nearest', inline: 'center' })
    }
  }, [activeKey])

  return (
    <div className="flex h-full min-w-0 flex-col lg:flex-row">
      {/* Вертикальное меню */}
      <div className="scrollbar-hide flex min-w-0 shrink-0 snap-x snap-proximity gap-0.5 overflow-x-auto border-b border-border/30 bg-muted/20 px-1.5 py-1.5 lg:flex-col lg:overflow-x-hidden lg:overflow-y-auto lg:border-b-0 lg:border-r lg:py-2">
        {items.map((item, i) => {
          const showHeader = !!item.group && item.group !== items[i - 1]?.group
          return (
            <div key={item.key} className="shrink-0 snap-start lg:w-full">
              {showHeader && (
                <div className="hidden whitespace-nowrap px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/60 lg:block">
                  {item.group}
                </div>
              )}
              <button
                ref={activeKey === item.key ? activeItem : undefined}
                onClick={() => onSelect(item.key)}
                className={`min-h-11 w-auto shrink-0 whitespace-nowrap rounded-md px-3 py-2 text-left text-sm font-medium transition-colors lg:min-h-0 lg:w-full ${item.group ? 'lg:pl-5' : ''} ${
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
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        {children}
      </div>
    </div>
  )
}
