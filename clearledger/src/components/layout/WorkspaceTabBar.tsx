import { useRef, type KeyboardEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Pin, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTabs } from '@/contexts/TabsContext'
import { resolveTab, describeView } from '@/config/tabRegistry'
import { cn } from '@/lib/utils'

const HOME = '/'

export function WorkspaceTabBar() {
  const { tabs, pinTab, closeTab, isPinned } = useTabs()
  const navigate = useNavigate()
  const location = useLocation()
  const tabRefs = useRef(new Map<string, HTMLButtonElement>())
  const activeKey = location.pathname + location.search
  const current = describeView(location.pathname, location.search)
  const currentPinned = current ? isPinned(current.key) : false
  const canPin = !!current && !currentPinned

  if (tabs.length === 1 && tabs[0].key === HOME && activeKey === HOME) return null

  function close(key: string, isActive: boolean) {
    const nextKey = closeTab(key)
    if (isActive) navigate(nextKey)
  }

  function focusTab(key: string) {
    requestAnimationFrame(() => tabRefs.current.get(key)?.focus())
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | null = null
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = tabs.length - 1
    if (nextIndex !== null) {
      event.preventDefault()
      const next = tabs[nextIndex]
      navigate(next.key)
      focusTab(next.key)
      return
    }
    if (event.key === 'Delete' && tabs[index].closable) {
      event.preventDefault()
      const nextKey = closeTab(tabs[index].key)
      navigate(nextKey)
      focusTab(nextKey)
    }
  }

  function handlePin() {
    if (!current) return
    const result = pinTab(current)
    if (result === 'limit') {
      toast.warning('Слишком много закреплённых экранов', {
        description: 'Открепите один из экранов и повторите попытку.',
      })
    }
  }

  return (
    <div className="flex h-10 shrink-0 items-center border-b border-border/60 bg-muted/25 px-2">
      <ScrollArea className="h-9 min-w-0 flex-1">
        <div role="tablist" aria-label="Закреплённые экраны" className="flex h-9 min-w-max items-center gap-1 pr-2">
          {tabs.map((tab, index) => {
            const meta = resolveTab(tab.pathname)
            const Icon = meta?.icon
            const active = tab.key === activeKey
            return (
              <div
                key={tab.key}
                role="presentation"
                className={cn(
                  'group flex h-8 max-w-60 shrink-0 items-center rounded-lg transition-colors',
                  active
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-background/60 hover:text-foreground',
                )}
              >
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      ref={(node) => {
                        if (node) tabRefs.current.set(tab.key, node)
                        else tabRefs.current.delete(tab.key)
                      }}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      aria-current={active ? 'page' : undefined}
                      tabIndex={active || (!currentPinned && index === 0) ? 0 : -1}
                      onClick={() => navigate(tab.key)}
                      onAuxClick={(event) => {
                        if (event.button === 1 && tab.closable) {
                          event.preventDefault()
                          close(tab.key, active)
                        }
                      }}
                      onKeyDown={(event) => handleTabKeyDown(event, index)}
                      className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 pl-2.5 pr-2 text-xs font-medium"
                    >
                      {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden="true" /> : null}
                      <span className="truncate">{tab.title}</span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" sideOffset={6}>{tab.title}</TooltipContent>
                </Tooltip>

                {tab.closable ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className={cn(
                          'mr-1 rounded-md text-muted-foreground hover:text-destructive',
                          active ? 'opacity-80' : 'opacity-0 group-hover:opacity-80 group-focus-within:opacity-80',
                        )}
                        onClick={(event) => {
                          event.stopPropagation()
                          close(tab.key, active)
                        }}
                        aria-label={`Открепить экран «${tab.title}»`}
                      >
                        <X />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" sideOffset={6}>Открепить экран</TooltipContent>
                  </Tooltip>
                ) : null}
              </div>
            )
          })}
        </div>
        <ScrollBar orientation="horizontal" className="h-1.5" />
      </ScrollArea>

      {canPin ? (
        <div className="shrink-0 border-l border-border/60 pl-2">
          <Button variant="ghost" size="xs" className="h-7 rounded-md" onClick={handlePin}>
            <Pin data-icon="inline-start" />
            Закрепить экран
          </Button>
        </div>
      ) : null}
    </div>
  )
}
