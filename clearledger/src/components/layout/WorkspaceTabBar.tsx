/**
 * Горизонтальная полоса закреплённых вкладок — ниже верхнего Header, по ширине
 * рабочей области. Переход по меню сам вкладку НЕ создаёт: пользователь
 * закрепляет текущий вид кнопкой-пином справа. «Рабочий стол» (/) закреплён
 * всегда, без «×». Только десктоп.
 */
import { useLocation, useNavigate } from 'react-router-dom'
import { X, Pin } from 'lucide-react'
import { useTabs } from '@/contexts/TabsContext'
import { resolveTab, describeView } from '@/config/tabRegistry'
import { cn } from '@/lib/utils'

export function WorkspaceTabBar() {
  const { tabs, pinTab, closeTab, isPinned } = useTabs()
  const navigate = useNavigate()
  const location = useLocation()
  const activeKey = location.pathname + location.search

  function handleClose(key: string, isActive: boolean) {
    const next = closeTab(key)
    if (isActive) navigate(next)
  }

  const current = describeView(location.pathname, location.search)
  const currentPinned = current ? isPinned(current.key) : false
  // Закрепить можно любой открытый вид (включая рабочий стол); скрываем только на 404.
  const canPin = !!current

  // Нечего показывать (нет закладок и текущий вид не закрепляем) — полосу прячем.
  if (tabs.length === 0 && !canPin) return null

  return (
    <div className="flex items-end h-9 shrink-0 border-b border-border/60 bg-muted/40 overflow-x-auto scrollbar-hide px-2 gap-0.5">
      {/* Кнопка «Закрепить/Открепить» — всегда крайняя слева, вкладки правее */}
      {canPin && (
        <button
          onClick={() => {
            if (currentPinned) handleClose(current!.key, true)
            else pinTab(current!)
          }}
          title={currentPinned ? 'Открепить текущую страницу' : 'Закрепить текущую страницу во вкладках'}
          className={cn(
            'shrink-0 self-center flex items-center gap-1 h-6 mr-1 px-2 rounded-md text-xs border transition-colors',
            currentPinned
              ? 'border-primary/40 bg-primary/10 text-primary'
              : 'border-border/60 text-muted-foreground hover:text-foreground hover:bg-background/60',
          )}
        >
          <Pin className={cn('h-3.5 w-3.5', currentPinned && 'fill-current')} />
          {currentPinned ? 'Закреплено' : 'Закрепить'}
        </button>
      )}
      {tabs.map((tab) => {
        const meta = resolveTab(tab.pathname)
        const Icon = meta?.icon
        const isActive = tab.key === activeKey
        return (
          <div
            key={tab.key}
            onMouseDown={(e) => {
              if (e.button === 1 && tab.closable) { e.preventDefault(); handleClose(tab.key, isActive) }
            }}
            className={cn(
              'group flex items-center gap-1.5 pl-2.5 pr-1 h-7 rounded-t-md text-xs cursor-pointer transition-colors shrink-0 border border-b-0',
              isActive
                ? 'bg-background border-border/60 text-foreground font-medium -mb-px'
                : 'border-transparent text-muted-foreground hover:bg-background/40',
            )}
          >
            <button onClick={() => navigate(tab.key)} className="flex items-center gap-1.5 max-w-[190px]">
              {Icon && <Icon className="h-3.5 w-3.5 shrink-0" />}
              <span className="truncate">{tab.title}</span>
            </button>
            {tab.closable ? (
              <button
                onClick={(e) => { e.stopPropagation(); handleClose(tab.key, isActive) }}
                title="Открепить вкладку"
                className="h-4 w-4 flex items-center justify-center rounded hover:bg-destructive/20 hover:text-destructive opacity-60 group-hover:opacity-100 transition-opacity"
              >
                <X className="h-3 w-3" />
              </button>
            ) : (
              <span className="w-1" />
            )}
          </div>
        )
      })}
    </div>
  )
}
